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
from core.database import SessionLocal, User, Conversation, Message, CostingRequest, init_db
from main import invoke_agent

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
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

class RequestStatus(BaseModel):
    job_id: str
    item_details: str
    status: str
    price: Optional[float] = None
    created_at: Optional[datetime] = None

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
        session_state=request.state
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

# --- Costing Sheet Downloads ---

@app.get("/costing-sheets")
def list_costing_sheets(current_user: User = Depends(get_current_user)):
    """List all available costing sheets."""
    downloads_dir = "temp_downloads"
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
    file_path = os.path.join("temp_downloads", filename)

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

    file_path = os.path.join("temp_downloads", filename)
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

    file_path = os.path.join("temp_downloads", filename)
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
