import uuid
import random
import time
import os
import json
import smtplib
from email.message import EmailMessage
from datetime import datetime
from typing import List, Dict, Any, Optional
from core import config
from utils import templates
from services.search import hybrid_search
from core.database import (
    SessionLocal, CostingRequest, Product, EstimationLines,
    CostingLineItem, PendingQuoteRequest
)
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from langchain.tools import tool
import requests

# Optional Langfuse telemetry
try:
    from langfuse import Langfuse
except ImportError:
    Langfuse = None

LANGFUSE_ENABLED = bool(
    Langfuse
    and config.LANGFUSE_PUBLIC_KEY
    and config.LANGFUSE_SECRET_KEY
)
_langfuse_client = None


def _get_langfuse_client():
    """Lazily initialize Langfuse client if credentials are present."""
    global _langfuse_client
    if not LANGFUSE_ENABLED:
        return None
    if _langfuse_client is None:
        try:
            _langfuse_client = Langfuse(
                public_key=config.LANGFUSE_PUBLIC_KEY,
                secret_key=config.LANGFUSE_SECRET_KEY,
                host=config.LANGFUSE_HOST,
            )
        except Exception as e:
            print(f"[Langfuse] Init error: {e}")
            _langfuse_client = None
    return _langfuse_client


def _trace_tool(name: str, input_payload: Any, output_payload: Any = None, error: Exception = None):
    """Send a lightweight Langfuse trace for tool usage."""
    client = _get_langfuse_client()
    if not client:
        return

    metadata = {"source": "utils.tools"}
    if error:
        metadata["error"] = str(error)

    try:
        method = getattr(client, "trace", None) or getattr(client, "event", None)
        if not callable(method):
            return
        method(
            name=name,
            input=input_payload,
            output=output_payload,
            metadata=metadata,
        )
    except Exception as e:  # Telemetry must never break runtime
        if isinstance(e, AttributeError):
            return
        print(f"[Langfuse] Trace error ({name}): {e}")

# --- SMTP Email Services ---
GMAIL_SMTP_SERVER = "smtp.gmail.com"
GMAIL_SMTP_PORT = 587
MS_SMTP_SERVER = "smtp.office365.com"
MS_SMTP_PORT = 587

def send_email(to: str, subject: str, body: str, service: str = "microsoft", attachment_path: str = None) -> bool:
    """
    Send an email using configured SMTP services, optionally with an attachment.

    Args:
        to: Recipient email address
        subject: Email subject
        body: Email body text
        service: "microsoft" or "gmail"
        attachment_path: Optional path to a file to attach

    Returns:
        True if email sent successfully, False otherwise
    """
    msg = EmailMessage()
    
    # Configure server and credentials based on service
    if service.lower() == "microsoft":
        server_addr = MS_SMTP_SERVER
        server_port = MS_SMTP_PORT
        sender_email = config.MS_GRAPH_SENDER_EMAIL or config.SMTP_EMAIL
        password = config.SMTP_PASSWORD
    else:  # Default to gmail
        server_addr = GMAIL_SMTP_SERVER
        server_port = GMAIL_SMTP_PORT
        sender_email = config.SMTP_EMAIL
        # Use Gmail App Password if available
        password = os.getenv("GMAIL_APP_PASSWORD", "").strip('"') or config.SMTP_PASSWORD

    msg["From"] = sender_email
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    if attachment_path and os.path.exists(attachment_path):
        import mimetypes
        ctype, encoding = mimetypes.guess_type(attachment_path)
        if ctype is None or encoding is not None:
            ctype = 'application/octet-stream'
        maintype, subtype = ctype.split('/', 1)
        
        with open(attachment_path, 'rb') as fp:
            msg.add_attachment(
                fp.read(),
                maintype=maintype,
                subtype=subtype,
                filename=os.path.basename(attachment_path)
            )
        print(f"[SMTP] Attached file: {attachment_path}")

    trace_input = {
        "to": to,
        "subject": subject,
        "service": service
    }

    try:
        print(f"[SMTP] Connecting to {service} server ({server_addr})...")
        server = smtplib.SMTP(server_addr, server_port)
        server.starttls()
        server.login(sender_email, password)
        server.send_message(msg)
        server.quit()
        print(f"[SMTP] Email successfully sent to {to} via {service}")
        _trace_tool(
            name="send_email",
            input_payload=trace_input,
            output_payload={"status": "sent"}
        )
        return True
    except Exception as e:
        print(f"[SMTP] Error sending via {service}: {e}")
        _trace_tool(
            name="send_email",
            input_payload=trace_input,
            error=e
        )
        return False


# --- Costing Tools ---

def get_graph_access_token() -> Optional[str]:
    """Retrieves Microsoft Graph API access token."""
    tenant_id = config.MS_GRAPH_TENANT_ID
    client_id = config.MS_GRAPH_CLIENT_ID
    client_secret = config.MS_GRAPH_CLIENT_SECRET
    
    if not all([tenant_id, client_id, client_secret]):
        print("[GraphAPI] Missing credentials")
        return None

    url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default"
    }
    
    try:
        response = requests.post(url, data=data)
        response.raise_for_status()
        return response.json().get("access_token")
    except Exception as e:
        print(f"[GraphAPI] Auth Error: {e}")
        return None

def create_sharepoint_list_item(
    job_id: str, 
    title: str, 
    price: float, 
    status: str
) -> bool:
    """
    Creates a new item in the configured SharePoint List using MS Graph API.
    
    Columns:
    - Title: Item description/Title
    - Job_x0020_ID: The Job ID
    - Price: Total Price
    - Status: Status (Ready/Awaiting Quote)
    """
    site_id = config.SHAREPOINT_SITE_ID
    list_name = config.SHAREPOINT_LIST_NAME
    
    if not site_id:
        print("[SharePoint] Missing Site ID configuration")
        return False
        
    token = get_graph_access_token()
    if not token:
        return False
        
    url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists/{list_name}/items"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "fields": {
            "Title": str(title),
            "JobID": str(job_id),
            "Price": str(price),
            "Status": str(status)
        }
    }
    
    try:
        print(f"[SharePoint] Creating list item for {job_id}...")
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        print(f"[SharePoint] Successfully created list item: {response.json().get('id')}")
        return True
    except Exception as e:
        print(f"[SharePoint] API Error: {e}")
        if hasattr(e, 'response') and e.response is not None:
             print(f"Response: {e.response.text}")
        return False


def update_sharepoint_status(job_id: str, status: Optional[str] = None, price: Optional[float] = None) -> bool:
    """
    Updates an existing SharePoint list item (matched by JobID) with new status and/or price.
    """
    site_id = config.SHAREPOINT_SITE_ID
    list_name = config.SHAREPOINT_LIST_NAME

    if not site_id:
        print("[SharePoint] Missing Site ID configuration")
        return False

    token = get_graph_access_token()
    if not token:
        return False

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Prefer": "HonorNonIndexedQueriesWarningMayFailRandomly"
    }

    try:
        # Find the item by JobID
        list_items_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists/{list_name}/items"
        resp = requests.get(
            list_items_url,
            headers=headers,
            params={"$filter": f"fields/JobID eq '{job_id}'"}
        )
        resp.raise_for_status()
        items = resp.json().get("value", [])
        if not items:
            print(f"[SharePoint] No list item found for JobID {job_id}")
            return False

        item_id = items[0]["id"]
        fields_payload = {}
        if status is not None:
            fields_payload["Status"] = str(status)
        if price is not None:
            fields_payload["Price"] = str(price)

        if not fields_payload:
            return True

        update_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists/{list_name}/items/{item_id}/fields"
        update_resp = requests.patch(update_url, headers=headers, json=fields_payload)
        update_resp.raise_for_status()
        print(f"[SharePoint] Updated JobID {job_id} with fields: {fields_payload}")
        return True
    except Exception as e:
        print(f"[SharePoint] Update error for {job_id}: {e}")
        if hasattr(e, 'response') and e.response is not None:
             print(f"Response: {e.response.text}")
        return False


def send_costing_ready_notification(job_id: str, description: str = "", sharepoint_url: Optional[str] = None, attachment_path: str = None):
    """Send a notification email when a costing job becomes Ready, optionally with attachment."""
    to_email = config.NOTIFICATION_EMAIL
    if not to_email:
        print("[Notify] No NOTIFICATION_EMAIL configured; skipping ready notification.")
        return False

    subject = f"Costing Ready: {job_id}"
    body_lines = [
        f"Job ID: {job_id}",
        f"Status: Ready",
    ]
    if description:
        body_lines.append(f"Description: {description}")
    if sharepoint_url:
        body_lines.append(f"SharePoint: {sharepoint_url}")

    body_lines.append("\nThe costing sheet has been updated with all received quotes.")
    body = "\n".join(body_lines)

    sent = send_email(to_email, subject, body, service="microsoft", attachment_path=attachment_path)
    _trace_tool(
        name="send_costing_ready_notification",
        input_payload={"job_id": job_id, "to": to_email, "has_attachment": bool(attachment_path)},
        output_payload={"sent": sent}
    )
    return sent

# Deprecated/Mock functions removed or kept for reference if needed
# (create_sharepoint_job and update_sharepoint_job logic replaced/superseded by above for the actual list)

def generate_costing_sheet(job_id: str, details: str, price: float) -> str:
    """Generates an Excel costing sheet from template."""
    try:
        wb = load_workbook(config.COSTING_TEMPLATE_PATH)
        ws = wb.active
        
        # Append new row
        ws.append([job_id, details, price, "Completed", time.strftime("%Y-%m-%d")])
        
        # Save to a temp file
        filename = f"costing_{job_id}.xlsx"
        output_path = os.path.join(config.TEMP_DOWNLOADS_DIR, filename)
        os.makedirs(config.TEMP_DOWNLOADS_DIR, exist_ok=True)
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
    trace_input = {
        "description": job_description,
        "boat_model": boat_model,
        "top_k": top_k
    }
    try:
        result = hybrid_search(job_description, boat_model.upper(), top_k=top_k)
        _trace_tool(
            name="search_similar_quotations",
            input_payload=trace_input,
            output_payload={"results_count": len(result)}
        )
        return result
    except Exception as e:
        _trace_tool(
            name="search_similar_quotations",
            input_payload=trace_input,
            error=e
        )
        raise


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
                "vendor_email": product.vendor_email or config.VENDOR_DEFAULT_EMAIL
            }
        else:
            # Return default vendor if product not found
            return {
                "found": False,
                "item_number": item_code,
                "unit_cost": None,
                "vendor_email": config.VENDOR_DEFAULT_EMAIL
            }
    except Exception as e:
        print(f"DB Error: {e}")
        return {"found": False, "unit_cost": None, "vendor_email": config.VENDOR_DEFAULT_EMAIL}
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
        _trace_tool(
            name="create_costing_request",
            input_payload={
                "user_id": user_id,
                "quotation_id": quotation_id,
                "line_num": line_num
            },
            output_payload={"job_id": job_id}
        )
        return job_id
    except Exception as e:
        print(f"DB Error: {e}")
        _trace_tool(
            name="create_costing_request",
            input_payload={
                "user_id": user_id,
                "quotation_id": quotation_id,
                "line_num": line_num
            },
            error=e
        )
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
    output_path = os.path.join(config.TEMP_DOWNLOADS_DIR, filename)
    os.makedirs(config.TEMP_DOWNLOADS_DIR, exist_ok=True)
    wb.save(output_path)

    print(f"[CostingSheet] Generated: {output_path} (Profit Margin: {profit_margin}x)")
    return output_path


def regenerate_costing_sheet(job_id: str) -> Optional[str]:
    """
    Regenerates the costing sheet from the latest DB state for the given job.
    Useful after receiving new quotes so downloads reflect updated prices.
    """
    session = SessionLocal()
    try:
        costing_req = session.query(CostingRequest).filter(
            CostingRequest.job_id == job_id
        ).first()

        if not costing_req:
            print(f"[CostingSheet] No costing request found for {job_id}")
            return None

        line_items = session.query(CostingLineItem).filter(
            CostingLineItem.costing_request_id == costing_req.id
        ).all()

        items = []
        for li in line_items:
            items.append({
                "item_name": li.item_name,
                "item_code": li.item_code,
                "quantity": li.quantity or 1,
                "unit_price": li.unit_price,
                "price_status": li.price_status or "pending",
                "vendor_email": li.vendor_email,
                "item_type": getattr(li, "item_type", None)
            })

        return create_costing_sheet_with_items(
            job_id=job_id,
            items=items,
            quotation_id=costing_req.quotation_id or "",
            description=costing_req.item_details or ""
        )
    except Exception as e:
        print(f"[CostingSheet] Regenerate error for {job_id}: {e}")
        return None
    finally:
        session.close()


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

    # Send the email using configured SMTP service (defaulting to microsoft as per GC requirement)
    email_sent = send_email(vendor_email, subject, body, service="microsoft")

    if not email_sent:
        print(f"[Email] Failed to send email to {vendor_email}")
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
                vendor_email=item.get("vendor_email"),
                item_type=item.get("item_type")
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


def get_costing_job_statuses(user_id: int, job_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Retrieves costing job statuses for a user, optionally filtered by job_id.
    Includes line items with their pricing status and quote tracking.
    """
    session = SessionLocal()
    try:
        query = session.query(CostingRequest).filter(
            CostingRequest.user_id == user_id
        )
        if job_id:
            query = query.filter(CostingRequest.job_id == job_id)

        requests = query.order_by(CostingRequest.created_at.desc()).all()
        results = []
        for req in requests:
            line_items = session.query(CostingLineItem).filter(
                CostingLineItem.costing_request_id == req.id
            ).all()
            pending_reqs = session.query(PendingQuoteRequest).filter(
                PendingQuoteRequest.costing_request_id == req.id
            ).all()
            results.append({
                "job_id": req.job_id,
                "status": req.status,
                "item_details": req.item_details,
                "created_at": req.created_at.isoformat() if req.created_at else None,
                "line_items": [{
                    "item_name": li.item_name,
                    "item_code": li.item_code,
                    "quantity": li.quantity,
                    "unit_price": li.unit_price,
                    "price_status": li.price_status,
                    "quote_received_at": li.quote_received_at.isoformat() if li.quote_received_at else None
                } for li in line_items],
                "quote_requests": [{
                    "item_name": pr.item_name,
                    "status": pr.status,
                    "sent_at": pr.email_sent_at.isoformat() if pr.email_sent_at else None,
                    "received_at": pr.received_at.isoformat() if pr.received_at else None
                } for pr in pending_reqs]
            })
        return results
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

            # Regenerate costing sheet file so downloads reflect new prices
            regenerate_costing_sheet(job_id)
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

                # Recalculate selling price for SharePoint and mark as Ready
                total_selling = 0
                line_items = session.query(CostingLineItem).filter(
                    CostingLineItem.costing_request_id == costing_req.id
                ).all()
                for item in line_items:
                    if item.unit_price is not None:
                        qty = item.quantity or 1
                        total_selling += (item.unit_price * qty * config.PROFIT_MARGIN)

                update_sharepoint_status(
                    job_id=job_id,
                    status="Ready",
                    price=round(total_selling, 2) if total_selling else None
                )
                # Notify via email that the job is ready
                send_costing_ready_notification(
                    job_id=job_id,
                    description=costing_req.item_details or "",
                    sharepoint_url=costing_req.sharepoint_url
                )

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
    from core.database import QuotationLines

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
                "price": quotation.sales_price
            }
        return None
    except Exception as e:
        print(f"DB Error: {e}")
        return None
    finally:
        session.close()
