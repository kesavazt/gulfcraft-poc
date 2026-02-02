from pydantic import PositiveInt
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.orm import sessionmaker, relationship, declarative_base
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy import Computed
from core import config
import json
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    role = Column(String, default="user")  # 'admin' or 'user'

'''class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    d365_id = Column(String, unique=True, index=True)
    name = Column(String, index=True)
    description = Column(Text)
    price = Column(Float)
    category = Column(String)
    embedding = Column(Vector(1536))  # OpenAI embedding size
    last_updated = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    # Add tsv column to support hybrid search
    tsv = Column(
        TSVECTOR,
        nullable=False,
        server_default=func.to_tsvector("english", description)
    )'''

# Create tables to ingest real data
class Product(Base):
    __tablename__ = "products"
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
    tsv = Column(
    TSVECTOR,
    Computed(
        "to_tsvector('english', description)",
        persisted=True
    )
    )

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
    quotation_id = Column(String, nullable=True)  # Selected quotation ID
    line_num = Column(Integer, nullable=True)  # Selected line number
    status = Column(String, default="Completed")  # Awaiting Quote, Completed
    item_details = Column(Text)
    price = Column(Float, nullable=True)
    sharepoint_url = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User")
    line_items = relationship("CostingLineItem", back_populates="costing_request")


class CostingLineItem(Base):
    """Individual line items in a costing job with their pricing status."""
    __tablename__ = "costing_line_items"
    id = Column(Integer, primary_key=True, index=True)
    costing_request_id = Column(Integer, ForeignKey("costing_requests.id"))
    item_name = Column(String)
    item_code = Column(String, nullable=True)
    quantity = Column(Integer, default=1)
    unit_price = Column(Float, nullable=True)
    price_status = Column(String, default="pending")  # resolved, pending_quote
    vendor_email = Column(String, nullable=True)
    item_type = Column(String, nullable=True)
    quote_requested_at = Column(DateTime(timezone=True), nullable=True)
    quote_received_at = Column(DateTime(timezone=True), nullable=True)

    # Price tracking fields - from estimation lines
    estimation_quantity = Column(Integer, nullable=True)  # Quantity from estimation
    estimation_average_price = Column(Float, nullable=True)  # Average price from estimation
    estimation_last_purchase_price = Column(Float, nullable=True)  # Last purchase price from estimation
    estimation_sales_price = Column(Float, nullable=True)  # Sales price from estimation

    # Price tracking fields - from products table lookup
    products_table_price = Column(Float, nullable=True)  # Unit cost from products table

    # Price source indicator
    price_source = Column(String, nullable=True)  # 'products', 'quotation', 'manual', 'pending', 'labour'

    costing_request = relationship("CostingRequest", back_populates="line_items")


class PendingQuoteRequest(Base):
    """Tracks pending email quote requests for items > threshold."""
    __tablename__ = "pending_quote_requests"
    id = Column(Integer, primary_key=True, index=True)
    costing_request_id = Column(Integer, ForeignKey("costing_requests.id"))
    costing_line_item_id = Column(Integer, ForeignKey("costing_line_items.id"))
    job_id = Column(String, index=True)  # For easy lookup by job_id in email subject
    item_name = Column(String)
    vendor_email = Column(String)
    email_sent_at = Column(DateTime(timezone=True), server_default=func.now())
    email_subject = Column(String)
    status = Column(String, default="pending")  # pending, received, timeout
    received_price = Column(Float, nullable=True)
    received_at = Column(DateTime(timezone=True), nullable=True)

# Setup Database Connection
engine = create_engine(config.DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in config.DATABASE_URL else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)     
