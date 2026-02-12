import uuid
import random
import time
import os
import json
import smtplib
import logging
from email.message import EmailMessage
from datetime import datetime
from typing import List, Dict, Any, Optional
from core import config
from utils import templates
from services.search import hybrid_search, hybrid_product_search
from core.database import (
    SessionLocal, CostingRequest, Product, EstimationLines,
    CostingLineItem, PendingQuoteRequest
)
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from langchain.tools import tool
import requests

logger = logging.getLogger(__name__)

# Optional Langfuse telemetry
from utils.langfuse_tracing import trace_tool, trace_operation
from utils.lifecycle_tracing import (
    log_job_created, log_quote_request_sent, log_quote_received,
    log_job_ready, log_job_approved, log_job_cancelled, log_job_duplicated
)

# --- SMTP Email Services ---
GMAIL_SMTP_SERVER = "smtp.gmail.com"
GMAIL_SMTP_PORT = 587
MS_SMTP_SERVER = "smtp.office365.com"
MS_SMTP_PORT = 587

@trace_tool
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

    try:
        print(f"[SMTP] Connecting to {service} server ({server_addr})...")
        server = smtplib.SMTP(server_addr, server_port)
        server.starttls()
        server.login(sender_email, password)
        server.send_message(msg)
        server.quit()
        print(f"[SMTP] Email successfully sent to {to} via {service}")
        return True
    except Exception as e:
        print(f"[SMTP] Error sending via {service}: {e}")
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

@trace_tool
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


@trace_tool
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


@trace_tool
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

@trace_tool
def search_similar_quotations(job_description: str, boat_model: str, top_k: int = None) -> List[Dict[str, Any]]:
    """Searches for similar quotations in the DB"""
    if top_k is None:
        top_k = config.TOP_K_ITEMS
    try:
        result = hybrid_search(job_description, boat_model.upper(), top_k=top_k)
        return result
    except Exception as e:
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

@trace_tool
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


@trace_tool
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
                "vendor_email": config.VENDOR_DEFAULT_EMAIL
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


@trace_tool
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

        # Log lifecycle event
        log_job_created(
            job_id=job_id,
            user_id=user_id,
            quotation_id=quotation_id,
            description=item_details
        )

        return job_id
    except Exception as e:
        print(f"DB Error: {e}")
        return ""
    finally:
        session.close()


@trace_tool
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
    Returns the filename (not full path) of the generated sheet.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Costing Sheet"

    # Default profit margin from config (used when item has no custom margin)
    default_margin = config.PROFIT_MARGIN

    # Header styling
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    profit_fill = PatternFill(start_color="70AD47", end_color="70AD47", fill_type="solid")  # Green for profit columns
    margin_fill = PatternFill(start_color="ED7D31", end_color="ED7D31", fill_type="solid")  # Orange for margin column
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
    ws['A5'] = "Default Margin:"
    ws['B5'] = f"{(default_margin - 1) * 100:.0f}%" if default_margin > 1 else f"{default_margin * 100:.0f}%"

    # Column headers (13 columns — Margin % inserted between Total Cost and Unit Sell)
    headers = [
        "Item Name", "Item Code",
        "Est. Qty", "Est. Price",
        "Qty", "Products Price",
        "Unit Cost", "Total Cost",
        "Margin %",
        "Unit Sell", "Total Sell",
        "Price Source", "Status"
    ]
    for col, header in enumerate(headers, start=1):
        cell = ws.cell(row=7, column=col, value=header)
        cell.font = header_font
        if col == 9:  # Margin % column
            cell.fill = margin_fill
        elif col in [10, 11]:  # Unit Sell and Total Sell columns
            cell.fill = profit_fill
        else:
            cell.fill = header_fill
        cell.border = thin_border
        cell.alignment = Alignment(horizontal='center')

    # Sort items: non-labour first, labour last
    sorted_items = sorted(items, key=lambda x: ((x.get("item_type") or "").lower() == "hour", x.get("item_name", "")))

    # Add items
    total_cost = 0
    total_selling = 0
    pending_items = []
    row = 8

    for item in sorted_items:
        # Column 1-2: Item Name and Code
        ws.cell(row=row, column=1, value=item.get("item_name", "")).border = thin_border
        ws.cell(row=row, column=2, value=item.get("item_code", "")).border = thin_border

        # Column 3-4: Estimation data (Previous Qty and Price)
        est_qty = item.get("estimation_quantity")
        est_price = item.get("estimation_last_purchase_price") or item.get("estimation_average_price")
        ws.cell(row=row, column=3, value=est_qty if est_qty is not None else "N/A").border = thin_border
        ws.cell(row=row, column=4, value=round(est_price, 2) if est_price is not None else "N/A").border = thin_border

        # Column 5-6: Current Qty and Products Table Price
        quantity = item.get("quantity", 1)
        products_price = item.get("products_table_price")
        ws.cell(row=row, column=5, value=quantity).border = thin_border
        ws.cell(row=row, column=6, value=round(products_price, 2) if products_price is not None else "N/A").border = thin_border

        price = item.get("unit_price")
        status = item.get("price_status", "resolved")
        price_source = item.get("price_source", "unknown")
        item_margin = item.get("margin") or default_margin

        # Column 9: Margin % (always shown)
        margin_pct = (item_margin - 1) * 100 if item_margin > 1 else item_margin * 100
        ws.cell(row=row, column=9, value=f"{margin_pct:.0f}%").border = thin_border

        if status == "pending_quote" or price is None:
            # Column 7-8: Pending values
            ws.cell(row=row, column=7, value="PENDING").border = thin_border
            ws.cell(row=row, column=8, value="PENDING").border = thin_border
            # Column 10-11: Pending sell values
            ws.cell(row=row, column=10, value="PENDING").border = thin_border
            ws.cell(row=row, column=11, value="PENDING").border = thin_border
            # Column 12-13: Source and Status
            ws.cell(row=row, column=12, value=price_source.capitalize()).border = thin_border
            ws.cell(row=row, column=13, value="Awaiting Quote").border = thin_border
            pending_items.append(item)
        else:
            # Column 7-8: Cost columns
            ws.cell(row=row, column=7, value=round(price, 2)).border = thin_border
            item_total_cost = price * quantity
            ws.cell(row=row, column=8, value=round(item_total_cost, 2)).border = thin_border

            # Column 10-11: Selling price columns (with per-item margin)
            unit_selling = price * item_margin
            item_total_selling = item_total_cost * item_margin
            ws.cell(row=row, column=10, value=round(unit_selling, 2)).border = thin_border
            ws.cell(row=row, column=11, value=round(item_total_selling, 2)).border = thin_border

            # Column 12-13: Source and Status
            ws.cell(row=row, column=12, value=price_source.capitalize()).border = thin_border
            ws.cell(row=row, column=13, value="Resolved").border = thin_border

            total_cost += item_total_cost
            total_selling += item_total_selling

        row += 1

    # Add total row
    row += 1
    total_font = Font(bold=True)

    ws.cell(row=row, column=7, value="TOTAL:").font = total_font
    if pending_items:
        ws.cell(row=row, column=8, value=f"{round(total_cost, 2)} + PENDING").font = total_font
        ws.cell(row=row, column=11, value=f"{round(total_selling, 2)} + PENDING").font = total_font
    else:
        ws.cell(row=row, column=8, value=round(total_cost, 2)).font = total_font
        ws.cell(row=row, column=11, value=round(total_selling, 2)).font = total_font

    # Add profit summary row
    row += 1
    ws.cell(row=row, column=7, value="PROFIT:").font = total_font
    if not pending_items:
        profit_amount = total_selling - total_cost
        ws.cell(row=row, column=11, value=round(profit_amount, 2)).font = total_font

    # Adjust column widths
    ws.column_dimensions['A'].width = 30  # Item Name
    ws.column_dimensions['B'].width = 15  # Item Code
    ws.column_dimensions['C'].width = 10  # Est. Qty
    ws.column_dimensions['D'].width = 12  # Est. Price
    ws.column_dimensions['E'].width = 8   # Qty
    ws.column_dimensions['F'].width = 14  # Products Price
    ws.column_dimensions['G'].width = 12  # Unit Cost
    ws.column_dimensions['H'].width = 12  # Total Cost
    ws.column_dimensions['I'].width = 10  # Margin %
    ws.column_dimensions['J'].width = 12  # Unit Sell
    ws.column_dimensions['K'].width = 12  # Total Sell
    ws.column_dimensions['L'].width = 14  # Price Source
    ws.column_dimensions['M'].width = 15  # Status

    # Save file
    filename = f"costing_{job_id}.xlsx"
    output_path = os.path.join(config.TEMP_DOWNLOADS_DIR, filename)
    os.makedirs(config.TEMP_DOWNLOADS_DIR, exist_ok=True)

    try:
        wb.save(output_path)
        print(f"[CostingSheet] Generated: {output_path} (Default Margin: {default_margin}x)")
        print(f"[CostingSheet] File exists: {os.path.exists(output_path)}")
        print(f"[CostingSheet] File size: {os.path.getsize(output_path) if os.path.exists(output_path) else 0} bytes")
    except Exception as e:
        print(f"[CostingSheet] Error saving file: {e}")
        raise

    return filename  # Return just the filename, not the full path


@trace_tool
def regenerate_costing_sheet(job_id: str) -> Optional[str]:
    """
    Regenerates the costing sheet from the latest DB state for the given job.
    Useful after receiving new quotes so downloads reflect updated prices.
    Returns the filename (not full path) of the regenerated sheet.
    """
    session = SessionLocal()
    try:
        costing_req = session.query(CostingRequest).filter(
            CostingRequest.job_id == job_id
        ).first()

        if not costing_req:
            logger.warning(f"[RegenerateSheet] No costing request found for {job_id}")
            return None

        line_items = session.query(CostingLineItem).filter(
            CostingLineItem.costing_request_id == costing_req.id
        ).all()

        print(f"[RegenerateSheet] Job: {job_id}")
        print(f"[RegenerateSheet] Found {len(line_items)} line items")
        print(f"[RegenerateSheet] Line item IDs: {[li.id for li in line_items]}")

        items = []
        for li in line_items:
            items.append({
                "item_name": li.item_name,
                "item_code": li.item_code,
                "quantity": li.quantity or 1,
                "unit_price": li.unit_price,
                "price_status": li.price_status or "pending",
                "vendor_email": li.vendor_email,
                "item_type": getattr(li, "item_type", None),
                # Estimation tracking fields
                "estimation_quantity": getattr(li, "estimation_quantity", None),
                "estimation_average_price": getattr(li, "estimation_average_price", None),
                "estimation_last_purchase_price": getattr(li, "estimation_last_purchase_price", None),
                "estimation_sales_price": getattr(li, "estimation_sales_price", None),
                # Products table tracking
                "products_table_price": getattr(li, "products_table_price", None),
                # Price source
                "price_source": getattr(li, "price_source", "unknown"),
                # Per-item margin
                "margin": getattr(li, "margin", None)
            })

        filename = create_costing_sheet_with_items(
            job_id=job_id,
            items=items,
            quotation_id=costing_req.quotation_id or "",
            description=costing_req.item_details or ""
        )

        if filename:
            # Verify file was actually saved
            full_path = os.path.join(config.TEMP_DOWNLOADS_DIR, filename)
            if os.path.exists(full_path):
                logger.info(f"[RegenerateSheet] Successfully regenerated: {filename}")
                print(f"[RegenerateSheet] File saved at: {full_path}")
            else:
                logger.error(f"[RegenerateSheet] File not found after generation: {full_path}")
                return None
        else:
            logger.error(f"[RegenerateSheet] Generation returned no filename for {job_id}")
            return None

        return filename  # Return just the filename
    except Exception as e:
        logger.error(f"[RegenerateSheet] Error for {job_id}: {e}", exc_info=True)
        return None
    finally:
        session.close()


@trace_tool
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
            # Find the associated line item to link it
            line_item = session.query(CostingLineItem).filter(
                CostingLineItem.costing_request_id == costing_req.id,
                CostingLineItem.item_name == item_name
            ).first()

            pending_req = PendingQuoteRequest(
                costing_request_id=costing_req.id,
                costing_line_item_id=line_item.id if line_item else None,
                job_id=job_id,
                item_name=item_name,
                vendor_email=vendor_email,
                email_subject=subject,
                status="pending"
            )
            session.add(pending_req)

            # Update costing request status
            costing_req.status = "Awaiting Quote"

            # Set quotes_requested_at if this is the first quote request
            if costing_req.quotes_requested_at is None:
                costing_req.quotes_requested_at = datetime.now()

            session.commit()
            print(f"[Email] Sent price request for {item_name} to {vendor_email}")

            # Log lifecycle event
            log_quote_request_sent(
                job_id=job_id,
                item_name=item_name,
                vendor_email=vendor_email,
                item_code=item_code
            )

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
                # Mark as quotation source when received via email
                if hasattr(line_item, 'price_source'):
                    line_item.price_source = "quotation"
                session.commit()
                print(f"[CostingSheet] Updated price for {item_name}: {price}")
                return True

        return False
    except Exception as e:
        print(f"DB Error: {e}")
        return False
    finally:
        session.close()


@trace_tool
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
                item_type=item.get("item_type"),
                # Estimation tracking fields
                estimation_quantity=item.get("estimation_quantity"),
                estimation_average_price=item.get("estimation_average_price"),
                estimation_last_purchase_price=item.get("estimation_last_purchase_price"),
                estimation_sales_price=item.get("estimation_sales_price"),
                # Products table tracking fields
                products_table_price=item.get("products_table_price"),
                # Price source tracking
                price_source=item.get("price_source", "pending"),
                # Per-item margin
                margin=item.get("margin")
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
                    "id": li.id,
                    "item_name": li.item_name,
                    "item_code": li.item_code,
                    "quantity": li.quantity,
                    "unit_price": li.unit_price,
                    "price_status": li.price_status,
                    "price_source": li.price_source,
                    "item_type": li.item_type,
                    "vendor_email": li.vendor_email,
                    "estimation_quantity": li.estimation_quantity,
                    "estimation_average_price": li.estimation_average_price,
                    "estimation_last_purchase_price": li.estimation_last_purchase_price,
                    "estimation_sales_price": li.estimation_sales_price,
                    "products_table_price": li.products_table_price,
                    "quote_received_at": li.quote_received_at.isoformat() if li.quote_received_at else None
                } for li in line_items],
                "quote_requests": [{
                    "item_name": pr.item_name,
                    "status": pr.status,
                    "vendor_email": pr.vendor_email,
                    "email_subject": pr.email_subject,
                    "received_price": pr.received_price,
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


def list_recent_jobs(user_id: int = None, limit: int = 10) -> List[Dict[str, Any]]:
    """
    List recent costing jobs for interactive selection.
    Returns simplified job info suitable for agent display.
    """
    session = SessionLocal()
    try:
        query = session.query(CostingRequest)
        if user_id:
            query = query.filter(CostingRequest.user_id == user_id)

        jobs = query.order_by(CostingRequest.created_at.desc()).limit(limit).all()

        results = []
        for job in jobs:
            # Count line items
            line_items_count = session.query(CostingLineItem).filter(
                CostingLineItem.costing_request_id == job.id
            ).count()

            results.append({
                "job_id": job.job_id,
                "description": job.item_details[:100] + "..." if len(job.item_details) > 100 else job.item_details,
                "status": job.status,
                "line_items_count": line_items_count,
                "created_at": job.created_at.strftime("%Y-%m-%d %H:%M") if job.created_at else "N/A"
            })

        return results
    except Exception as e:
        print(f"DB Error listing jobs: {e}")
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

            # Log lifecycle event
            log_quote_received(
                job_id=job_id,
                item_name=item_name,
                price=price,
                vendor_email=pending_req.vendor_email
            )

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


def mark_quote_received_by_id(
    line_item_id: int,
    price: float,
    job_id: str = None
) -> bool:
    """
    Marks a pending quote request as received and updates the price using line item ID.
    This is more precise than name-based matching.

    Args:
        line_item_id: Database ID of the CostingLineItem
        price: The received unit price
        job_id: Optional job_id for logging and sheet regeneration

    Returns:
        True if successful, False otherwise
    """
    session = SessionLocal()
    try:
        # Update the line item price
        line_item = session.query(CostingLineItem).filter(
            CostingLineItem.id == line_item_id
        ).first()

        if not line_item:
            print(f"[UpdatePrice] Line item {line_item_id} not found")
            return False

        line_item.unit_price = price
        line_item.price_status = "resolved"
        line_item.quote_received_at = datetime.now()
        # Mark as quotation source when received via email
        if hasattr(line_item, 'price_source'):
            line_item.price_source = "quotation"

        # Update any associated pending request
        pending_req = session.query(PendingQuoteRequest).filter(
            PendingQuoteRequest.costing_line_item_id == line_item_id,
            PendingQuoteRequest.status == "pending"
        ).first()

        if pending_req:
            pending_req.status = "received"
            pending_req.received_price = price
            pending_req.received_at = datetime.now()

        session.commit()

        print(f"[UpdatePrice] Updated line item {line_item_id} ({line_item.item_name}): {price}")

        # Regenerate costing sheet if job_id provided
        if job_id:
            regenerate_costing_sheet(job_id)

        return True

    except Exception as e:
        print(f"[UpdatePrice] DB Error: {e}")
        session.rollback()
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

                # Set all_quotes_received_at timestamp
                costing_req.all_quotes_received_at = datetime.now()
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

                # Log lifecycle event
                log_job_ready(
                    job_id=job_id,
                    user_id=costing_req.user_id,
                    total_price=round(total_selling, 2) if total_selling else None
                )

                update_sharepoint_status(
                    job_id=job_id,
                    status="Ready",
                    price=round(total_selling, 2) if total_selling else None
                )

                # Get costing sheet file path for email attachment
                filename = f"costing_{job_id}.xlsx"
                file_path = os.path.join(config.TEMP_DOWNLOADS_DIR, filename)
                attachment_path = file_path if os.path.exists(file_path) else None

                if not attachment_path:
                    print(f"[ReadyNotification] Costing sheet not found at {file_path}, email will be sent without attachment")

                # Notify via email that the job is ready (with attachment)
                send_costing_ready_notification(
                    job_id=job_id,
                    description=costing_req.item_details or "",
                    sharepoint_url=costing_req.sharepoint_url,
                    attachment_path=attachment_path
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


@trace_tool
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


# =============================================================================
# NEW TOOLS FOR PHASE 1 & 2 AGENTS
# =============================================================================

# --- Edit Job Tools ---

@trace_tool
def add_line_item_to_job(
    job_id: str,
    item_name: str,
    item_code: str = "",
    quantity: int = 1,
    unit_price: float = None,
    vendor_email: str = None
) -> Dict[str, Any]:
    """
    Adds a new line item to an existing costing job.
    Returns the created line item details.
    """
    session = SessionLocal()
    try:
        costing_req = session.query(CostingRequest).filter(
            CostingRequest.job_id == job_id
        ).first()

        if not costing_req:
            return {"success": False, "error": f"Job {job_id} not found"}

        # Determine price status and source
        price_status = "resolved" if unit_price is not None else "pending_quote"
        price_source = "manual" if unit_price is not None else "pending"

        line_item = CostingLineItem(
            costing_request_id=costing_req.id,
            item_name=item_name,
            item_code=item_code,
            quantity=quantity,
            unit_price=unit_price,
            price_status=price_status,
            vendor_email=vendor_email or config.VENDOR_DEFAULT_EMAIL,
            price_source=price_source,
            margin=config.PROFIT_MARGIN
        )
        session.add(line_item)
        session.commit()
        session.refresh(line_item)  # Ensure we have the latest state with ID

        item_id = line_item.id
        print(f"[AddLineItem] Added {item_name} (ID: {item_id}) to {job_id}")

    except Exception as e:
        print(f"[AddLineItem] Error: {e}")
        session.rollback()
        return {"success": False, "error": str(e)}
    finally:
        session.close()

    # Regenerate costing sheet AFTER closing the session to ensure commit is flushed
    file_path = regenerate_costing_sheet(job_id)

    return {
        "success": True,
        "item_id": item_id,
        "item_name": item_name,
        "quantity": quantity,
        "unit_price": unit_price,
        "price_status": price_status,
        "file_path": file_path,
    }


@trace_tool
def remove_line_item_from_job(job_id: str, item_identifier: str) -> Dict[str, Any]:
    """
    Removes a line item from a costing job.
    item_identifier can be item_id (int as string) or item_name.
    """
    session = SessionLocal()
    try:
        costing_req = session.query(CostingRequest).filter(
            CostingRequest.job_id == job_id
        ).first()

        if not costing_req:
            return {"success": False, "error": f"Job {job_id} not found"}

        # Try to find by ID first
        line_item = None
        if item_identifier.isdigit():
            line_item = session.query(CostingLineItem).filter(
                CostingLineItem.id == int(item_identifier),
                CostingLineItem.costing_request_id == costing_req.id
            ).first()

        # If not found, try by name
        if not line_item:
            line_item = session.query(CostingLineItem).filter(
                CostingLineItem.costing_request_id == costing_req.id,
                CostingLineItem.item_name.ilike(f"%{item_identifier}%")
            ).first()

        if not line_item:
            return {"success": False, "error": f"Item '{item_identifier}' not found in job {job_id}"}

        item_name = line_item.item_name
        line_item_id = line_item.id

        # Delete any pending quote requests for this line item first (foreign key constraint)
        from core.database import PendingQuoteRequest
        pending_quotes = session.query(PendingQuoteRequest).filter(
            PendingQuoteRequest.costing_line_item_id == line_item_id
        ).all()

        for pending_quote in pending_quotes:
            session.delete(pending_quote)

        if pending_quotes:
            print(f"[RemoveLineItem] Deleted {len(pending_quotes)} pending quote request(s) for {item_name}")

        # Now delete the line item
        session.delete(line_item)
        session.commit()

        print(f"[RemoveLineItem] Removed {item_name} from {job_id}")

    except Exception as e:
        print(f"[RemoveLineItem] Error: {e}")
        session.rollback()
        return {"success": False, "error": str(e)}
    finally:
        session.close()

    # Regenerate costing sheet AFTER closing the session to ensure commit is flushed
    file_path = regenerate_costing_sheet(job_id)

    return {
        "success": True,
        "removed_item": item_name,
        "file_path": file_path,
    }


def search_products_for_agent(query: str, limit: int = 10) -> Dict[str, Any]:
    """
    Search for products across Products and EstimationLines tables.
    Uses hybrid search (vector + full-text) for description-based queries,
    and falls back to ILIKE for short code-like queries.
    Used by the edit job agent to find items when adding to a job.
    Returns:
        {"found": True/False, "results": [...], "message": "..."}
    """
    if not query or len(query) < 2:
        return {"found": False, "results": [], "message": "Search query too short (min 2 characters)"}

    # Determine if this is likely a description-based query
    # Use hybrid search for queries that look like descriptions (not just codes)
    is_code_only = query.replace("-", "").replace("_", "").isalnum() and len(query) < 15
    is_description_query = len(query) > 3 and not is_code_only

    session = SessionLocal()
    try:
        results = []
        seen_items = set()

        # For description-based queries, use hybrid search first
        if is_description_query:
            hybrid_results = hybrid_product_search(query, top_k=limit)
            for product in hybrid_results:
                item_key = product["item_number"]
                if item_key not in seen_items:
                    results.append({
                        "item_code": product["item_number"],
                        "item_name": product["description"] or product["item_number"],
                        "unit_cost": product["unit_cost"],
                        "vendor_email": product.get("vendor_email") or config.VENDOR_DEFAULT_EMAIL,
                        "source": "product",
                        "has_name": bool(product["description"]),
                        "score": product.get("score", 0),
                    })
                    seen_items.add(item_key)

        # ILIKE search on Products by item_number (code) OR description
        search_pattern = f"%{query}%"
        products = session.query(Product).filter(
            (Product.item_number.ilike(search_pattern)) |
            (Product.description.ilike(search_pattern))
        ).limit(20).all()

        for product in products:
            item_key = product.item_number
            if item_key not in seen_items:
                results.append({
                    "item_code": product.item_number,
                    "item_name": product.description or product.item_number,
                    "unit_cost": float(product.unit_cost) if product.unit_cost else None,
                    "vendor_email": config.VENDOR_DEFAULT_EMAIL,
                    "source": "product",
                    "has_name": bool(product.description),
                })
                seen_items.add(item_key)

        # ILIKE search on Products by description
        if not is_description_query:
            products_by_desc = session.query(Product).filter(
                Product.description.ilike(search_pattern)
            ).limit(20).all()

            for product in products_by_desc:
                item_key = product.item_number
                if item_key not in seen_items:
                    results.append({
                        "item_code": product.item_number,
                        "item_name": product.description or product.item_number,
                        "unit_cost": float(product.unit_cost) if product.unit_cost else None,
                        "vendor_email": config.VENDOR_DEFAULT_EMAIL,
                        "source": "product",
                        "has_name": bool(product.description),
                    })
                    seen_items.add(item_key)

        # Search EstimationLines by item_name (description)
        estimation_items = session.query(EstimationLines).filter(
            EstimationLines.item_name.ilike(search_pattern)
        ).limit(20).all()

        for item in estimation_items:
            item_key = item.std_item_code or item.item_name
            if item_key not in seen_items:
                product_price = None
                if item.std_item_code:
                    product = session.query(Product).filter(
                        Product.item_number == item.std_item_code
                    ).first()
                    if product:
                        product_price = float(product.unit_cost) if product.unit_cost else None

                results.append({
                    "item_code": item.std_item_code or "",
                    "item_name": item.item_name,
                    "unit_cost": product_price or (float(item.sales_price) if item.sales_price else None),
                    "vendor_email": config.VENDOR_DEFAULT_EMAIL,
                    "source": "estimation",
                    "has_name": True,
                })
                seen_items.add(item_key)

        # Also search EstimationLines by std_item_code
        if len(results) < 10:
            estimation_by_code = session.query(EstimationLines).filter(
                EstimationLines.std_item_code.ilike(search_pattern)
            ).limit(20).all()

            for item in estimation_by_code:
                item_key = item.std_item_code or item.item_name
                if item_key not in seen_items:
                    product_price = None
                    if item.std_item_code:
                        product = session.query(Product).filter(
                            Product.item_number == item.std_item_code
                        ).first()
                        if product:
                            product_price = float(product.unit_cost) if product.unit_cost else None

                    results.append({
                        "item_code": item.std_item_code or "",
                        "item_name": item.item_name,
                        "unit_cost": product_price or (float(item.sales_price) if item.sales_price else None),
                        "vendor_email": config.VENDOR_DEFAULT_EMAIL,
                        "source": "estimation",
                        "has_name": True,
                    })
                    seen_items.add(item_key)

        # Sort: hybrid results already ranked by score, ILIKE by relevance
        if not is_description_query:
            q_lower = query.lower()
            def sort_key(item):
                name_lower = item["item_name"].lower()
                code_lower = (item["item_code"] or "").lower()
                if name_lower == q_lower or code_lower == q_lower:
                    return 0
                elif name_lower.startswith(q_lower) or code_lower.startswith(q_lower):
                    return 1
                else:
                    return 2
            results.sort(key=sort_key)

        results = results[:limit]

        if not results:
            return {
                "found": False,
                "results": [],
                "message": f"No products found matching '{query}'. Try searching by item code or a different description."
            }

        return {
            "found": True,
            "results": results,
            "message": f"Found {len(results)} product(s) matching '{query}'"
        }
    except Exception as e:
        print(f"[SearchProductsForAgent] Error: {e}")
        return {"found": False, "results": [], "message": f"Search error: {str(e)}"}
    finally:
        session.close()


@trace_tool
def search_products_by_description(query: str, limit: int = 10) -> Dict[str, Any]:
    """
    Search products by description using hybrid search (semantic + full-text).
    Used by pricing advisor and other agents for description-based product lookup.
    Returns:
        {"found": True/False, "results": [...], "message": "..."}
    """
    if not query or len(query) < 2:
        return {"found": False, "results": [], "message": "Search query too short"}

    try:
        hybrid_results = hybrid_product_search(query, top_k=limit)

        if not hybrid_results:
            return {
                "found": False,
                "results": [],
                "message": f"No products found matching '{query}'"
            }

        results = []
        for product in hybrid_results:
            results.append({
                "item_code": product["item_number"],
                "item_name": product["description"] or product["item_number"],
                "unit_cost": product["unit_cost"],
                "vendor_email": product.get("vendor_email") or config.VENDOR_DEFAULT_EMAIL,
                "source": "product",
                "score": product.get("score", 0),
            })

        return {
            "found": True,
            "results": results,
            "message": f"Found {len(results)} product(s) matching '{query}'"
        }
    except Exception as e:
        print(f"[SearchProductsByDescription] Error: {e}")
        return {"found": False, "results": [], "message": f"Search error: {str(e)}"}


def find_matching_line_items(job_id: str, item_identifier: str) -> Dict[str, Any]:
    """
    Find line items matching the identifier. Returns all matches for disambiguation.
    Returns:
        {"match": "exact", "items": [single_item]} if exact ID or single name match
        {"match": "multiple", "items": [item1, item2, ...]} if ambiguous
        {"match": "none", "items": [], "error": "..."} if nothing found
    """
    session = SessionLocal()
    try:
        costing_req = session.query(CostingRequest).filter(
            CostingRequest.job_id == job_id
        ).first()
        if not costing_req:
            return {"match": "none", "items": [], "error": f"Job {job_id} not found"}

        def _item_dict(li):
            return {
                "id": li.id,
                "item_name": li.item_name,
                "item_code": li.item_code,
                "quantity": li.quantity,
                "unit_price": li.unit_price,
                "price_status": li.price_status,
            }

        # Try exact ID match first
        if item_identifier.isdigit():
            line_item = session.query(CostingLineItem).filter(
                CostingLineItem.id == int(item_identifier),
                CostingLineItem.costing_request_id == costing_req.id
            ).first()
            if line_item:
                return {"match": "exact", "items": [_item_dict(line_item)]}

        # Name-based search returning ALL matches
        matches = session.query(CostingLineItem).filter(
            CostingLineItem.costing_request_id == costing_req.id,
            CostingLineItem.item_name.ilike(f"%{item_identifier}%")
        ).all()

        if len(matches) == 0:
            return {"match": "none", "items": [], "error": f"No item matching '{item_identifier}' found in job {job_id}"}
        elif len(matches) == 1:
            return {"match": "exact", "items": [_item_dict(matches[0])]}
        else:
            return {"match": "multiple", "items": [_item_dict(m) for m in matches]}
    except Exception as e:
        print(f"[FindMatchingItems] Error: {e}")
        return {"match": "none", "items": [], "error": str(e)}
    finally:
        session.close()


@trace_tool
def update_line_item(
    job_id: str,
    item_identifier: str,
    new_quantity: int = None,
    new_unit_price: float = None,
    new_item_name: str = None,
    new_item_code: str = None
) -> Dict[str, Any]:
    """
    Updates a line item's details.
    item_identifier can be item_id or item_name.
    """
    session = SessionLocal()
    try:
        costing_req = session.query(CostingRequest).filter(
            CostingRequest.job_id == job_id
        ).first()

        if not costing_req:
            return {"success": False, "error": f"Job {job_id} not found"}

        # Find line item
        line_item = None
        if item_identifier.isdigit():
            line_item = session.query(CostingLineItem).filter(
                CostingLineItem.id == int(item_identifier),
                CostingLineItem.costing_request_id == costing_req.id
            ).first()

        if not line_item:
            line_item = session.query(CostingLineItem).filter(
                CostingLineItem.costing_request_id == costing_req.id,
                CostingLineItem.item_name.ilike(f"%{item_identifier}%")
            ).first()

        if not line_item:
            return {"success": False, "error": f"Item '{item_identifier}' not found"}

        # Update fields
        if new_quantity is not None:
            line_item.quantity = new_quantity
        if new_unit_price is not None:
            line_item.unit_price = new_unit_price
            line_item.price_status = "resolved"
            line_item.quote_received_at = datetime.now()
            # Set price source to manual/quotation when manually entered
            if hasattr(line_item, 'price_source'):
                line_item.price_source = "quotation" if line_item.price_status == "pending_quote" else "manual"
        if new_item_name is not None:
            line_item.item_name = new_item_name
        if new_item_code is not None:
            line_item.item_code = new_item_code

        session.commit()

        # Save values before closing session
        item_name = line_item.item_name
        quantity = line_item.quantity
        unit_price = line_item.unit_price
        price_status = line_item.price_status

        print(f"[UpdateLineItem] Updated {item_name} in {job_id}")

    except Exception as e:
        print(f"[UpdateLineItem] Error: {e}")
        session.rollback()
        return {"success": False, "error": str(e)}
    finally:
        session.close()

    # Regenerate costing sheet AFTER closing the session to ensure commit is flushed
    file_path = regenerate_costing_sheet(job_id)

    return {
        "success": True,
        "item_name": item_name,
        "quantity": quantity,
        "unit_price": unit_price,
        "price_status": price_status,
        "file_path": file_path,
    }


@trace_tool
def update_job_description(job_id: str, new_description: str) -> Dict[str, Any]:
    """Updates the description of a costing job."""
    session = SessionLocal()
    try:
        costing_req = session.query(CostingRequest).filter(
            CostingRequest.job_id == job_id
        ).first()

        if not costing_req:
            return {"success": False, "error": f"Job {job_id} not found"}

        costing_req.item_details = new_description
        session.commit()

        print(f"[UpdateJobDesc] Updated description for {job_id}")

        # Regenerate costing sheet after committing description
        file_path = regenerate_costing_sheet(job_id)

        return {
            "success": True,
            "job_id": job_id,
            "new_description": new_description,
            "file_path": file_path,
        }
    except Exception as e:
        print(f"[UpdateJobDesc] Error: {e}")
        session.rollback()
        return {"success": False, "error": str(e)}
    finally:
        session.close()


# --- Job Lifecycle Tools ---

@trace_tool
def approve_costing_job(job_id: str, user_id: int) -> Dict[str, Any]:
    """
    Approves a costing job by changing its status to 'Approved'.
    """
    session = SessionLocal()
    try:
        costing_req = session.query(CostingRequest).filter(
            CostingRequest.job_id == job_id,
            CostingRequest.user_id == user_id
        ).first()

        if not costing_req:
            return {"success": False, "error": f"Job {job_id} not found"}

        costing_req.status = "Approved"
        costing_req.approved_at = datetime.now()
        session.commit()

        # Log lifecycle event with timestamps for duration scoring
        log_job_approved(
            job_id=job_id,
            user_id=user_id,
            final_price=costing_req.price,
            created_at=costing_req.created_at,
            quotes_requested_at=costing_req.quotes_requested_at,
            all_quotes_received_at=costing_req.all_quotes_received_at
        )

        # Update SharePoint
        update_sharepoint_status(job_id, status="Approved")

        print(f"[ApproveJob] Approved {job_id}")

        return {
            "success": True,
            "job_id": job_id,
            "status": "Approved",
            "message": f"Job {job_id} has been approved"
        }
    except Exception as e:
        print(f"[ApproveJob] Error: {e}")
        session.rollback()
        return {"success": False, "error": str(e)}
    finally:
        session.close()


@trace_tool
def duplicate_costing_job(job_id: str, user_id: int, new_description: str = None) -> Dict[str, Any]:
    """
    Duplicates an existing costing job with all its line items.
    Returns the new job_id.
    """
    session = SessionLocal()
    try:
        # Get original job
        original_job = session.query(CostingRequest).filter(
            CostingRequest.job_id == job_id,
            CostingRequest.user_id == user_id
        ).first()

        if not original_job:
            return {"success": False, "error": f"Job {job_id} not found"}

        # Create new job
        new_job_id = f"COST-{uuid.uuid4().hex[:8].upper()}"
        new_job = CostingRequest(
            user_id=user_id,
            job_id=new_job_id,
            quotation_id=original_job.quotation_id,
            line_num=original_job.line_num,
            item_details=new_description or f"Copy of {original_job.item_details}",
            status="Completed",
            original_job_id=job_id  # Track job lineage
        )
        session.add(new_job)
        session.flush()

        # Copy line items
        original_items = session.query(CostingLineItem).filter(
            CostingLineItem.costing_request_id == original_job.id
        ).all()

        for item in original_items:
            new_item = CostingLineItem(
                costing_request_id=new_job.id,
                item_name=item.item_name,
                item_code=item.item_code,
                quantity=item.quantity,
                unit_price=item.unit_price,
                price_status=item.price_status,
                vendor_email=item.vendor_email,
                item_type=item.item_type
            )
            session.add(new_item)

        session.commit()

        print(f"[DuplicateJob] Created {new_job_id} from {job_id}")

        # Log lifecycle event
        log_job_duplicated(
            original_job_id=job_id,
            new_job_id=new_job_id,
            user_id=user_id
        )

        # Generate costing sheet for new job
        items_for_sheet = []
        for item in original_items:
            items_for_sheet.append({
                "item_name": item.item_name,
                "item_code": item.item_code,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "price_status": item.price_status,
                "is_labour": item.item_type == "Hour" if item.item_type else False
            })

        create_costing_sheet_with_items(
            new_job_id,
            items_for_sheet,
            original_job.quotation_id or "",
            new_job.item_details
        )

        return {
            "success": True,
            "new_job_id": new_job_id,
            "original_job_id": job_id,
            "items_copied": len(original_items)
        }
    except Exception as e:
        print(f"[DuplicateJob] Error: {e}")
        session.rollback()
        return {"success": False, "error": str(e)}
    finally:
        session.close()


@trace_tool
def cancel_costing_job(job_id: str, user_id: int) -> Dict[str, Any]:
    """
    Cancels a costing job by changing its status to 'Cancelled'.
    """
    session = SessionLocal()
    try:
        costing_req = session.query(CostingRequest).filter(
            CostingRequest.job_id == job_id,
            CostingRequest.user_id == user_id
        ).first()

        if not costing_req:
            return {"success": False, "error": f"Job {job_id} not found"}

        costing_req.status = "Cancelled"
        costing_req.cancelled_at = datetime.now()
        session.commit()

        # Log lifecycle event
        log_job_cancelled(
            job_id=job_id,
            user_id=user_id
        )

        # Update SharePoint
        update_sharepoint_status(job_id, status="Cancelled")

        print(f"[CancelJob] Cancelled {job_id}")

        return {
            "success": True,
            "job_id": job_id,
            "status": "Cancelled"
        }
    except Exception as e:
        print(f"[CancelJob] Error: {e}")
        session.rollback()
        return {"success": False, "error": str(e)}
    finally:
        session.close()


@trace_tool
def get_download_url(job_id: str) -> Dict[str, Any]:
    """
    Returns the download URL for a costing sheet.
    """
    filename = f"costing_{job_id}.xlsx"
    file_path = os.path.join(config.TEMP_DOWNLOADS_DIR, filename)

    if os.path.exists(file_path):
        return {
            "success": True,
            "job_id": job_id,
            "download_url": f"/costing-sheets/{filename}",
            "filename": filename
        }
    else:
        return {
            "success": False,
            "error": f"Costing sheet for {job_id} not found. It may need to be regenerated."
        }


# --- Quote Management Tools ---

@trace_tool
def enter_manual_quote(
    job_id: str,
    item_identifier: str,
    quoted_price: float,
    vendor_email: str = None
) -> Dict[str, Any]:
    """
    Manually enters a quote price for an item.
    Sets price_source to 'manual' or 'quotation' depending on context.
    """
    result = update_line_item(
        job_id=job_id,
        item_identifier=item_identifier,
        new_unit_price=quoted_price
    )

    # Mark as quotation source if manually entered
    if result.get("success"):
        result["message"] = "Manual quote entered successfully"

    return result


@trace_tool
def resend_quote_request(job_id: str, item_name: str) -> Dict[str, Any]:
    """
    Resends a quote request email for a specific item.
    """
    session = SessionLocal()
    try:
        costing_req = session.query(CostingRequest).filter(
            CostingRequest.job_id == job_id
        ).first()

        if not costing_req:
            return {"success": False, "error": f"Job {job_id} not found"}

        # Find the line item
        line_item = session.query(CostingLineItem).filter(
            CostingLineItem.costing_request_id == costing_req.id,
            CostingLineItem.item_name.ilike(f"%{item_name}%")
        ).first()

        if not line_item:
            return {"success": False, "error": f"Item '{item_name}' not found in job"}

        # Send email
        email_sent = send_price_request_email(
            job_id=job_id,
            item_name=line_item.item_name,
            item_code=line_item.item_code or "N/A",
            quantity=line_item.quantity or 1,
            vendor_email=line_item.vendor_email or config.VENDOR_DEFAULT_EMAIL
        )

        if email_sent:
            return {
                "success": True,
                "job_id": job_id,
                "item_name": line_item.item_name,
                "vendor_email": line_item.vendor_email,
                "message": f"Quote request resent to {line_item.vendor_email}"
            }
        else:
            return {"success": False, "error": "Failed to send email"}

    except Exception as e:
        print(f"[ResendQuote] Error: {e}")
        return {"success": False, "error": str(e)}
    finally:
        session.close()


@trace_tool
def cancel_quote_request(job_id: str, item_name: str) -> Dict[str, Any]:
    """
    Cancels a pending quote request for an item.
    """
    session = SessionLocal()
    try:
        # Find pending request
        costing_req = session.query(CostingRequest).filter(
            CostingRequest.job_id == job_id
        ).first()

        if not costing_req:
            return {"success": False, "error": f"Job {job_id} not found"}

        pending_req = session.query(PendingQuoteRequest).filter(
            PendingQuoteRequest.job_id == job_id,
            PendingQuoteRequest.item_name.ilike(f"%{item_name}%"),
            PendingQuoteRequest.status == "pending"
        ).first()

        if not pending_req:
            return {"success": False, "error": f"No pending quote request found for '{item_name}'"}

        pending_req.status = "cancelled"
        session.commit()

        print(f"[CancelQuote] Cancelled quote request for {item_name} in {job_id}")

        return {
            "success": True,
            "job_id": job_id,
            "item_name": item_name,
            "message": f"Quote request cancelled for {item_name}"
        }
    except Exception as e:
        print(f"[CancelQuote] Error: {e}")
        session.rollback()
        return {"success": False, "error": str(e)}
    finally:
        session.close()


# --- Pricing Intelligence Tools ---

@trace_tool
def get_item_price_history(item_code: str, item_name: str = None, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Retrieves price history for an item from past costing jobs AND historical estimation lines.
    Searches by item_code first, falls back to item_name ILIKE if no results.
    """
    session = SessionLocal()
    try:
        history = []

        # 1. Get data from CostingLineItem (recent costing jobs)
        line_items = session.query(CostingLineItem).filter(
            CostingLineItem.item_code == item_code,
            CostingLineItem.unit_price.isnot(None)
        ).order_by(CostingLineItem.quote_received_at.desc()).limit(limit).all()

        # Fallback: search by item_name if no results by code
        if not line_items and item_name:
            line_items = session.query(CostingLineItem).filter(
                CostingLineItem.item_name.ilike(f"%{item_name}%"),
                CostingLineItem.unit_price.isnot(None)
            ).order_by(CostingLineItem.quote_received_at.desc()).limit(limit).all()

        for item in line_items:
            costing_req = session.query(CostingRequest).filter(
                CostingRequest.id == item.costing_request_id
            ).first()

            history.append({
                "job_id": costing_req.job_id if costing_req else "Unknown",
                "item_name": item.item_name,
                "item_code": item.item_code,
                "unit_price": item.unit_price,
                "quantity": item.quantity,
                "vendor_email": item.vendor_email,
                "date": item.quote_received_at.isoformat() if item.quote_received_at else None
            })

        # 2. Get historical data from EstimationLines
        estimation_items = session.query(EstimationLines).filter(
            EstimationLines.std_item_code == item_code
        ).limit(limit).all()

        # Fallback: search by item_name if no results by code
        if not estimation_items and item_name:
            estimation_items = session.query(EstimationLines).filter(
                EstimationLines.item_name.ilike(f"%{item_name}%")
            ).limit(limit).all()

        for est_item in estimation_items:
            # Add entries for different price types from estimation
            if est_item.last_purchase_price and est_item.last_purchase_price > 0:
                history.append({
                    "job_id": est_item.quotation_id or "Historical",
                    "item_name": est_item.item_name,
                    "item_code": est_item.std_item_code,
                    "unit_price": float(est_item.last_purchase_price),
                    "quantity": est_item.item_qty,
                    "vendor_email": "Historical Data",
                    "date": "Historical (Last Purchase)"
                })

            if est_item.average_price and est_item.average_price > 0:
                history.append({
                    "job_id": est_item.quotation_id or "Historical",
                    "item_name": est_item.item_name,
                    "item_code": est_item.std_item_code,
                    "unit_price": float(est_item.average_price),
                    "quantity": est_item.item_qty,
                    "vendor_email": "Historical Data",
                    "date": "Historical (Average)"
                })

        # Sort by date (most recent first, then historical)
        history.sort(key=lambda x: (x["date"] is None or "Historical" in str(x["date"]), x.get("date") or ""), reverse=True)

        return history[:limit * 2]  # Return more results since we're combining two sources
    except Exception as e:
        print(f"[PriceHistory] Error: {e}")
        return []
    finally:
        session.close()


@trace_tool
def get_current_product_price(item_code: str) -> Dict[str, Any]:
    """
    Gets the current price from the Products table for an item.
    """
    session = SessionLocal()
    try:
        product = session.query(Product).filter(
            Product.item_number == item_code
        ).first()

        if product:
            return {
                "found": True,
                "item_code": product.item_number,
                "description": product.description,
                "unit_cost": float(product.unit_cost) if product.unit_cost else None,
                "vendor_email": product.vendor_email,
            }
        return {"found": False}
    except Exception as e:
        print(f"[CurrentProductPrice] Error: {e}")
        return {"found": False}
    finally:
        session.close()


@trace_tool
def get_average_item_price(item_code: str, item_name: str = None) -> Dict[str, Any]:
    """
    Calculates average price for an item from historical data (CostingLineItem + EstimationLines).
    Searches by item_code first, falls back to item_name ILIKE if no results.
    """
    session = SessionLocal()
    try:
        from sqlalchemy import func

        # 1. Get prices from CostingLineItem
        result = session.query(
            func.avg(CostingLineItem.unit_price).label('avg_price'),
            func.min(CostingLineItem.unit_price).label('min_price'),
            func.max(CostingLineItem.unit_price).label('max_price'),
            func.count(CostingLineItem.id).label('count')
        ).filter(
            CostingLineItem.item_code == item_code,
            CostingLineItem.unit_price.isnot(None)
        ).first()

        # Fallback: search by item_name if no results by code
        if (not result or result.count == 0) and item_name:
            result = session.query(
                func.avg(CostingLineItem.unit_price).label('avg_price'),
                func.min(CostingLineItem.unit_price).label('min_price'),
                func.max(CostingLineItem.unit_price).label('max_price'),
                func.count(CostingLineItem.id).label('count')
            ).filter(
                CostingLineItem.item_name.ilike(f"%{item_name}%"),
                CostingLineItem.unit_price.isnot(None)
            ).first()

        # 2. Get prices from EstimationLines
        estimation_prices = []
        estimation_items = session.query(EstimationLines).filter(
            EstimationLines.std_item_code == item_code
        ).all()

        # Fallback: search by item_name if no results by code
        if not estimation_items and item_name:
            estimation_items = session.query(EstimationLines).filter(
                EstimationLines.item_name.ilike(f"%{item_name}%")
            ).all()

        for est_item in estimation_items:
            if est_item.last_purchase_price and est_item.last_purchase_price > 0:
                estimation_prices.append(float(est_item.last_purchase_price))
            if est_item.average_price and est_item.average_price > 0:
                estimation_prices.append(float(est_item.average_price))

        # 3. Combine results from both sources
        all_prices = []
        if result and result.count > 0:
            # Get individual prices from CostingLineItem
            costing_prices = session.query(CostingLineItem.unit_price).filter(
                CostingLineItem.item_code == item_code,
                CostingLineItem.unit_price.isnot(None)
            ).all()
            all_prices.extend([float(p[0]) for p in costing_prices if p[0] is not None])

        all_prices.extend(estimation_prices)

        if all_prices:
            return {
                "item_code": item_code,
                "average_price": round(sum(all_prices) / len(all_prices), 2),
                "min_price": round(min(all_prices), 2),
                "max_price": round(max(all_prices), 2),
                "sample_count": len(all_prices)
            }
        else:
            return {
                "item_code": item_code,
                "error": "No historical pricing data found"
            }
    except Exception as e:
        print(f"[AvgPrice] Error: {e}")
        return {"item_code": item_code, "error": str(e)}
    finally:
        session.close()


# --- Vendor Intelligence Tools ---

@trace_tool
def get_vendor_info(vendor_email: str) -> Dict[str, Any]:
    """
    Retrieves vendor information and statistics.
    """
    session = SessionLocal()
    try:
        from sqlalchemy import func

        # Get quote response statistics
        total_requests = session.query(PendingQuoteRequest).filter(
            PendingQuoteRequest.vendor_email == vendor_email
        ).count()

        received_requests = session.query(PendingQuoteRequest).filter(
            PendingQuoteRequest.vendor_email == vendor_email,
            PendingQuoteRequest.status == "received"
        ).count()

        pending_requests = session.query(PendingQuoteRequest).filter(
            PendingQuoteRequest.vendor_email == vendor_email,
            PendingQuoteRequest.status == "pending"
        ).count()

        # Get items supplied by this vendor
        items_count = session.query(CostingLineItem).filter(
            CostingLineItem.vendor_email == vendor_email
        ).count()

        return {
            "vendor_email": vendor_email,
            "total_quote_requests": total_requests,
            "received_quotes": received_requests,
            "pending_quotes": pending_requests,
            "response_rate": round((received_requests / total_requests * 100), 1) if total_requests > 0 else 0,
            "total_items_supplied": items_count
        }
    except Exception as e:
        print(f"[VendorInfo] Error: {e}")
        return {"vendor_email": vendor_email, "error": str(e)}
    finally:
        session.close()


@trace_tool
def get_vendors_for_item_type(item_type: str = None, item_code: str = None) -> List[Dict[str, Any]]:
    """
    Finds vendors who have supplied specific types of items.
    """
    session = SessionLocal()
    try:
        from sqlalchemy import func, distinct

        query = session.query(
            CostingLineItem.vendor_email,
            func.count(CostingLineItem.id).label('item_count')
        ).filter(
            CostingLineItem.vendor_email.isnot(None)
        )

        if item_type:
            query = query.filter(CostingLineItem.item_type == item_type)

        if item_code:
            query = query.filter(CostingLineItem.item_code.like(f"%{item_code}%"))

        vendors = query.group_by(CostingLineItem.vendor_email).order_by(func.count(CostingLineItem.id).desc()).limit(10).all()

        return [{
            "vendor_email": v.vendor_email,
            "items_supplied": v.item_count
        } for v in vendors]
    except Exception as e:
        print(f"[VendorsForItem] Error: {e}")
        return []
    finally:
        session.close()


@trace_tool
def send_costing_sheet_email(
    job_id: str,
    recipient_email: str,
    message: str = ""
) -> Dict[str, Any]:
    """
    Sends the costing sheet to a specified email address.
    """
    session = SessionLocal()
    try:
        costing_req = session.query(CostingRequest).filter(
            CostingRequest.job_id == job_id
        ).first()

        if not costing_req:
            return {"success": False, "error": f"Job {job_id} not found"}

        # Get file path
        filename = f"costing_{job_id}.xlsx"
        file_path = os.path.join(config.TEMP_DOWNLOADS_DIR, filename)

        if not os.path.exists(file_path):
            # Try to regenerate
            file_path = regenerate_costing_sheet(job_id)
            if not file_path or not os.path.exists(file_path):
                return {"success": False, "error": "Costing sheet file not found"}

        # Send email with attachment
        subject = f"Costing Sheet - {job_id}"
        body = f"""Please find attached the costing sheet for job {job_id}.

Description: {costing_req.item_details or 'N/A'}
Status: {costing_req.status}

{message}

Best regards,
Gulf Craft Costing Team
"""

        email_sent = send_email(
            to=recipient_email,
            subject=subject,
            body=body,
            service="microsoft",
            attachment_path=file_path
        )

        if email_sent:
            return {
                "success": True,
                "job_id": job_id,
                "recipient": recipient_email,
                "message": f"Costing sheet sent to {recipient_email}"
            }
        else:
            return {"success": False, "error": "Failed to send email"}

    except Exception as e:
        print(f"[SendCostingEmail] Error: {e}")
        return {"success": False, "error": str(e)}
    finally:
        session.close()
