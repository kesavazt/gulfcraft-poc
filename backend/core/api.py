from fastapi import FastAPI, Depends, HTTPException, status, File, UploadFile, Form
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from datetime import timedelta, datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict
from jose import JWTError, jwt
import bcrypt
import os
import uuid
import glob as glob_module
import logging
import traceback
from core import config
from core.database import SessionLocal, User, Conversation, Message, CostingRequest, CostingLineItem, Product, EstimationLines, init_db
from main import invoke_agent
from utils import tools
from utils.lifecycle_tracing import get_job_metrics, get_aggregate_metrics
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app):
    # Startup: Ensure temp_downloads directory exists
    try:
        os.makedirs(config.TEMP_DOWNLOADS_DIR, exist_ok=True)
        print(f"[api] Temp downloads directory ready: {config.TEMP_DOWNLOADS_DIR}")
    except Exception as e:
        print(f"[api] Failed to create temp_downloads directory: {e}")

    # Startup: launch email monitor in background thread
    try:
        from services.email_monitor import start_email_monitor
        start_email_monitor()
        print("[api] Email monitor started")
    except Exception as e:
        print(f"[api] Email monitor failed to start: {e}")
    yield
    # Shutdown: stop email monitor
    try:
        from services.email_monitor import stop_email_monitor
        stop_email_monitor()
    except Exception:
        pass


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Health Check (Public Endpoint) ---
@app.get("/")
def root():
    return {"status": "ok", "service": "Gulf Craft Costing Agent", "version": "1.0.0"}

@app.get("/health")
def health():
    return {"status": "healthy", "database": "connected"}

# --- Auth Setup ---
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def hash_password(password):
    pwd_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed_password = bcrypt.hashpw(password=pwd_bytes, salt=salt)
    return hashed_password.decode('utf-8')

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, config.SECRET_KEY, algorithm=config.ALGORITHM)
    return encoded_jwt

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, config.SECRET_KEY, algorithms=[config.ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception
    return user

# --- Pydantic Models ---
class Token(BaseModel):
    access_token: str
    token_type: str

class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[int] = None
    state: Optional[dict] = None


class ChatResponse(BaseModel):
    response: str
    conversation_id: int
    state: Optional[dict] = None
    download_url: Optional[str] = None  # URL to download generated costing sheet

class LineItemSchema(BaseModel):
    id: int
    item_name: str
    item_code: Optional[str] = None
    quantity: int
    unit_price: Optional[float] = None
    price_status: str
    vendor_email: Optional[str] = None
    item_type: Optional[str] = None
    # Estimation tracking fields
    estimation_quantity: Optional[int] = None
    estimation_average_price: Optional[float] = None
    estimation_last_purchase_price: Optional[float] = None
    estimation_sales_price: Optional[float] = None
    # Products table tracking
    products_table_price: Optional[float] = None
    # Price source
    price_source: Optional[str] = None
    # Per-item margin (multiplier)
    margin: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)

class ProductSchema(BaseModel):
    id: int
    item_number: str
    unit_cost: Optional[float] = None
    vendor_email: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class LineItemUpdate(BaseModel):
    item_name: Optional[str] = None
    item_code: Optional[str] = None
    quantity: Optional[int] = None
    unit_price: Optional[float] = None
    item_type: Optional[str] = None
    margin: Optional[float] = None

class LineItemCreate(BaseModel):
    item_name: str
    item_code: Optional[str] = None
    quantity: int = 1
    unit_price: Optional[float] = None
    item_type: Optional[str] = "Item"
    vendor_email: Optional[str] = None
    margin: Optional[float] = None

class RequestStatus(BaseModel):
    id: int
    job_id: str
    item_details: str
    status: str
    price: Optional[float] = None
    created_at: Optional[datetime] = None
    line_items: List[LineItemSchema] = []

    model_config = ConfigDict(from_attributes=True)

# ...

@app.post("/token", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not bcrypt.checkpw(form_data.password.encode('utf-8'), user.hashed_password.encode('utf-8')):
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    access_token_expires = timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data={"sub": user.username}, expires_delta=access_token_expires)
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/users/me")
def read_users_me(current_user: User = Depends(get_current_user)):
    return {"username": current_user.username, "role": current_user.role}

# --- Chat Endpoints ---
@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Get or Create Conversation
    if request.conversation_id:
        conversation = db.query(Conversation).filter(Conversation.id == request.conversation_id, Conversation.user_id == current_user.id).first()
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        conversation = Conversation(user_id=current_user.id)
        db.add(conversation)
        db.commit()
        db.refresh(conversation)

    # Save User Message
    user_msg = Message(conversation_id=conversation.id, content=request.message, sender="user")
    db.add(user_msg)
    db.commit()

    # Load conversation history from DB
    conversation_history = []
    messages = db.query(Message).filter(
        Message.conversation_id == conversation.id
    ).order_by(Message.id).all()

    for msg in messages[:-1]:  # Exclude the message we just added
        conversation_history.append({
            "role": "user" if msg.sender == "user" else "assistant",
            "content": msg.content
        })

    # Invoke Agent with conversation history and previous state
    result = invoke_agent(
        message=request.message,
        user_id=current_user.id,
        threshold=config.PRICE_THRESHOLD,
        conversation_history=conversation_history,
        session_state=request.state,
        conversation_id=uuid.uuid5(uuid.NAMESPACE_URL, f"conv_{conversation.id}").hex  # Deterministic valid 32-char hex trace ID
    )


    # Save AI Message
    ai_msg = Message(conversation_id=conversation.id, content=result["response"], sender="ai")
    db.add(ai_msg)
    db.commit()

    # Check if a costing sheet was generated and build download URL
    download_url = None
    generated_file = result["state"].get("generated_file")
    if generated_file:
        # generated_file is just the filename (e.g., "costing_COST-00123456.xlsx")
        # Verify it exists before providing download URL
        full_path = os.path.join(config.TEMP_DOWNLOADS_DIR, generated_file)
        if os.path.exists(full_path):
            download_url = f"/costing-sheets/{generated_file}"
        else:
            print(f"[API] Warning: Generated file not found: {full_path}")

    return {
        "response": result["response"],
        "conversation_id": conversation.id,
        "state": result["state"],
        "download_url": download_url
    }

@app.get("/chat/history/{conversation_id}")
def get_history(conversation_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conversation = db.query(Conversation).filter(Conversation.id == conversation_id, Conversation.user_id == current_user.id).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation.messages

# --- Request Monitoring ---
@app.get("/requests", response_model=List[RequestStatus])
def get_requests(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role == "admin":
        requests = db.query(CostingRequest).all()
    else:
        requests = db.query(CostingRequest).filter(CostingRequest.user_id == current_user.id).all()

    # Always recalculate price based on current line items
    for req in requests:
        total_price = sum(
            (item.unit_price or 0) * (item.quantity or 1)
            for item in req.line_items
            if item.unit_price is not None
        )
        req.price = total_price if total_price > 0 else None

    db.commit()
    return requests

class ItemSearchResult(BaseModel):
    """Enhanced search result combining item info from multiple sources."""
    item_code: Optional[str] = None
    item_name: str
    unit_cost: Optional[float] = None
    vendor_email: Optional[str] = None
    source: str  # "product" or "estimation"

    model_config = ConfigDict(from_attributes=True)


@app.get("/products/search", response_model=List[ItemSearchResult])
def search_products(q: str, db: Session = Depends(get_db)):
    """
    Search for items by name or code across Products and EstimationLines tables.
    Returns combined results suitable for dropdown selection.
    """
    if not q or len(q) < 2:
        return []

    search_pattern = f"%{q}%"
    results = []
    seen_items = set()  # Track unique item_code to avoid duplicates

    # Search in Products table by item_number (code)
    products = db.query(Product).filter(
        Product.item_number.ilike(search_pattern)
    ).limit(20).all()

    for product in products:
        item_key = product.item_number
        if item_key not in seen_items:
            results.append({
                "item_code": product.item_number,
                "item_name": product.item_number,  # Use code as name since no name field
                "unit_cost": float(product.unit_cost) if product.unit_cost else None,
                "vendor_email": config.VENDOR_DEFAULT_EMAIL,
                "source": "product"
            })
            seen_items.add(item_key)

    # Search in EstimationLines by item_name (actual name/description)
    estimation_items = db.query(EstimationLines).filter(
        EstimationLines.item_name.ilike(search_pattern)
    ).limit(20).all()

    for item in estimation_items:
        item_key = item.std_item_code or item.item_name
        if item_key not in seen_items:
            # Try to get pricing from Product table
            product_price = None
            vendor_email = None
            if item.std_item_code:
                product = db.query(Product).filter(
                    Product.item_number == item.std_item_code
                ).first()
                if product:
                    product_price = float(product.unit_cost) if product.unit_cost else None

            results.append({
                "item_code": item.std_item_code,
                "item_name": item.item_name,
                "unit_cost": product_price or (float(item.sales_price) if item.sales_price else None),
                "vendor_email": config.VENDOR_DEFAULT_EMAIL,
                "source": "estimation"
            })
            seen_items.add(item_key)

    # Search in EstimationLines by item_code as well
    if not results or len(results) < 10:
        estimation_by_code = db.query(EstimationLines).filter(
            EstimationLines.std_item_code.ilike(search_pattern)
        ).limit(20).all()

        for item in estimation_by_code:
            item_key = item.std_item_code or item.item_name
            if item_key not in seen_items:
                product_price = None
                if item.std_item_code:
                    product = db.query(Product).filter(
                        Product.item_number == item.std_item_code
                    ).first()
                    if product:
                        product_price = float(product.unit_cost) if product.unit_cost else None

                results.append({
                    "item_code": item.std_item_code,
                    "item_name": item.item_name,
                    "unit_cost": product_price or (float(item.sales_price) if item.sales_price else None),
                    "vendor_email": config.VENDOR_DEFAULT_EMAIL,
                    "source": "estimation"
                })
                seen_items.add(item_key)

    # Sort by relevance (exact matches first, then partial matches)
    def sort_key(item):
        name_lower = item["item_name"].lower()
        code_lower = (item["item_code"] or "").lower()
        q_lower = q.lower()

        # Exact match gets highest priority
        if name_lower == q_lower or code_lower == q_lower:
            return 0
        # Starts with query gets second priority
        elif name_lower.startswith(q_lower) or code_lower.startswith(q_lower):
            return 1
        # Contains query gets third priority
        else:
            return 2

    results.sort(key=sort_key)

    # Return top 15 results
    return results[:15]


@app.get("/products/search/legacy", response_model=List[ProductSchema])
def search_products_legacy(q: str, db: Session = Depends(get_db)):
    """Legacy endpoint for backward compatibility."""
    if not q:
        return []
    products = db.query(Product).filter(Product.item_number.ilike(f"%{q}%")).limit(10).all()
    return products

@app.post("/requests/{job_id}/items", response_model=LineItemSchema)
def add_line_item(job_id: str, item: LineItemCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    request = db.query(CostingRequest).filter(CostingRequest.job_id == job_id).first()
    if not request:
        raise HTTPException(status_code=404, detail="Job not found")
    if current_user.role != "admin" and request.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Permission denied")

    new_item = CostingLineItem(
        costing_request_id=request.id,
        item_name=item.item_name,
        item_code=item.item_code,
        quantity=item.quantity,
        unit_price=item.unit_price,
        price_status="resolved" if item.unit_price is not None else "pending",
        price_source="manual",
        item_type=item.item_type,
        vendor_email=item.vendor_email,
        margin=item.margin if item.margin is not None else config.PROFIT_MARGIN
    )
    db.add(new_item)
    db.commit()
    db.refresh(new_item)

    # Recalculate total price
    total_price = 0
    all_items = db.query(CostingLineItem).filter(CostingLineItem.costing_request_id == request.id).all()
    for it in all_items:
        if it.unit_price:
            total_price += (it.unit_price * (it.quantity or 1))

    request.price = total_price
    db.commit()

    tools.regenerate_costing_sheet(job_id)
    return new_item

@app.delete("/requests/{job_id}/items/{item_id}")
def delete_line_item(job_id: str, item_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    request = db.query(CostingRequest).filter(CostingRequest.job_id == job_id).first()
    if not request:
        raise HTTPException(status_code=404, detail="Job not found")
    if current_user.role != "admin" and request.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Permission denied")

    line_item = db.query(CostingLineItem).filter(CostingLineItem.id == item_id, CostingLineItem.costing_request_id == request.id).first()
    if not line_item:
        raise HTTPException(status_code=404, detail="Line item not found")

    # Delete any pending quote requests for this line item first (foreign key constraint)
    from core.database import PendingQuoteRequest
    pending_quotes = db.query(PendingQuoteRequest).filter(
        PendingQuoteRequest.costing_line_item_id == item_id
    ).all()

    for pending_quote in pending_quotes:
        db.delete(pending_quote)

    # Now delete the line item
    db.delete(line_item)
    db.commit()

    # Recalculate total price
    total_price = 0
    all_items = db.query(CostingLineItem).filter(CostingLineItem.costing_request_id == request.id).all()
    for it in all_items:
        if it.unit_price:
            total_price += (it.unit_price * (it.quantity or 1))

    request.price = total_price
    db.commit()

    tools.regenerate_costing_sheet(job_id)
    return {"detail": "Item deleted"}

@app.put("/requests/{job_id}/items/{item_id}", response_model=LineItemSchema)
def update_line_item(job_id: str, item_id: int, item_update: LineItemUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Verify job exists and user has access
    request = db.query(CostingRequest).filter(CostingRequest.job_id == job_id).first()
    if not request:
        raise HTTPException(status_code=404, detail="Job not found")
    if current_user.role != "admin" and request.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Permission denied")

    line_item = db.query(CostingLineItem).filter(CostingLineItem.id == item_id, CostingLineItem.costing_request_id == request.id).first()
    if not line_item:
        raise HTTPException(status_code=404, detail="Line item not found")

    if item_update.unit_price is not None:
        line_item.unit_price = item_update.unit_price
        line_item.price_status = "resolved"
    if item_update.item_name is not None:
        line_item.item_name = item_update.item_name
    if item_update.item_code is not None:
        line_item.item_code = item_update.item_code
    if item_update.quantity is not None:
        line_item.quantity = item_update.quantity
    if item_update.item_type is not None:
        line_item.item_type = item_update.item_type
    if item_update.margin is not None:
        line_item.margin = item_update.margin

    db.commit()
    db.refresh(line_item)

    # Recalculate total price for the request
    total_price = 0
    all_items = db.query(CostingLineItem).filter(CostingLineItem.costing_request_id == request.id).all()
    for item in all_items:
        if item.unit_price:
            total_price += (item.unit_price * (item.quantity or 1))

    request.price = total_price
    db.commit()

    # Regenerate local file
    tools.regenerate_costing_sheet(job_id)

    return line_item

@app.post("/requests/{job_id}/approve")
def approve_job(job_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    request = db.query(CostingRequest).filter(CostingRequest.job_id == job_id).first()
    if not request:
        raise HTTPException(status_code=404, detail="Job not found")
    if current_user.role != "admin" and request.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Permission denied")

    request.status = "Approved"
    db.commit()

    # Regenerate sheet and get path
    file_path = tools.regenerate_costing_sheet(job_id)

    # Calculate total selling price (with margin) for SharePoint
    total_selling = 0
    all_items = db.query(CostingLineItem).filter(CostingLineItem.costing_request_id == request.id).all()
    for item in all_items:
        if item.unit_price:
            total_selling += (item.unit_price * (item.quantity or 1) * config.PROFIT_MARGIN)

    # Update SharePoint
    tools.update_sharepoint_status(job_id, status="Approved", price=round(total_selling, 2))

    # Send Notification Email with Attachment
    tools.send_costing_ready_notification(
        job_id=job_id,
        description=request.item_details or "",
        sharepoint_url=request.sharepoint_url,
        attachment_path=file_path
    )

    return {"status": "Approved", "job_id": job_id}

# --- Costing Sheet Downloads ---

@app.get("/costing-sheets")
def list_costing_sheets(current_user: User = Depends(get_current_user)):
    """List all available costing sheets."""
    downloads_dir = config.TEMP_DOWNLOADS_DIR
    if not os.path.exists(downloads_dir):
        return {"sheets": []}

    sheets = []
    for filepath in glob_module.glob(os.path.join(downloads_dir, "*.xlsx")):
        filename = os.path.basename(filepath)
        stat = os.stat(filepath)
        sheets.append({
            "filename": filename,
            "size": stat.st_size,
            "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
            "download_url": f"/costing-sheets/{filename}"
        })

    # Sort by creation time, newest first
    sheets.sort(key=lambda x: x["created"], reverse=True)
    return {"sheets": sheets}


@app.get("/costing-sheets/by-job/{job_id}")
def download_costing_sheet_by_job(job_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Download a costing sheet by job ID. Regenerates if not found."""
    # Prevent directory traversal
    if ".." in job_id or "/" in job_id or "\\" in job_id:
        raise HTTPException(status_code=400, detail="Invalid job ID")

    # The filename pattern is costing_{job_id}.xlsx
    filename = f"costing_{job_id}.xlsx"
    file_path = os.path.join(config.TEMP_DOWNLOADS_DIR, filename)

    # If file doesn't exist, regenerate it
    if not os.path.exists(file_path):
        logger.info(f"Costing sheet not found for job {job_id}, attempting regeneration")

        # Get the costing request from database
        costing_req = db.query(CostingRequest).filter(CostingRequest.job_id == job_id).first()

        if not costing_req:
            logger.error(f"Job {job_id} not found in database")
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

        logger.debug(f"Found costing request: id={costing_req.id}, quotation_id={costing_req.quotation_id}, item_details={costing_req.item_details}")

        # Check user has access to this job
        if current_user.role != "admin" and costing_req.user_id != current_user.id:
            logger.warning(f"User {current_user.username} denied access to job {job_id}")
            raise HTTPException(status_code=403, detail="Access denied")

        # Get line items for this job
        line_items = db.query(CostingLineItem).filter(
            CostingLineItem.costing_request_id == costing_req.id
        ).all()

        logger.info(f"Retrieved {len(line_items)} line items for job {job_id}")

        # Convert to the format expected by create_costing_sheet_with_items
        items_data = []
        for idx, item in enumerate(line_items):
            item_dict = {
                "item_name": item.item_name,
                "item_code": item.item_code or "",
                "quantity": item.quantity or 1,
                "unit_price": item.unit_price,
                "price_status": item.price_status or "resolved",
                "item_type": item.item_type,
                "estimation_quantity": item.estimation_quantity,
                "estimation_last_purchase_price": item.estimation_last_purchase_price,
                "estimation_average_price": item.estimation_average_price,
                "products_table_price": item.products_table_price,
                "price_source": item.price_source,
                "margin": None,  # Will use default margin from config
            }
            items_data.append(item_dict)
            logger.debug(f"Item {idx}: {item_dict}")

        # Regenerate the costing sheet
        try:
            logger.info(f"Calling create_costing_sheet_with_items for job {job_id}")
            generated_filename = tools.create_costing_sheet_with_items(
                job_id=job_id,
                items=items_data,
                quotation_id=costing_req.quotation_id or "N/A",
                description=costing_req.item_details or "Costing Request"
            )
            file_path = os.path.join(config.TEMP_DOWNLOADS_DIR, generated_filename)
            logger.info(f"Successfully regenerated costing sheet: {generated_filename}")
        except Exception as e:
            logger.error(f"Failed to regenerate costing sheet for job {job_id}: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=f"Failed to regenerate costing sheet: {str(e)}")

    return FileResponse(
        file_path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"}
    )


@app.get("/costing-sheets/{filename}")
def download_costing_sheet(filename: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Download a specific costing sheet. Regenerates if not found."""
    # Prevent directory traversal
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    file_path = os.path.join(config.TEMP_DOWNLOADS_DIR, filename)

    # If file doesn't exist, try to regenerate it if it follows the costing_{job_id}.xlsx pattern
    if not os.path.exists(file_path):
        # Extract job_id from filename (pattern: costing_{job_id}.xlsx)
        if filename.startswith("costing_") and filename.endswith(".xlsx"):
            job_id = filename[8:-5]  # Remove "costing_" prefix and ".xlsx" suffix
            logger.info(f"Costing sheet {filename} not found for job {job_id}, attempting regeneration")

            # Get the costing request from database
            costing_req = db.query(CostingRequest).filter(CostingRequest.job_id == job_id).first()

            if not costing_req:
                logger.error(f"Job {job_id} not found in database")
                raise HTTPException(status_code=404, detail="Costing sheet not found")

            logger.debug(f"Found costing request: id={costing_req.id}, quotation_id={costing_req.quotation_id}, item_details={costing_req.item_details}")

            # Check user has access to this job
            if current_user.role != "admin" and costing_req.user_id != current_user.id:
                logger.warning(f"User {current_user.username} denied access to job {job_id}")
                raise HTTPException(status_code=403, detail="Access denied")

            # Get line items for this job
            line_items = db.query(CostingLineItem).filter(
                CostingLineItem.costing_request_id == costing_req.id
            ).all()

            logger.info(f"Retrieved {len(line_items)} line items for job {job_id}")

            # Convert to the format expected by create_costing_sheet_with_items
            items_data = []
            for idx, item in enumerate(line_items):
                item_dict = {
                    "item_name": item.item_name,
                    "item_code": item.item_code or "",
                    "quantity": item.quantity or 1,
                    "unit_price": item.unit_price,
                    "price_status": item.price_status or "resolved",
                    "item_type": item.item_type,
                    "estimation_quantity": item.estimation_quantity,
                    "estimation_last_purchase_price": item.estimation_last_purchase_price,
                    "estimation_average_price": item.estimation_average_price,
                    "products_table_price": item.products_table_price,
                    "price_source": item.price_source,
                    "margin": None,  # Will use default margin from config
                }
                items_data.append(item_dict)
                logger.debug(f"Item {idx}: {item_dict}")

            # Regenerate the costing sheet
            try:
                logger.info(f"Calling create_costing_sheet_with_items for job {job_id}")
                generated_filename = tools.create_costing_sheet_with_items(
                    job_id=job_id,
                    items=items_data,
                    quotation_id=costing_req.quotation_id or "N/A",
                    description=costing_req.item_details or "Costing Request"
                )
                file_path = os.path.join(config.TEMP_DOWNLOADS_DIR, generated_filename)
                logger.info(f"Successfully regenerated costing sheet: {generated_filename}")
            except Exception as e:
                logger.error(f"Failed to regenerate costing sheet for job {job_id}: {str(e)}")
                logger.error(f"Traceback: {traceback.format_exc()}")
                raise HTTPException(status_code=500, detail=f"Failed to regenerate costing sheet: {str(e)}")
        else:
            logger.warning(f"File {filename} not found and doesn't match costing sheet pattern")
            raise HTTPException(status_code=404, detail="Costing sheet not found")

    return FileResponse(
        file_path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"}
    )


@app.get("/download/{filename}")
def download_file(filename: str, current_user: User = Depends(get_current_user)):
    """Generic file download endpoint."""
    # Prevent directory traversal
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    file_path = os.path.join(config.TEMP_DOWNLOADS_DIR, filename)
    if os.path.exists(file_path):
        return FileResponse(
            file_path,
            filename=filename,
            headers={"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"}
        )
    raise HTTPException(status_code=404, detail="File not found")


# --- Job Duration Metrics Endpoints ---

class JobMetricsResponse(BaseModel):
    """Response schema for job metrics."""
    job_id: str
    status: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    quotes_requested_at: Optional[str] = None
    all_quotes_received_at: Optional[str] = None
    approved_at: Optional[str] = None
    cancelled_at: Optional[str] = None
    original_job_id: Optional[str] = None
    item_metrics: dict
    quote_metrics: dict
    durations: dict

    model_config = ConfigDict(from_attributes=True)


class AggregateMetricsResponse(BaseModel):
    """Response schema for aggregate metrics."""
    period_days: int
    total_jobs: int
    status_breakdown: Optional[dict] = None
    avg_time_to_approval: Optional[dict] = None
    avg_quote_wait_time: Optional[dict] = None
    jobs_pending_quotes: Optional[int] = None
    jobs_ready: Optional[int] = None
    jobs_approved: Optional[int] = None
    message: Optional[str] = None
    error: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


@app.get("/metrics/job/{job_id}", response_model=JobMetricsResponse)
def get_job_metrics_endpoint(job_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Get comprehensive duration metrics for a specific job.

    Returns timestamps for key lifecycle events and calculated durations:
    - Time from creation to first quote request
    - Time waiting for all quotes
    - Time from ready to approval
    - Total time to completion
    """
    # Verify user has access to this job
    request = db.query(CostingRequest).filter(CostingRequest.job_id == job_id).first()
    if not request:
        raise HTTPException(status_code=404, detail="Job not found")
    if current_user.role != "admin" and request.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Permission denied")

    metrics = get_job_metrics(job_id)
    if not metrics:
        raise HTTPException(status_code=404, detail="Metrics not available for this job")

    return metrics


@app.get("/metrics/aggregate", response_model=AggregateMetricsResponse)
def get_aggregate_metrics_endpoint(
    days: int = 30,
    current_user: User = Depends(get_current_user)
):
    """
    Get aggregate metrics across all jobs for the current user.

    Args:
        days: Number of days to look back (default: 30)

    Returns:
        - Total jobs in period
        - Status breakdown
        - Average time to approval
        - Average quote wait time
        - Jobs pending/ready/approved counts
    """
    # Regular users only see their own metrics, admins see all
    user_id = None if current_user.role == "admin" else current_user.id

    metrics = get_aggregate_metrics(user_id=user_id, days=days)
    return metrics


@app.get("/metrics/job/{job_id}/timeline")
def get_job_timeline(job_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Get a timeline of events for a specific job.

    Returns a chronological list of lifecycle events with timestamps.
    """
    from core.database import PendingQuoteRequest, CostingLineItem

    # Verify user has access to this job
    request = db.query(CostingRequest).filter(CostingRequest.job_id == job_id).first()
    if not request:
        raise HTTPException(status_code=404, detail="Job not found")
    if current_user.role != "admin" and request.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Permission denied")

    timeline = []

    # Job created
    if request.created_at:
        timeline.append({
            "event": "job.created",
            "timestamp": request.created_at.isoformat(),
            "details": {"description": request.item_details}
        })

    # First quote requested
    if request.quotes_requested_at:
        timeline.append({
            "event": "job.quotes_requested",
            "timestamp": request.quotes_requested_at.isoformat(),
            "details": {}
        })

    # Individual quote requests
    quote_requests = db.query(PendingQuoteRequest).filter(
        PendingQuoteRequest.costing_request_id == request.id
    ).order_by(PendingQuoteRequest.email_sent_at).all()

    for qr in quote_requests:
        if qr.email_sent_at:
            timeline.append({
                "event": "quote.requested",
                "timestamp": qr.email_sent_at.isoformat(),
                "details": {
                    "item_name": qr.item_name,
                    "vendor_email": qr.vendor_email
                }
            })

        if qr.received_at:
            timeline.append({
                "event": "quote.received",
                "timestamp": qr.received_at.isoformat(),
                "details": {
                    "item_name": qr.item_name,
                    "price": qr.received_price
                }
            })

    # All quotes received (job ready)
    if request.all_quotes_received_at:
        timeline.append({
            "event": "job.ready",
            "timestamp": request.all_quotes_received_at.isoformat(),
            "details": {}
        })

    # Job approved
    if request.approved_at:
        timeline.append({
            "event": "job.approved",
            "timestamp": request.approved_at.isoformat(),
            "details": {}
        })

    # Job cancelled
    if request.cancelled_at:
        timeline.append({
            "event": "job.cancelled",
            "timestamp": request.cancelled_at.isoformat(),
            "details": {}
        })

    # Sort by timestamp
    timeline.sort(key=lambda x: x["timestamp"])

    return {
        "job_id": job_id,
        "status": request.status,
        "timeline": timeline
    }


# --- Quote PDF Upload ---
@app.post("/chat/upload-quote")
async def upload_quote_pdf(
    file: UploadFile = File(...),
    job_id: str = Form(...),
    conversation_id: Optional[int] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Upload a vendor quote PDF, extract line items via OCR, and match to pending items."""
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    costing_req = db.query(CostingRequest).filter(CostingRequest.job_id == job_id).first()
    if not costing_req:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    upload_dir = os.path.join(config.TEMP_DOWNLOADS_DIR, "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    temp_path = os.path.join(upload_dir, f"{job_id}_{uuid.uuid4().hex[:8]}_{file.filename}")

    try:
        content = await file.read()
        with open(temp_path, "wb") as f:
            f.write(content)

        from services.pdf_extractor import extract_line_items_from_pdf
        extracted_items = extract_line_items_from_pdf(temp_path)

        if not extracted_items:
            return {
                "status": "no_items",
                "message": "Could not extract any line items from the uploaded PDF.",
                "extracted_count": 0,
                "matches": [],
                "job_id": job_id
            }

        from services.ocr_matcher import match_ocr_items_to_pending
        matches = match_ocr_items_to_pending(job_id, extracted_items)

        match_details = []
        for match in matches:
            ocr_item = match["ocr_item"]
            line_item_id = match["matched_line_item_id"]

            # Skip matches with no valid line_item_id (would cause 422 on confirm)
            if line_item_id is None:
                print(f"[UploadQuote] Skipping match with no line_item_id: {ocr_item.get('item_name')}")
                continue

            detail = {
                "line_item_id": line_item_id,
                "pending_request_id": match.get("pending_request_id"),
                "ocr_item_name": ocr_item.get("item_name"),
                "ocr_unit_price": ocr_item.get("unit_price"),
                "ocr_quantity": ocr_item.get("quantity"),
                "confidence": match["confidence"],
                "match_reason": match.get("match_reason", ""),
                "pending_item_name": match.get("pending_item_name", ""),
            }
            li = db.query(CostingLineItem).filter(CostingLineItem.id == line_item_id).first()
            if li:
                detail["pending_item_name"] = li.item_name
                detail["current_price"] = li.unit_price
                detail["current_status"] = li.price_status
            match_details.append(detail)

        if conversation_id:
            upload_msg = Message(
                conversation_id=conversation_id,
                content=f"[Uploaded vendor quote PDF: {file.filename}]",
                sender="user"
            )
            db.add(upload_msg)
            db.commit()

        return {
            "status": "matches_found" if match_details else "no_matches",
            "message": f"Extracted {len(extracted_items)} items from PDF, matched {len(match_details)} to pending quotes.",
            "extracted_count": len(extracted_items),
            "matches": match_details,
            "job_id": job_id
        }
    except Exception as e:
        print(f"[UploadQuote] Error processing PDF: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to process PDF: {str(e)}")
    finally:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass


class QuoteMatchItem(BaseModel):
    line_item_id: int
    price: Optional[float] = None
    apply: bool = True

class QuoteMatchConfirmation(BaseModel):
    job_id: str
    matches: List[QuoteMatchItem]

@app.post("/chat/confirm-quote-matches")
def confirm_quote_matches(
    confirmation: QuoteMatchConfirmation,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Apply confirmed quote matches from PDF extraction."""
    costing_req = db.query(CostingRequest).filter(
        CostingRequest.job_id == confirmation.job_id
    ).first()
    if not costing_req:
        raise HTTPException(status_code=404, detail=f"Job {confirmation.job_id} not found")

    applied = []
    skipped = []

    for match in confirmation.matches:
        if not match.apply:
            skipped.append(match.line_item_id)
            continue
        if match.price is None:
            print(f"[ConfirmQuote] Skipping line_item_id {match.line_item_id}: no price provided")
            skipped.append(match.line_item_id)
            continue
        success = tools.mark_quote_received_by_id(
            line_item_id=match.line_item_id,
            price=match.price,
            job_id=confirmation.job_id
        )
        if success:
            applied.append(match.line_item_id)
        else:
            skipped.append(match.line_item_id)

    quote_status = tools.check_all_quotes_received(confirmation.job_id)

    # Build download URL for the regenerated sheet
    download_url = f"/costing-sheets/by-job/{confirmation.job_id}"

    return {
        "status": "success",
        "applied_count": len(applied),
        "skipped_count": len(skipped),
        "all_quotes_received": quote_status.get("all_received", False),
        "pending_items": quote_status.get("pending_items", []),
        "job_id": confirmation.job_id,
        "download_url": download_url
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
