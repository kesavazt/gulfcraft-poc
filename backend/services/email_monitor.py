"""
Email Monitor Service
Polls inbox via Microsoft Graph API for incoming quotation emails and extracts prices using Mistral OCR.
"""
import os
import sys
import re
import time
import base64
import threading
import requests
from datetime import datetime
from typing import List, Dict, Any, Optional

# Ensure the backend package is importable when running as a script
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core import config
from core.database import (
    SessionLocal, CostingRequest, CostingLineItem,
    PendingQuoteRequest
)
from utils.tools import (
    mark_quote_received, mark_quote_received_by_id, check_all_quotes_received,
    create_costing_sheet_with_items
)

match_ocr_items_to_pending = None
try:
    from services.ocr_matcher import match_ocr_items_to_pending  # type: ignore[import-not-found]
    OCR_MATCHER_AVAILABLE = True
except ImportError:
    OCR_MATCHER_AVAILABLE = False

# Import pdf_extractor for OCR
extract_line_items_from_pdf = None
try:
    from services.pdf_extractor import extract_line_items_from_pdf
    PDF_EXTRACTOR_AVAILABLE = True
except ImportError:
    PDF_EXTRACTOR_AVAILABLE = False
    print("[Warning] pdf_extractor not available")


GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"


class EmailMonitor:
    """
    Monitors inbox via Microsoft Graph API for incoming price quotation responses.
    Uses Mistral OCR to extract prices from PDF attachments.
    """

    def __init__(self, poll_interval: int = 60):
        self.poll_interval = poll_interval
        self.running = False
        self._thread = None
        self.temp_dir = os.path.join(BASE_DIR, "temp_attachments")
        self._access_token: Optional[str] = None

        # Create temp directory for attachments
        os.makedirs(self.temp_dir, exist_ok=True)

        # MS Graph credentials
        self.tenant_id = config.MS_GRAPH_TENANT_ID
        self.client_id = config.MS_GRAPH_CLIENT_ID
        self.client_secret = config.MS_GRAPH_CLIENT_SECRET
        self.mailbox = config.MS_GRAPH_SENDER_EMAIL

        print(f"[EmailMonitor] Configured for Microsoft Graph API")
        print(f"[EmailMonitor] Mailbox: {self.mailbox}")

    def _get_access_token(self) -> Optional[str]:
        """Get OAuth2 access token for Microsoft Graph API."""
        if not all([self.tenant_id, self.client_id, self.client_secret]):
            print("[EmailMonitor] Missing MS Graph credentials in .env")
            return None

        url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "https://graph.microsoft.com/.default",
        }

        try:
            resp = requests.post(url, data=data, timeout=30)
            resp.raise_for_status()
            self._access_token = resp.json().get("access_token")
            if not self._access_token:
                print(f"[EmailMonitor] No access_token in response: {resp.json()}")
                return None
            return self._access_token
        except Exception as e:
            print(f"[EmailMonitor] Auth error: {e}")
            return None

    def _graph_headers(self) -> dict:
        """Return authorization headers for Graph API calls."""
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

    def start(self):
        """Start the email monitoring service in a background thread."""
        if self.running:
            print("[EmailMonitor] Already running")
            return

        self.running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        print(f"[EmailMonitor] Started. Polling every {self.poll_interval} seconds.")

    def stop(self):
        """Stop the email monitoring service."""
        self.running = False
        if self._thread:
            self._thread.join(timeout=5)
        print("[EmailMonitor] Stopped")

    def _poll_loop(self):
        """Main polling loop."""
        while self.running:
            try:
                self._check_for_emails()
            except Exception as e:
                print(f"[EmailMonitor] Error: {e}")
                self._access_token = None  # Force re-auth on next poll

            time.sleep(self.poll_interval)

    def _check_for_emails(self):
        """Check inbox for new quotation emails via Microsoft Graph API."""
        print("[EmailMonitor] Checking for new emails...")

        # Get/refresh access token
        if not self._access_token:
            if not self._get_access_token():
                return

        # Get all pending quote requests
        pending_requests = self._get_pending_requests()
        print(f"[EmailMonitor] {len(pending_requests)} pending quote requests in DB")

        # Fetch unread emails with quotation-related subjects
        # Note: Graph API has limitations on complex contains() filters
        # Simplify to just fetch unread emails and filter in Python
        odata_filter = "isRead eq false"

        url = (
            f"{GRAPH_API_BASE}/users/{self.mailbox}/messages"
            f"?$filter={odata_filter}"
            f"&$select=id,subject,from,body,hasAttachments,receivedDateTime"
            f"&$top=50"
            f"&$orderby=receivedDateTime desc"
        )

        try:
            resp = requests.get(url, headers=self._graph_headers(), timeout=30)

            if resp.status_code == 401:
                print("[EmailMonitor] Token expired, refreshing...")
                self._access_token = None
                if not self._get_access_token():
                    return
                resp = requests.get(url, headers=self._graph_headers(), timeout=30)

            resp.raise_for_status()
            all_messages = resp.json().get("value", [])

            # Filter messages by subject keywords (Python-side filtering)
            keywords = ['Price Quotation Request', 'JOB-', 'COST-']

            print(f"[EmailMonitor] Fetched {len(all_messages)} total unread emails")
            for i, msg in enumerate(all_messages):
                subj = msg.get('subject', '(no subject)')
                print(f"  [{i+1}] Subject: {subj}")

            messages = [
                msg for msg in all_messages
                if any(keyword in msg.get('subject', '') for keyword in keywords)
            ]

            print(f"[EmailMonitor] Filtered to {len(messages)} quotation-related emails (matching keywords: {keywords})")

            for msg in messages:
                try:
                    self._process_email(msg, pending_requests)
                except Exception as e:
                    print(f"[EmailMonitor] Error processing email {msg.get('id', '?')}: {e}")

        except Exception as e:
            print(f"[EmailMonitor] Error checking emails: {e}")
            self._access_token = None

    def _get_pending_requests(self) -> List[Dict[str, Any]]:
        """Get all pending quote requests from database."""
        session = SessionLocal()
        try:
            requests_list = session.query(PendingQuoteRequest).filter(
                PendingQuoteRequest.status == "pending"
            ).all()

            result = [{
                "id": req.id,
                "job_id": req.job_id,
                "item_name": req.item_name,
                "vendor_email": req.vendor_email,
                "costing_request_id": req.costing_request_id
            } for req in requests_list]

            if result:
                print(f"[EmailMonitor] Retrieved {len(result)} pending quote requests from DB:")
                for req in result:
                    print(f"  - ID: {req['id']}, Job: {req['job_id']}, Item: {req['item_name']}, Vendor: {req['vendor_email']}")
            else:
                print(f"[EmailMonitor] No pending quote requests found in DB")

            return result
        except Exception as e:
            print(f"[EmailMonitor] DB Error: {e}")
            import traceback
            traceback.print_exc()
            return []
        finally:
            session.close()

    def _process_email(self, msg: Dict[str, Any], pending_requests: List[Dict[str, Any]]):
        """Process a single email from Graph API response."""
        msg_id = msg["id"]
        subject = msg.get("subject", "")
        from_addr = msg.get("from", {}).get("emailAddress", {}).get("address", "unknown")

        print(f"\n[EmailMonitor] ========== Processing Email ==========")
        print(f"[EmailMonitor] Message ID: {msg_id}")
        print(f"[EmailMonitor] From: {from_addr}")
        print(f"[EmailMonitor] Subject: {subject}")

        # Extract job_id and item_name from subject
        job_id, item_name = self._parse_subject(subject)

        if not job_id:
            print(f"[EmailMonitor] ✗ SKIPPING: Could not extract job_id from subject")
            print(f"[EmailMonitor] ✗ Marking as read without processing")
            self._mark_as_read(msg_id)
            print(f"[EmailMonitor] ========================================\n")
            return

        print(f"[EmailMonitor] Extracted job_id: {job_id}, item_name: {item_name}")
        print(f"[EmailMonitor] Checking against {len(pending_requests)} pending requests")

        # Find matching pending request - prioritize job_id match
        matching_request = None
        for req in pending_requests:
            print(f"[EmailMonitor] Comparing with: job_id={req['job_id']}, item={req['item_name']}, vendor={req.get('vendor_email', 'N/A')}")

            if req["job_id"] == job_id:
                print(f"[EmailMonitor] ✓ Job ID matched: {job_id}")
                # If item_name also matches, prioritize this match
                if item_name and req["item_name"].lower() in item_name.lower():
                    matching_request = req
                    print(f"[EmailMonitor] ✓ Item name also matched: {item_name}")
                    break
                # Otherwise, keep this as a candidate match
                elif not matching_request:
                    matching_request = req
                    print(f"[EmailMonitor] ✓ Using as candidate match (no item name in subject)")

        if matching_request:
            print(f"[EmailMonitor] ✓ MATCHED: job_id={matching_request['job_id']}, item={matching_request['item_name']}, id={matching_request['id']}")
        else:
            print(f"[EmailMonitor] ✗ No pending request found for job_id: {job_id} from sender: {from_addr}")

        default_item_name = item_name or "Unknown Item"
        if matching_request:
            default_item_name = matching_request["item_name"]

        # Download attachments if present
        if msg.get("hasAttachments"):
            pdf_paths = self._download_attachments(msg_id)

            if pdf_paths:
                print(f"[EmailMonitor] Found {len(pdf_paths)} PDF attachment(s)")

                for pdf_path in pdf_paths:
                    extracted_data = self.extract_prices_from_pdf(pdf_path)

                    if extracted_data:
                        print(f"[EmailMonitor] Extracted {len(extracted_data)} items from PDF")
                        self._update_prices_from_extraction(
                            job_id=job_id,
                            item_name=default_item_name,
                            extracted_data=extracted_data
                        )
                    else:
                        print(f"[EmailMonitor] No data extracted from PDF")

                    try:
                        os.remove(pdf_path)
                    except:
                        pass

                self._mark_as_read(msg_id)
                return

        # No PDF attachments, try body text
        body_content = msg.get("body", {}).get("content", "")
        body_type = msg.get("body", {}).get("contentType", "text")

        if body_type == "html":
            body_text = re.sub(r'<[^>]+>', '', body_content)
        else:
            body_text = body_content

        print(f"[EmailMonitor] No PDF attachment. Email body preview: {body_text[:200] if body_text else 'Empty'}")

        price = self._extract_price_from_text(body_text)
        if price:
            print(f"[EmailMonitor] Extracted price from body: {price}")
            self._update_prices_from_extraction(
                job_id=job_id,
                item_name=default_item_name,
                extracted_data=[{"item_name": default_item_name, "unit_price": price}]
            )

        self._mark_as_read(msg_id)
        print(f"[EmailMonitor] Marked email as read")

    def _download_attachments(self, message_id: str) -> List[str]:
        """Download PDF attachments from an email via Graph API."""
        pdf_paths = []

        url = f"{GRAPH_API_BASE}/users/{self.mailbox}/messages/{message_id}/attachments"

        try:
            resp = requests.get(url, headers=self._graph_headers(), timeout=30)
            resp.raise_for_status()
            attachments = resp.json().get("value", [])

            for att in attachments:
                filename = att.get("name", "attachment")
                content_type = att.get("contentType", "")
                content_bytes_b64 = att.get("contentBytes")

                is_pdf = (
                    filename.lower().endswith(".pdf")
                    or content_type == "application/pdf"
                )

                if is_pdf and content_bytes_b64:
                    file_bytes = base64.b64decode(content_bytes_b64)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    safe_filename = f"{timestamp}_{filename}"
                    filepath = os.path.join(self.temp_dir, safe_filename)

                    with open(filepath, "wb") as f:
                        f.write(file_bytes)

                    pdf_paths.append(filepath)
                    print(f"[EmailMonitor] Saved PDF: {filepath} ({len(file_bytes)} bytes)")
                else:
                    print(f"[EmailMonitor] Skipping non-PDF attachment: {filename} ({content_type})")

        except Exception as e:
            print(f"[EmailMonitor] Error downloading attachments: {e}")

        return pdf_paths

    def _mark_as_read(self, message_id: str):
        """Mark an email as read via Graph API."""
        url = f"{GRAPH_API_BASE}/users/{self.mailbox}/messages/{message_id}"
        try:
            resp = requests.patch(
                url,
                headers=self._graph_headers(),
                json={"isRead": True},
                timeout=15
            )
            resp.raise_for_status()
            print(f"[EmailMonitor] ✓ Marked email {message_id[:20]}... as read")
        except Exception as e:
            print(f"[EmailMonitor] ✗ Error marking email as read: {e}")

    def _parse_subject(self, subject: str) -> tuple:
        """Parse job_id and item_name from email subject."""
        job_id = None
        item_name = None

        print(f"[EmailMonitor] Parsing subject: '{subject}'")

        if not subject:
            print(f"[EmailMonitor] Subject is empty")
            return job_id, item_name

        # Remove RE:, FW:, Fwd: prefixes
        clean_subject = subject
        for prefix in ["RE:", "Re:", "re:", "FW:", "Fw:", "fw:", "Fwd:", "FWD:"]:
            clean_subject = clean_subject.replace(prefix, "").strip()

        print(f"[EmailMonitor] After removing prefixes: '{clean_subject}'")

        # Split by " - "
        parts = clean_subject.split(" - ")
        print(f"[EmailMonitor] Split into {len(parts)} parts: {parts}")

        for i, part in enumerate(parts):
            part = part.strip()
            print(f"[EmailMonitor] Checking part {i}: '{part}'")
            if part.startswith("JOB-") or part.startswith("COST-"):
                job_id = part
                print(f"[EmailMonitor] Found job_id: {job_id}")
                if i + 1 < len(parts):
                    item_name = parts[i + 1].strip()
                    print(f"[EmailMonitor] Found item_name: {item_name}")
                break

        if not job_id:
            print(f"[EmailMonitor] ✗ Could not find job_id in subject (no part starts with JOB- or COST-)")

        return job_id, item_name

    def _extract_price_from_text(self, text: str) -> Optional[float]:
        """Try to extract a price from plain text."""
        if not text:
            return None

        patterns = [
            r'\$[\d,]+\.?\d*',
            r'USD\s*[\d,]+\.?\d*',
            r'AED\s*[\d,]+\.?\d*',
            r'[\d,]+\.?\d*\s*(?:USD|AED|SAR)',
            r'(?:price|total|amount|cost)[\s:]*[\d,]+\.?\d*',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                numeric = re.sub(r'[^\d.]', '', matches[0])
                try:
                    return float(numeric)
                except ValueError:
                    continue

        return None

    def _update_prices_from_extraction(self, job_id: str, item_name: str, extracted_data: List[Dict[str, Any]]):
        """Update database with extracted unit costs (no profit margin applied)."""
        matched_items = None
        if OCR_MATCHER_AVAILABLE and match_ocr_items_to_pending:
            try:
                matched_items = match_ocr_items_to_pending(
                    job_id=job_id,
                    extracted_items=extracted_data
                )
            except Exception as e:
                print(f"[EmailMonitor] OCR matcher error: {e}")
                matched_items = None

        if matched_items:
            for match in matched_items:
                ocr_item = match.get("ocr_item") or {}
                cost_price = ocr_item.get("unit_price") or ocr_item.get("price")
                matched_id = match.get("matched_line_item_id")
                confidence = match.get("confidence")
                match_reason = match.get("match_reason", "")

                if matched_id and cost_price:
                    cost_price = float(cost_price)
                    print(f"[EmailMonitor] LLM Match: Line item {matched_id} at confidence {confidence:.2f}")
                    print(f"[EmailMonitor] Reason: {match_reason}")

                    success = mark_quote_received_by_id(
                        line_item_id=matched_id,
                        price=cost_price,
                        job_id=job_id
                    )

                    if success:
                        print(f"[EmailMonitor] Updated price for {ocr_item.get('item_name', item_name)}: {cost_price}")

                        status = check_all_quotes_received(job_id)
                        if status["all_received"]:
                            print(f"[EmailMonitor] All quotes received for {job_id}. Regenerating costing sheet.")
                            self._regenerate_costing_sheet(job_id)
            return

        for item in extracted_data:
            extracted_item_name = item.get("item_name", item_name)
            cost_price = item.get("unit_price") or item.get("price")

            if cost_price:
                cost_price = float(cost_price)
                print(f"[EmailMonitor] Cost: {cost_price} (no margin applied)")

                success = mark_quote_received(
                    job_id=job_id,
                    item_name=extracted_item_name,
                    price=cost_price
                )

                if success:
                    print(f"[EmailMonitor] Updated price for {extracted_item_name}: {cost_price}")

                    status = check_all_quotes_received(job_id)
                    if status["all_received"]:
                        print(f"[EmailMonitor] All quotes received for {job_id}. Regenerating costing sheet.")
                        self._regenerate_costing_sheet(job_id)

    def extract_prices_from_pdf(self, pdf_path: str) -> List[Dict[str, Any]]:
        """Extract item names and prices from a PDF quotation using Mistral OCR."""
        if PDF_EXTRACTOR_AVAILABLE and extract_line_items_from_pdf:
            try:
                items = extract_line_items_from_pdf(pdf_path)
                return items
            except Exception as e:
                print(f"[EmailMonitor] PDF extraction error: {e}")
                return []
        else:
            print("[EmailMonitor] PDF extractor not available.")
            return []

    def _regenerate_costing_sheet(self, job_id: str):
        """Regenerate the costing sheet with updated prices."""
        session = SessionLocal()
        try:
            costing_req = session.query(CostingRequest).filter(
                CostingRequest.job_id == job_id
            ).first()

            if not costing_req:
                return

            line_items = session.query(CostingLineItem).filter(
                CostingLineItem.costing_request_id == costing_req.id
            ).all()

            items = [{
                "item_name": item.item_name,
                "item_code": item.item_code,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "price_status": item.price_status
            } for item in line_items]

            file_path = create_costing_sheet_with_items(
                job_id=job_id,
                items=items,
                quotation_id=costing_req.quotation_id or "",
                description=costing_req.item_details or ""
            )

            if file_path:
                costing_req.status = "Completed"  # type: ignore[assignment]
                session.commit()
                print(f"[EmailMonitor] Regenerated costing sheet: {file_path}")

        except Exception as e:
            print(f"[EmailMonitor] Error regenerating sheet: {e}")
        finally:
            session.close()


# Singleton instance
_monitor_instance = None


def get_email_monitor() -> EmailMonitor:
    """Get or create the email monitor singleton."""
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = EmailMonitor(
            poll_interval=int(os.getenv("EMAIL_POLL_INTERVAL", "60"))
        )
    return _monitor_instance


def start_email_monitor():
    """Start the email monitoring service."""
    monitor = get_email_monitor()
    monitor.start()


def stop_email_monitor():
    """Stop the email monitoring service."""
    monitor = get_email_monitor()
    monitor.stop()


# Manual trigger for testing
def process_mock_email(job_id: str, item_name: str, price: float):
    """Manually process a mock email for testing purposes."""
    print(f"[MockEmail] Processing mock email for {job_id}")

    success = mark_quote_received(
        job_id=job_id,
        item_name=item_name,
        price=price
    )

    if success:
        print(f"[MockEmail] Updated price for {item_name}: {price}")

        status = check_all_quotes_received(job_id)
        if status["all_received"]:
            monitor = get_email_monitor()
            monitor._regenerate_costing_sheet(job_id)

    return success


def test_graph_connection():
    """Test Microsoft Graph API connection, list recent emails, and test attachment download."""
    print("=" * 60)
    print("Microsoft Graph Email Monitor - Connection Test")
    print("=" * 60)
    print(f"Mailbox: {config.MS_GRAPH_SENDER_EMAIL}")
    print(f"Tenant:  {config.MS_GRAPH_TENANT_ID}")
    print(f"Client:  {config.MS_GRAPH_CLIENT_ID}")
    print()

    monitor = EmailMonitor()

    # Step 1: Authenticate
    print("[1/3] Authenticating with Microsoft Graph API...")
    token = monitor._get_access_token()
    if not token:
        print("FAILED: Could not get access token.")
        print("Check MS_GRAPH_TENANT_ID, MS_GRAPH_CLIENT_ID, MS_GRAPH_CLIENT_SECRET in .env")
        print("Ensure the app registration has Mail.Read and Mail.ReadWrite permissions (Application type).")
        return False

    print("OK: Authentication successful.")
    print()

    # Step 2: List recent emails
    print("[2/3] Fetching recent emails...")
    url = (
        f"{GRAPH_API_BASE}/users/{monitor.mailbox}/messages"
        f"?$select=id,subject,from,hasAttachments,receivedDateTime"
        f"&$top=10"
        f"&$orderby=receivedDateTime desc"
    )

    try:
        resp = requests.get(url, headers=monitor._graph_headers(), timeout=30)
        resp.raise_for_status()
        messages = resp.json().get("value", [])
        print(f"OK: Found {len(messages)} recent emails.")
        print()

        attachment_msg_id = None
        for i, msg in enumerate(messages):
            from_email = msg.get("from", {}).get("emailAddress", {}).get("address", "?")
            subject = msg.get("subject", "(no subject)")
            has_att = msg.get("hasAttachments", False)
            received = msg.get("receivedDateTime", "")[:19]
            att_marker = " [ATTACHMENTS]" if has_att else ""

            print(f"  {i+1}. {received} | From: {from_email}")
            print(f"     Subject: {subject}{att_marker}")

            if has_att and not attachment_msg_id:
                attachment_msg_id = msg["id"]

        print()

    except requests.exceptions.HTTPError as e:
        print(f"FAILED: {e}")
        if e.response is not None:
            print(f"Response: {e.response.text[:500]}")
        return False
    except Exception as e:
        print(f"FAILED: {e}")
        return False

    # Step 3: Test attachment download
    print("[3/3] Testing attachment download...")
    if not attachment_msg_id:
        print("SKIPPED: No emails with attachments found in recent 10 emails.")
        print("Send an email with a PDF attachment to test this feature.")
    else:
        print(f"Downloading attachments from message...")
        pdf_paths = monitor._download_attachments(attachment_msg_id)

        # Also check for non-PDF attachments
        att_url = f"{GRAPH_API_BASE}/users/{monitor.mailbox}/messages/{attachment_msg_id}/attachments"
        att_resp = requests.get(att_url, headers=monitor._graph_headers(), timeout=30)
        att_resp.raise_for_status()
        all_attachments = att_resp.json().get("value", [])

        print(f"  Total attachments: {len(all_attachments)}")
        for att in all_attachments:
            name = att.get("name", "?")
            size = att.get("size", 0)
            ctype = att.get("contentType", "?")
            print(f"    - {name} ({ctype}, {size} bytes)")

        if pdf_paths:
            print(f"  Downloaded {len(pdf_paths)} PDF file(s):")
            for p in pdf_paths:
                fsize = os.path.getsize(p) if os.path.exists(p) else 0
                print(f"    - {p} ({fsize} bytes)")
            print("OK: Attachment download working.")
        else:
            print("  No PDF attachments found (other types present but skipped).")
            print("OK: Attachment API working (no PDFs to download).")

    print()
    print("=" * 60)
    print("Test complete.")
    print("=" * 60)
    return True


def check_for_quotation_emails():
    """Run a single check for quotation emails (for testing)."""
    print("[Check] Running single check for quotation emails...")

    monitor = EmailMonitor()

    if not monitor._get_access_token():
        print("[Check] Failed to authenticate with Graph API")
        return False

    print("[Check] Authenticated. Checking for quotation emails...")

    try:
        monitor._check_for_emails()
        print("[Check] Done.")
        return True
    except Exception as e:
        print(f"[Check] Error: {e}")
        return False


if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd == "test":
            test_graph_connection()
        elif cmd == "check":
            check_for_quotation_emails()
        elif cmd == "run":
            print("[Monitor] Starting email monitor...")
            monitor = get_email_monitor()
            monitor.start()
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\n[Monitor] Stopping...")
                monitor.stop()
        else:
            print("Usage: python email_monitor.py [test|check|run]")
            print("  test  - Test Graph API connection, list emails, test attachment download")
            print("  check - Run a single check for quotation emails")
            print("  run   - Start continuous monitoring")
    else:
        test_graph_connection()
