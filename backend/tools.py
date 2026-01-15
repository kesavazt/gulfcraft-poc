import uuid
import random
import time
import os
import json
import requests
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


# --- Microsoft Graph API Email Client ---
class MSGraphEmailClient:
    """Microsoft Graph API client for sending emails using OAuth2."""

    def __init__(self):
        self.tenant_id = config.MS_GRAPH_TENANT_ID
        self.client_id = config.MS_GRAPH_CLIENT_ID
        self.client_secret = config.MS_GRAPH_CLIENT_SECRET
        self.sender_email = config.MS_GRAPH_SENDER_EMAIL
        self._access_token = None
        self._token_expiry = None

    def _get_access_token(self) -> str:
        """Get OAuth2 access token using client credentials flow."""
        # Return cached token if still valid
        if self._access_token and self._token_expiry:
            if datetime.now().timestamp() < self._token_expiry - 60:
                return self._access_token

        token_url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"

        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials"
        }

        response = requests.post(token_url, data=data)
        response.raise_for_status()

        token_data = response.json()
        self._access_token = token_data["access_token"]
        self._token_expiry = datetime.now().timestamp() + token_data.get("expires_in", 3600)

        return self._access_token

    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        cc: Optional[List[str]] = None,
        attachments: Optional[List[Dict[str, Any]]] = None
    ) -> bool:
        """
        Send an email using Microsoft Graph API.

        Args:
            to: Recipient email address
            subject: Email subject
            body: Email body (HTML supported)
            cc: Optional list of CC recipients
            attachments: Optional list of attachments with 'name' and 'content_bytes' (base64)

        Returns:
            True if email sent successfully, False otherwise
        """
        try:
            access_token = self._get_access_token()

            url = f"https://graph.microsoft.com/v1.0/users/{self.sender_email}/sendMail"

            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }

            # Build recipients
            to_recipients = [{"emailAddress": {"address": to}}]
            cc_recipients = [{"emailAddress": {"address": addr}} for addr in (cc or [])]

            # Build message
            message = {
                "subject": subject,
                "body": {
                    "contentType": "HTML",
                    "content": body.replace("\n", "<br>")
                },
                "toRecipients": to_recipients
            }

            if cc_recipients:
                message["ccRecipients"] = cc_recipients

            # Add attachments if provided
            if attachments:
                message["attachments"] = [
                    {
                        "@odata.type": "#microsoft.graph.fileAttachment",
                        "name": att["name"],
                        "contentBytes": att["content_bytes"]
                    }
                    for att in attachments
                ]

            payload = {
                "message": message,
                "saveToSentItems": "true"
            }

            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()

            print(f"[Email] Successfully sent email to {to}")
            return True

        except requests.exceptions.RequestException as e:
            print(f"[Email] Failed to send email: {e}")
            return False

    def is_configured(self) -> bool:
        """Check if Microsoft Graph API credentials are configured."""
        return bool(self.tenant_id and self.client_id and self.client_secret)


# Singleton email client instance
_email_client = None


def get_email_client() -> MSGraphEmailClient:
    """Get or create the email client singleton."""
    global _email_client
    if _email_client is None:
        _email_client = MSGraphEmailClient()
    return _email_client


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

def send_email(
    to: str,
    subject: str,
    body: str,
    cc: Optional[List[str]] = None,
    attachments: Optional[List[Dict[str, Any]]] = None
) -> bool:
    """
    Sends an email using Microsoft Graph API with OAuth2 authentication.
    Falls back to mock mode if credentials are not configured.

    Args:
        to: Recipient email address
        subject: Email subject
        body: Email body text
        cc: Optional list of CC recipients
        attachments: Optional list of attachments with 'name' and 'content_bytes' (base64)

    Returns:
        True if email sent successfully, False otherwise
    """
    email_client = get_email_client()

    if email_client.is_configured():
        # Use Microsoft Graph API
        return email_client.send_email(to, subject, body, cc, attachments)
    else:
        # Fallback to mock mode
        print(f"[Email - MOCK MODE] Microsoft Graph not configured")
        print(f"--- [Email Sent (Mock)] ---")
        print(f"To: {to}")
        if cc:
            print(f"CC: {', '.join(cc)}")
        print(f"Subject: {subject}")
        print(f"Body:\n{body}")
        if attachments:
            print(f"Attachments: {[att['name'] for att in attachments]}")
        print("----------------------")
        return True

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

def search_similar_quotations(job_description: str, boat_model: str) -> List[Dict[str, Any]]:
    """Searches for similar quotations in the DB"""
    print("Searching for similar quotations")
    print(job_description)
    print(boat_model)
    return hybrid_search(job_description, boat_model, top_k=config.TOP_K_ITEMS)

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


# --- Quotation Workflow Tools ---

def get_estimation_lines(quotation_id: str, line_num: int) -> List[Dict[str, Any]]:
    """
    Retrieves all estimation lines for a given quotation_id and line_num.
    Returns list of items with their details from the EstimationLines table.
    """
    session = SessionLocal()
    try:
        lines = session.query(EstimationLines).filter(
            EstimationLines.quotation_id == quotation_id,
            EstimationLines.line_num == line_num,
            EstimationLines.item_type == "Item"  # Only get items, not hours
        ).all()

        result = []
        for line in lines:
            result.append({
                "item_name": line.item_name,
                "item_code": line.std_item_code,
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


def get_product_price(item_name: str) -> Dict[str, Any]:
    """
    Searches for an item in the Product table by item_name.
    Returns the product details including unit_cost and vendor_email.
    """
    session = SessionLocal()
    try:
        # Search by item_number (which corresponds to item_name in our context)
        product = session.query(Product).filter(
            Product.item_number.ilike(f"%{item_name}%")
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
                "item_number": item_name,
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
            status="Pending"
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
    Returns the file path of the generated sheet.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Costing Sheet"

    # Header styling
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
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

    # Column headers
    headers = ["Item Name", "Item Code", "Quantity", "Unit Price", "Total", "Status"]
    for col, header in enumerate(headers, start=1):
        cell = ws.cell(row=6, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = thin_border
        cell.alignment = Alignment(horizontal='center')

    # Add items
    total_cost = 0
    pending_items = []
    row = 7

    for item in items:
        ws.cell(row=row, column=1, value=item.get("item_name", "")).border = thin_border
        ws.cell(row=row, column=2, value=item.get("item_code", "")).border = thin_border
        ws.cell(row=row, column=3, value=item.get("quantity", 1)).border = thin_border

        price = item.get("unit_price")
        status = item.get("price_status", "resolved")

        if status == "pending_quote" or price is None:
            ws.cell(row=row, column=4, value="PENDING").border = thin_border
            ws.cell(row=row, column=5, value="PENDING").border = thin_border
            ws.cell(row=row, column=6, value="Awaiting Quote").border = thin_border
            pending_items.append(item)
        else:
            ws.cell(row=row, column=4, value=price).border = thin_border
            item_total = price * item.get("quantity", 1)
            ws.cell(row=row, column=5, value=item_total).border = thin_border
            ws.cell(row=row, column=6, value="Resolved").border = thin_border
            total_cost += item_total

        row += 1

    # Add total row
    row += 1
    ws.cell(row=row, column=4, value="TOTAL:").font = Font(bold=True)
    if pending_items:
        ws.cell(row=row, column=5, value=f"{total_cost} + PENDING")
    else:
        ws.cell(row=row, column=5, value=total_cost)

    # Save file
    filename = f"costing_{job_id}.xlsx"
    output_path = os.path.join("temp_downloads", filename)
    os.makedirs("temp_downloads", exist_ok=True)
    wb.save(output_path)

    print(f"[CostingSheet] Generated: {output_path}")
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
"""

    # Send the email (mock)
    send_email(vendor_email, subject, body)

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
            costing_req.status = "Awaiting Quotes"
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
