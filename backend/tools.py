import uuid
import random
import time
import os
import json
from typing import List, Dict, Any, Optional
import config
import templates
from search import hybrid_search
from database import SessionLocal, CostingRequest, Product
from openpyxl import load_workbook

# --- SharePoint Tools ---

def create_sharepoint_job(details: str, user_id: int) -> str:
    """Creates a new costing job in SharePoint (Mock) and DB."""
    job_id = f"JOB-{uuid.uuid4().hex[:8].upper()}"
    print(f"[SharePoint] Created Job {job_id} for: {details}")
    
    # Store in DB
    session = SessionLocal()
    try:
        req = CostingRequest(
            user_id=user_id,
            job_id=job_id,
            item_details=details,
            status="Pending"
        )
        session.add(req)
        session.commit()
    except Exception as e:
        print(f"DB Error: {e}")
    finally:
        session.close()
        
    return job_id

def update_sharepoint_job(job_id: str, data: Dict[str, Any]):
    """Updates a costing job in SharePoint (Mock) and DB."""
    print(f"[SharePoint] Updating Job {job_id} with: {data}")
    
    session = SessionLocal()
    try:
        req = session.query(CostingRequest).filter(CostingRequest.job_id == job_id).first()
        if req:
            if "price" in data:
                req.price = data["price"]
            if "status" in data:
                req.status = data["status"]
            session.commit()
    except Exception as e:
        print(f"DB Error: {e}")
    finally:
        session.close()

def generate_costing_sheet(job_id: str, details: str, price: float) -> str:
    """Generates an Excel costing sheet from template."""
    try:
        wb = load_workbook(config.COSTING_TEMPLATE_PATH)
        ws = wb.active
        
        # Append new row
        ws.append([job_id, details, price, "Completed", time.strftime("%Y-%m-%d")])
        
        # Save to a temp file
        filename = f"costing_{job_id}.xlsx"
        output_path = os.path.join("temp_downloads", filename)
        os.makedirs("temp_downloads", exist_ok=True)
        wb.save(output_path)
        
        print(f"[SharePoint] Generated costing sheet: {output_path}")
        return filename
    except Exception as e:
        print(f"Excel Generation Error: {e}")
        return ""


# --- Email Tools ---

def send_email(to: str, subject: str, body: str):
    """Sends an email (Mock)."""
    print(f"--- [Email Sent] ---\nTo: {to}\nSubject: {subject}\nBody:\n{body}\n----------------------")

def read_email_quotation(job_id: str) -> Optional[float]:
    """
    Simulates reading an email for a specific Job ID.
    In a real scenario, this would check an inbox for unread emails with the Job ID in subject.
    For this agent, we'll simulate a response after a 'wait'.
    """
    print(f"[Email] Checking for quotation for {job_id}...")
    # Simulate finding an email 50% of the time immediately, or we might need a human-in-the-loop trigger
    # For the purpose of the demo, we'll return a price if the job exists
    return round(random.uniform(1000, 5000), 2)

# --- Search Tool ---

def search_similar_items(query: str) -> List[Dict[str, Any]]:
    """Searches for similar items using hybrid search."""
    return hybrid_search(query, top_k=config.TOP_K_ITEMS)

# --- Vendor Tools ---

def get_vendor_emails(category: str) -> List[str]:
    """Retrieves vendor emails for a given category."""
    try:
        with open("vendor_emails.json", "r") as f:
            data = json.load(f)
        return data.get(category.lower(), [])
    except FileNotFoundError:
        return []

def save_vendor_email(category: str, email: str):
    """Saves a new vendor email for a category."""
    try:
        with open("vendor_emails.json", "r") as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {}
    
    cat_key = category.lower()
    if cat_key not in data:
        data[cat_key] = []
    
    if email not in data[cat_key]:
        data[cat_key].append(email)
        with open("vendor_emails.json", "w") as f:
            json.dump(data, f, indent=2)
        print(f"[Vendor] Saved {email} to {category}")

# --- Monitoring Tools ---

def check_email_replies(job_id: str) -> List[Dict[str, Any]]:
    """Simulates checking for email replies."""
    print(f"[Monitor] Checking replies for {job_id}...")
    # Simulate a delay and random reply
    time.sleep(2) 
    if random.random() > 0.3:
        price = round(random.uniform(100, 5000), 2)
        print(f"[Monitor] Received quotation: ${price}")
        return [{"vendor": "supplier@example.com", "price": price}]
    return []

def upload_to_sharepoint(file_path: str) -> bool:
    """Mock upload to SharePoint."""
    if os.path.exists(file_path):
        print(f"[SharePoint] Uploading {file_path}...")
        time.sleep(1)
        print("[SharePoint] Upload Complete.")
        return True
    return False
