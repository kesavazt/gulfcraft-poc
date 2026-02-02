from fastapi import FastAPI, Depends, HTTPException, status
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
import glob as glob_module
from core import config
from core.database import SessionLocal, User, Conversation, Message, CostingRequest, CostingLineItem, Product, EstimationLines, init_db
from main import invoke_agent
from utils import tools

app = FastAPI()

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
        expire = datetime.utcnow() + timedelta(minutes=15)
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

class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "user"

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

class LineItemCreate(BaseModel):
    item_name: str
    item_code: Optional[str] = None
    quantity: int = 1
    unit_price: Optional[float] = None
    item_type: Optional[str] = "Item"
    vendor_email: Optional[str] = None

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

@app.post("/auth/register", response_model=Token)
def register(user: UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.username == user.username).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    hashed_password = hash_password(user.password)
    new_user = User(username=user.username, hashed_password=hashed_password, role=user.role)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    access_token = create_access_token(data={"sub": new_user.username})
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/token", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not bcrypt.checkpw(form_data.password.encode('utf-8'), user.hashed_password.encode('utf-8')):
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    access_token = create_access_token(data={"sub": user.username})
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
        conversation_id=f"conv_{conversation.id}"  # Maintain consistent conversation trace
    )


    # Save AI Message
    ai_msg = Message(conversation_id=conversation.id, content=result["response"], sender="ai")
    db.add(ai_msg)
    db.commit()

    # Check if a costing sheet was generated and build download URL
    download_url = None
    generated_file = result["state"].get("generated_file")
    if generated_file and os.path.exists(generated_file):
        filename = os.path.basename(generated_file)
        download_url = f"/costing-sheets/{filename}"

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
                "vendor_email": product.vendor_email,
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
                    vendor_email = product.vendor_email

            results.append({
                "item_code": item.std_item_code,
                "item_name": item.item_name,
                "unit_cost": product_price or (float(item.sales_price) if item.sales_price else None),
                "vendor_email": vendor_email or config.VENDOR_DEFAULT_EMAIL,
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
                vendor_email = None
                if item.std_item_code:
                    product = db.query(Product).filter(
                        Product.item_number == item.std_item_code
                    ).first()
                    if product:
                        product_price = float(product.unit_cost) if product.unit_cost else None
                        vendor_email = product.vendor_email

                results.append({
                    "item_code": item.std_item_code,
                    "item_name": item.item_name,
                    "unit_cost": product_price or (float(item.sales_price) if item.sales_price else None),
                    "vendor_email": vendor_email or config.VENDOR_DEFAULT_EMAIL,
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
        item_type=item.item_type,
        vendor_email=item.vendor_email
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
def download_costing_sheet_by_job(job_id: str, current_user: User = Depends(get_current_user)):
    """Download a costing sheet by job ID."""
    # Prevent directory traversal
    if ".." in job_id or "/" in job_id or "\\" in job_id:
        raise HTTPException(status_code=400, detail="Invalid job ID")

    # The filename pattern is costing_{job_id}.xlsx
    filename = f"costing_{job_id}.xlsx"
    file_path = os.path.join(config.TEMP_DOWNLOADS_DIR, filename)

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Costing sheet for job {job_id} not found")

    return FileResponse(
        file_path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"}
    )


@app.get("/costing-sheets/{filename}")
def download_costing_sheet(filename: str, current_user: User = Depends(get_current_user)):
    """Download a specific costing sheet."""
    # Prevent directory traversal
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    file_path = os.path.join(config.TEMP_DOWNLOADS_DIR, filename)
    if not os.path.exists(file_path):
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
