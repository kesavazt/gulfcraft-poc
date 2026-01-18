import uuid
import random
import time
import os
import json
import smtplib
from email.message import EmailMessage
from datetime import datetime
from typing import List, Dict, Any, Optional
import config
import templates
from search import hybrid_search
from database import (
    SessionLocal, CostingRequest, Product, EstimationLines,
    CostingLineItem, PendingQuoteRequest
)
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from langchain.tools import tool


# --- SMTP Email (Gmail) ---
# Gmail SMTP settings
GMAIL_SMTP_SERVER = "smtp.gmail.com"
GMAIL_SMTP_PORT = 587

def send_email(to: str, subject: str, body: str) -> bool:
    """
    Send an email using Gmail SMTP.

    Args:
        to: Recipient email address
        subject: Email subject
        body: Email body text

    Returns:
        True if email sent successfully, False otherwise
    """
    msg = EmailMessage()
    msg["From"] = config.SMTP_EMAIL
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    # Use Gmail App Password if available, otherwise fall back to SMTP_PASSWORD
    smtp_password = os.getenv("GMAIL_APP_PASSWORD", "").strip('"') or config.SMTP_PASSWORD

    try:
        server = smtplib.SMTP(GMAIL_SMTP_SERVER, GMAIL_SMTP_PORT)
        server.starttls()
        server.login(config.SMTP_EMAIL, smtp_password)
        server.send_message(msg)
        server.quit()
        print(f"[SMTP] Email sent to {to}")
        return True
    except Exception as e:
        print(f"[SMTP] Error: {e}")
        return False


# --- Costing Tools ---

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
            status="Completed"  # Default to Completed
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

def search_similar_quotations(job_description: str, boat_model: str, top_k: int = None) -> List[Dict[str, Any]]:
    """Searches for similar quotations in the DB"""
    if top_k is None:
        top_k = config.TOP_K_ITEMS
    #print(f"Searching for similar quotations (top_k={top_k})")
    #print(job_description)
    #print(boat_model)
    result =hybrid_search(job_description, boat_model.upper(), top_k=top_k)
    #print(result)
    #print(job_description,boat_model)
    return result


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

# --- Quotation Workflow Tools ---

def get_estimation_lines(quotation_id: str, line_num: int) -> List[Dict[str, Any]]:
    """
    Retrieves all estimation lines for a given quotation_id and line_num.
    Returns list of items with their details from the EstimationLines table.
    Includes item_type to differentiate between labour and non-labour items.
    """
    session = SessionLocal()
    try:
        lines = session.query(EstimationLines).filter(
            EstimationLines.quotation_id == quotation_id,
            EstimationLines.line_num == line_num
        ).all()

        result = []
        for line in lines:
            result.append({
                "item_name": line.item_name,
                "item_code": line.std_item_code,
                "item_type": line.item_type,
                "quantity": line.item_qty,
                "uom": line.uom,
                "average_price": line.average_price,
                "last_purchase_price": line.last_purchase_price,
                "sales_price": line.sales_price
            })

        print(f"[EstimationLines] Found {len(result)} items for {quotation_id}, line {line_num}")
        return result
    except Exception as e:
        print(f"DB Error: {e}")
        return []
    finally:
        session.close()


def get_product_price(item_code: str) -> Dict[str, Any]:
    """
    Searches for an item in the Product table by item_code (std_item_code from EstimationLines).
    Returns the product details including unit_cost and vendor_email.
    """
    session = SessionLocal()
    try:
        # Search by item_number using exact match on item_code
        product = session.query(Product).filter(
            Product.item_number == item_code
        ).first()

        if product:
            return {
                "found": True,
                "item_number": product.item_number,
                "unit_cost": product.unit_cost,
                "vendor_email": product.vendor_email or "vinod.ihava@gulfcraftinc.com"
            }
        else:
            # Return default vendor if product not found
            return {
                "found": False,
                "item_number": item_code,
                "unit_cost": None,
                "vendor_email": "vinod.ihava@gulfcraftinc.com"
            }
    except Exception as e:
        print(f"DB Error: {e}")
        return {"found": False, "unit_cost": None, "vendor_email": "vinod.ihava@gulfcraftinc.com"}
    finally:
        session.close()


def create_costing_request(
    user_id: int,
    quotation_id: str,
    line_num: int,
    item_details: str
) -> str:
    """
    Creates a new costing request in the database.
    Returns the generated job_id.
    """
    job_id = f"COST-{uuid.uuid4().hex[:8].upper()}"
    session = SessionLocal()
    try:
        req = CostingRequest(
            user_id=user_id,
            job_id=job_id,
            quotation_id=quotation_id,
            line_num=line_num,
            item_details=item_details,
            status="Completed"  # Default to Completed, will be updated to "Awaiting Quote" if items need quotes
        )
        session.add(req)
        session.commit()
        print(f"[CostingRequest] Created {job_id}")
        return job_id
    except Exception as e:
        print(f"DB Error: {e}")
        return ""
    finally:
        session.close()


def create_costing_sheet_with_items(
    job_id: str,
    items: List[Dict[str, Any]],
    quotation_id: str,
    description: str
) -> str:
    """
    Generates a costing sheet Excel file with the provided items.
    Items with price > threshold have 'pending' as their price.
    Applies profit margin from config to calculate selling prices.
    Returns the file path of the generated sheet.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Costing Sheet"

    # Get profit margin from config
    profit_margin = config.PROFIT_MARGIN

    # Header styling
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    profit_fill = PatternFill(start_color="70AD47", end_color="70AD47", fill_type="solid")  # Green for profit columns
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )

    # Add header info
    ws['A1'] = "Job ID:"
    ws['B1'] = job_id
    ws['A2'] = "Quotation ID:"
    ws['B2'] = quotation_id
    ws['A3'] = "Description:"
    ws['B3'] = description
    ws['A4'] = "Date:"
    ws['B4'] = datetime.now().strftime("%Y-%m-%d %H:%M")
    ws['A5'] = "Profit Margin:"
    ws['B5'] = f"{(profit_margin - 1) * 100:.0f}%" if profit_margin > 1 else f"{profit_margin * 100:.0f}%"

    # Column headers - added Selling Price columns
    headers = ["Item Name", "Item Code", "Qty", "Unit Cost", "Total Cost", "Unit Sell", "Total Sell", "Status"]
    for col, header in enumerate(headers, start=1):
        cell = ws.cell(row=7, column=col, value=header)
        cell.font = header_font
        # Use green fill for selling price columns
        if col in [6, 7]:
            cell.fill = profit_fill
        else:
            cell.fill = header_fill
        cell.border = thin_border
        cell.alignment = Alignment(horizontal='center')

    # Add items
    total_cost = 0
    total_selling = 0
    pending_items = []
    row = 8

    for item in items:
        ws.cell(row=row, column=1, value=item.get("item_name", "")).border = thin_border
        ws.cell(row=row, column=2, value=item.get("item_code", "")).border = thin_border
        ws.cell(row=row, column=3, value=item.get("quantity", 1)).border = thin_border

        price = item.get("unit_price")
        status = item.get("price_status", "resolved")
        quantity = item.get("quantity", 1)

        if status == "pending_quote" or price is None:
            ws.cell(row=row, column=4, value="PENDING").border = thin_border
            ws.cell(row=row, column=5, value="PENDING").border = thin_border
            ws.cell(row=row, column=6, value="PENDING").border = thin_border
            ws.cell(row=row, column=7, value="PENDING").border = thin_border
            ws.cell(row=row, column=8, value="Awaiting Quote").border = thin_border
            pending_items.append(item)
        else:
            # Cost columns
            ws.cell(row=row, column=4, value=round(price, 2)).border = thin_border
            item_total_cost = price * quantity
            ws.cell(row=row, column=5, value=round(item_total_cost, 2)).border = thin_border

            # Selling price columns (with profit margin applied)
            unit_selling = price * profit_margin
            item_total_selling = item_total_cost * profit_margin
            ws.cell(row=row, column=6, value=round(unit_selling, 2)).border = thin_border
            ws.cell(row=row, column=7, value=round(item_total_selling, 2)).border = thin_border

            ws.cell(row=row, column=8, value="Resolved").border = thin_border

            total_cost += item_total_cost
            total_selling += item_total_selling

        row += 1

    # Add total row
    row += 1
    total_font = Font(bold=True)

    ws.cell(row=row, column=4, value="TOTAL:").font = total_font
    if pending_items:
        ws.cell(row=row, column=5, value=f"{round(total_cost, 2)} + PENDING").font = total_font
        ws.cell(row=row, column=7, value=f"{round(total_selling, 2)} + PENDING").font = total_font
    else:
        ws.cell(row=row, column=5, value=round(total_cost, 2)).font = total_font
        ws.cell(row=row, column=7, value=round(total_selling, 2)).font = total_font

    # Add profit summary row
    row += 1
    ws.cell(row=row, column=4, value="PROFIT:").font = total_font
    if not pending_items:
        profit_amount = total_selling - total_cost
        ws.cell(row=row, column=7, value=round(profit_amount, 2)).font = total_font

    # Adjust column widths
    ws.column_dimensions['A'].width = 30
    ws.column_dimensions['B'].width = 15
    ws.column_dimensions['C'].width = 8
    ws.column_dimensions['D'].width = 12
    ws.column_dimensions['E'].width = 12
    ws.column_dimensions['F'].width = 12
    ws.column_dimensions['G'].width = 12
    ws.column_dimensions['H'].width = 15

    # Save file
    filename = f"costing_{job_id}.xlsx"
    output_path = os.path.join("temp_downloads", filename)
    os.makedirs("temp_downloads", exist_ok=True)
    wb.save(output_path)

    print(f"[CostingSheet] Generated: {output_path} (Profit Margin: {profit_margin}x)")
    return output_path


def send_price_request_email(
    job_id: str,
    item_name: str,
    item_code: str,
    quantity: int,
    vendor_email: str
) -> bool:
    """
    Sends an email to the vendor requesting a price quotation for an item.
    Stores the pending request in the database for tracking.
    """
    # Override vendor email for testing - send all emails to test recipient
    test_email = "shehryarshahid49@gmail.com"
    actual_recipient = test_email  # Change to vendor_email for production

    subject = f"Price Quotation Request - {job_id} - {item_name}"
    body = f"""Dear Vendor,

We are requesting a price quotation for the following item:

Job ID: {job_id}
Item Name: {item_name}
Item Code: {item_code}
Quantity: {quantity}

Please reply to this email with your quotation as a PDF attachment.
Include a table with the item name and price in your quotation document.

IMPORTANT: Please keep the Job ID "{job_id}" in your reply subject line
for automated processing.

Best regards,
Gulf Craft Costing Team

---
[DEBUG] Original vendor email: {vendor_email}
"""

    # Send the email using Microsoft Graph API
    email_sent = send_email(actual_recipient, subject, body)

    if not email_sent:
        print(f"[Email] Failed to send email to {actual_recipient}")
        return False

    # Store the pending request
    session = SessionLocal()
    try:
        # Find the costing request
        costing_req = session.query(CostingRequest).filter(
            CostingRequest.job_id == job_id
        ).first()

        if costing_req:
            pending_req = PendingQuoteRequest(
                costing_request_id=costing_req.id,
                job_id=job_id,
                item_name=item_name,
                vendor_email=vendor_email,
                email_subject=subject,
                status="pending"
            )
            session.add(pending_req)

            # Update costing request status
            costing_req.status = "Awaiting Quote"
            session.commit()
            print(f"[Email] Sent price request for {item_name} to {vendor_email}")
            return True
    except Exception as e:
        print(f"DB Error: {e}")
        return False
    finally:
        session.close()

    return True


def update_costing_sheet_with_price(
    job_id: str,
    item_name: str,
    price: float
) -> bool:
    """
    Updates the costing sheet and database with a received price for an item.
    """
    session = SessionLocal()
    try:
        # Find the costing line item
        costing_req = session.query(CostingRequest).filter(
            CostingRequest.job_id == job_id
        ).first()

        if costing_req:
            line_item = session.query(CostingLineItem).filter(
                CostingLineItem.costing_request_id == costing_req.id,
                CostingLineItem.item_name.ilike(f"%{item_name}%")
            ).first()

            if line_item:
                line_item.unit_price = price
                line_item.price_status = "resolved"
                line_item.quote_received_at = datetime.now()
                session.commit()
                print(f"[CostingSheet] Updated price for {item_name}: {price}")
                return True

        return False
    except Exception as e:
        print(f"DB Error: {e}")
        return False
    finally:
        session.close()


def save_costing_line_items(job_id: str, items: List[Dict[str, Any]]) -> bool:
    """
    Saves the costing line items to the database.
    """
    session = SessionLocal()
    try:
        costing_req = session.query(CostingRequest).filter(
            CostingRequest.job_id == job_id
        ).first()

        if not costing_req:
            print(f"[Error] Costing request {job_id} not found")
            return False

        for item in items:
            line_item = CostingLineItem(
                costing_request_id=costing_req.id,
                item_name=item.get("item_name"),
                item_code=item.get("item_code"),
                quantity=item.get("quantity", 1),
                unit_price=item.get("unit_price"),
                price_status=item.get("price_status", "pending"),
                vendor_email=item.get("vendor_email")
            )
            session.add(line_item)

        session.commit()
        print(f"[CostingLineItems] Saved {len(items)} items for {job_id}")
        return True
    except Exception as e:
        print(f"DB Error: {e}")
        return False
    finally:
        session.close()


def get_pending_quote_requests(job_id: str = None) -> List[Dict[str, Any]]:
    """
    Retrieves all pending quote requests, optionally filtered by job_id.
    """
    session = SessionLocal()
    try:
        query = session.query(PendingQuoteRequest).filter(
            PendingQuoteRequest.status == "pending"
        )

        if job_id:
            query = query.filter(PendingQuoteRequest.job_id == job_id)

        requests = query.all()

        return [{
            "id": req.id,
            "job_id": req.job_id,
            "item_name": req.item_name,
            "vendor_email": req.vendor_email,
            "email_subject": req.email_subject,
            "sent_at": req.email_sent_at.isoformat() if req.email_sent_at else None
        } for req in requests]
    except Exception as e:
        print(f"DB Error: {e}")
        return []
    finally:
        session.close()


def mark_quote_received(
    job_id: str,
    item_name: str,
    price: float
) -> bool:
    """
    Marks a pending quote request as received and updates the price.
    """
    session = SessionLocal()
    try:
        pending_req = session.query(PendingQuoteRequest).filter(
            PendingQuoteRequest.job_id == job_id,
            PendingQuoteRequest.item_name.ilike(f"%{item_name}%"),
            PendingQuoteRequest.status == "pending"
        ).first()

        if pending_req:
            pending_req.status = "received"
            pending_req.received_price = price
            pending_req.received_at = datetime.now()
            session.commit()

            # Also update the costing sheet
            update_costing_sheet_with_price(job_id, item_name, price)
            return True

        return False
    except Exception as e:
        print(f"DB Error: {e}")
        return False
    finally:
        session.close()


def check_all_quotes_received(job_id: str) -> Dict[str, Any]:
    """
    Checks if all pending quotes for a job have been received.
    Returns status and list of still-pending items.
    """
    session = SessionLocal()
    try:
        pending = session.query(PendingQuoteRequest).filter(
            PendingQuoteRequest.job_id == job_id,
            PendingQuoteRequest.status == "pending"
        ).all()

        if not pending:
            # All quotes received, update costing request status
            costing_req = session.query(CostingRequest).filter(
                CostingRequest.job_id == job_id
            ).first()
            if costing_req:
                costing_req.status = "Completed"
                session.commit()

            return {
                "all_received": True,
                "pending_items": []
            }

        return {
            "all_received": False,
            "pending_items": [req.item_name for req in pending]
        }
    except Exception as e:
        print(f"DB Error: {e}")
        return {"all_received": False, "pending_items": []}
    finally:
        session.close()


def get_quotation_by_id(quotation_id: str, line_num: int = None) -> Optional[Dict[str, Any]]:
    """
    Retrieves a quotation directly from the QuotationLines table by its ID.
    This is used when the user selects a quotation in a subsequent conversation turn.

    Args:
        quotation_id: The quotation ID (e.g., "AJMFQ-000001")
        line_num: Optional specific line number. If not provided, returns the first matching line.
    """
    from database import QuotationLines

    session = SessionLocal()
    try:
        query = session.query(QuotationLines).filter(
            QuotationLines.quotation_id == quotation_id
        )

        if line_num is not None:
            query = query.filter(QuotationLines.line_num == line_num)

        quotation = query.first()

        if quotation:
            return {
                "quotation_id": quotation.quotation_id,
                "line_num": quotation.line_num,
                "description": quotation.description,
                "boat_model": quotation.afz_boat_model_id,
                "sales_price": quotation.sales_price
            }
        return None
    except Exception as e:
        print(f"DB Error: {e}")
        return None
    finally:
        session.close()
