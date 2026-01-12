from pydantic import PositiveInt
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector
import config
import json
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    role = Column(String, default="user")  # 'admin' or 'user'

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    d365_id = Column(String, unique=True, index=True)
    name = Column(String, index=True)
    description = Column(Text)
    price = Column(Float)
    category = Column(String)
    embedding = Column(Vector(1536))  # OpenAI embedding size
    last_updated = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

# Create tables to ingest real data
class Inventory(Base):
    __tablename__ = "inventory"
    id = Column(Integer,autoincrement=True,primary_key=True)
    item_number = Column(String)
    unit_cost = Column(Integer)
    vendor_email = Column(String)

class QuotationLines(Base):
    __tablename__ = "quotation_lines"
    id = Column(Integer,primary_key=True,index=True,autoincrement=True) # quotationId can't be used as primary key
    quotation_id = Column(String)
    line_num = Column(Integer)
    description = Column(String)
    sales_price = Column(Integer)
    afz_boat_model_id = Column(String)
    embedding = Column(Vector(1536))

class EstimationLines(Base):
    __tablename__ = "estimation_lines"
    id = Column(Integer,primary_key=True,autoincrement=True)
    quotation_id = Column(String) # can't make this the foreign key either
    line_num = Column(Integer)
    item_type = Column(String) # must use item_type = "Item"
    item_name = Column(String)
    std_item_code = Column(String)
    uom = Column(String)
    item_qty = Column(Integer)
    average_price = Column(Integer)
    last_purchase_price = Column(Integer)
    sales_price = Column(Integer)

class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    user = relationship("User")
    messages = relationship("Message", back_populates="conversation")

class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"))
    content = Column(Text)
    sender = Column(String)  # 'user' or 'ai'
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    conversation = relationship("Conversation", back_populates="messages")

class CostingRequest(Base):
    __tablename__ = "costing_requests"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    job_id = Column(String, unique=True, index=True)
    status = Column(String, default="Pending")  # Pending, Quotation Requested, Completed
    item_details = Column(Text)
    price = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User")

# Setup Database Connection
engine = create_engine(config.DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in config.DATABASE_URL else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)     
