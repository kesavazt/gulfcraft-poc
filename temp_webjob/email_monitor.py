"""
Email Monitor Service
Polls inbox via IMAP for incoming quotation emails and extracts prices using Mistral OCR.
"""
import os
import sys
import time
import email
import imaplib
import threading
from email.header import decode_header
from email.message import Message
from datetime import datetime
from typing import List, Dict, Any, Optional, cast

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
    from pdf_extractor import extract_line_items_from_pdf
    PDF_EXTRACTOR_AVAILABLE = True
except ImportError:
    PDF_EXTRACTOR_AVAILABLE = False
    print("[Warning] pdf_extractor not available")


# IMAP configuration for Gmail
IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.gmail.com")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))


class EmailMonitor:
    """
    Monitors inbox via IMAP for incoming price quotation responses.
    Uses Mistral OCR to extract prices from PDF attachments.
    """

    def __init__(self, poll_interval: int = 60):
        self.poll_interval = poll_interval
        self.running = False
        self._thread = None
        self.temp_dir = "temp_attachments"
        self.imap_connection: Optional[imaplib.IMAP4_SSL] = None

        # Create temp directory for attachments
        os.makedirs(self.temp_dir, exist_ok=True)

        # Get IMAP credentials from config
        # For Gmail, use GMAIL_APP_PASSWORD if available
        self.imap_email = config.SMTP_EMAIL
        self.imap_password = os.getenv("GMAIL_APP_PASSWORD", "").strip('"') or config.SMTP_PASSWORD

        print(f"[EmailMonitor] Configured for IMAP: {IMAP_SERVER}:{IMAP_PORT}")
        print(f"[EmailMonitor] Email account: {self.imap_email}")

    def _connect_imap(self) -> bool:
        """Connect to IMAP server."""
        try:
            # Close existing connection if any
            if self.imap_connection:
                try:
                    self.imap_connection.logout()
                except:
                    pass

            # Connect to IMAP server with SSL
            print(f"[EmailMonitor] Connecting to {IMAP_SERVER}:{IMAP_PORT}...")
            self.imap_connection = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)

            # Login
            print(f"[EmailMonitor] Logging in as {self.imap_email}...")
            self.imap_connection.login(self.imap_email, self.imap_password)

            print("[EmailMonitor] IMAP connection established")
            return True

        except imaplib.IMAP4.error as e:
            print(f"[EmailMonitor] IMAP login error: {e}")
            print("[EmailMonitor] For Gmail, you need to use an App Password:")
            print("  1. Enable 2-Step Verification in your Google Account")
            print("  2. Go to Google Account > Security > App passwords")
            print("  3. Generate a new app password for 'Mail'")
            print("  4. Use that password in SMTP_PASSWORD in .env")
            return False
        except Exception as e:
            print(f"[EmailMonitor] IMAP connection error: {e}")
            return False

    def _disconnect_imap(self):
        """Disconnect from IMAP server."""
        if self.imap_connection:
            try:
                self.imap_connection.logout()
            except:
                pass
            self.imap_connection = None

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
        self._disconnect_imap()
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
                # Reconnect on error
                self._disconnect_imap()

            time.sleep(self.poll_interval)

    def _check_for_emails(self):
        """Check inbox for new quotation emails via IMAP."""
        print("[EmailMonitor] Checking for new emails...")

        # Connect to IMAP if not connected
        if not self.imap_connection:
            if not self._connect_imap():
                return

        # Get all pending quote requests (can be empty, we still process emails)
        pending_requests = self._get_pending_requests()
        print(f"[EmailMonitor] {len(pending_requests)} pending quote requests in DB")

        try:
            if not self.imap_connection:
                return

            conn = self.imap_connection
            # Select inbox
            conn.select("INBOX")

            # Search for unread emails - look for replies to quotation requests
            # Search for emails containing "Quotation" OR "JOB-" in subject
            # We search for multiple patterns to catch replies
            all_email_ids = set()

            # Search patterns for quotation-related emails
            search_patterns = [
                '(UNSEEN SUBJECT "Price Quotation Request")',
                '(UNSEEN SUBJECT "RE: Price Quotation")',
                '(UNSEEN SUBJECT "JOB-")',
                '(UNSEEN SUBJECT "COST-")',
            ]

            for pattern in search_patterns:
                try:
                    status, messages = conn.search(None, pattern)
                    if status == "OK" and messages[0]:
                        for email_id in messages[0].split():
                            all_email_ids.add(email_id)
                except:
                    pass

            email_ids = list(all_email_ids)
            print(f"[EmailMonitor] Found {len(email_ids)} unread quotation-related emails")

            for email_id in email_ids:
                try:
                    self._process_email(email_id, pending_requests)
                except Exception as e:
                    print(f"[EmailMonitor] Error processing email {email_id}: {e}")

        except imaplib.IMAP4.error as e:
            print(f"[EmailMonitor] IMAP error: {e}")
            self._disconnect_imap()
        except Exception as e:
            print(f"[EmailMonitor] Error checking emails: {e}")
            self._disconnect_imap()

    def _get_pending_requests(self) -> List[Dict[str, Any]]:
        """Get all pending quote requests from database."""
        session = SessionLocal()
        try:
            requests_list = session.query(PendingQuoteRequest).filter(
                PendingQuoteRequest.status == "pending"
            ).all()

            return [{
                "id": req.id,
                "job_id": req.job_id,
                "item_name": req.item_name,
                "vendor_email": req.vendor_email,
                "costing_request_id": req.costing_request_id
            } for req in requests_list]
        except Exception as e:
            print(f"[EmailMonitor] DB Error: {e}")
            return []
        finally:
            session.close()

    def _process_email(self, email_id: bytes, pending_requests: List[Dict[str, Any]]):
        """Process a single email."""
        if not self.imap_connection:
            return
        conn = self.imap_connection

        # Fetch the email
        message_id = email_id.decode() if isinstance(email_id, bytes) else str(email_id)
        status, msg_data = conn.fetch(message_id, "(RFC822)")

        if status != "OK":
            print(f"[EmailMonitor] Failed to fetch email {email_id}")
            return

        if not msg_data or not msg_data[0]:
            print(f"[EmailMonitor] Empty email data for {email_id}")
            return

        # Parse the email
        raw_email = msg_data[0][1]
        raw_bytes = cast(bytes, raw_email)
        msg = email.message_from_bytes(raw_bytes)

        # Decode subject
        subject = self._decode_header(msg["Subject"])
        from_addr = self._decode_header(msg["From"])

        print(f"[EmailMonitor] Processing email from: {from_addr}")
        print(f"[EmailMonitor] Subject: {subject}")

        # Extract job_id and item_name from subject
        job_id, item_name = self._parse_subject(subject)

        if not job_id:
            print(f"[EmailMonitor] Could not extract job_id from subject: {subject}")
            # Mark as read anyway to avoid reprocessing
            self._mark_as_read(email_id)
            return

        print(f"[EmailMonitor] Extracted job_id: {job_id}, item_name: {item_name}")

        # Find matching pending request (optional - we can still process without it)
        matching_request = None
        for req in pending_requests:
            if req["job_id"] == job_id:
                if item_name and req["item_name"].lower() in item_name.lower():
                    matching_request = req
                    break
                elif not matching_request:
                    matching_request = req

        if matching_request:
            print(f"[EmailMonitor] Found matching pending request for item: {matching_request['item_name']}")
        else:
            print(f"[EmailMonitor] No pending request found for job_id: {job_id} (will still extract data)")

        # Use item_name from subject if no matching request
        default_item_name = item_name or "Unknown Item"
        if matching_request:
            default_item_name = matching_request["item_name"]

        # Extract attachments
        pdf_paths = self._extract_pdf_attachments(msg)

        if pdf_paths:
            print(f"[EmailMonitor] Found {len(pdf_paths)} PDF attachment(s)")

            for pdf_path in pdf_paths:
                # Extract prices from PDF using OCR
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

                # Clean up temp file
                try:
                    os.remove(pdf_path)
                except:
                    pass
        else:
            # No PDF found, try body
            body_text = self._get_email_body(msg)
            print(f"[EmailMonitor] No PDF attachment. Email body preview: {body_text[:200] if body_text else 'Empty'}")

            price = self._extract_price_from_text(body_text)
            if price:
                print(f"[EmailMonitor] Extracted price from body: {price}")
                self._update_prices_from_extraction(
                    job_id=job_id,
                    item_name=default_item_name,
                    extracted_data=[{"item_name": default_item_name, "unit_price": price}]
                )

        # Mark email as read
        self._mark_as_read(email_id)
        print(f"[EmailMonitor] Marked email as read")

    def _decode_header(self, header_value: str) -> str:
        """Decode email header value."""
        if not header_value:
            return ""

        decoded_parts = decode_header(header_value)
        result = []

        for part, encoding in decoded_parts:
            if isinstance(part, bytes):
                result.append(part.decode(encoding or "utf-8", errors="replace"))
            else:
                result.append(part)

        return " ".join(result)

    def _extract_pdf_attachments(self, msg: Message) -> List[str]:
        """Extract PDF attachments from email."""
        pdf_paths = []

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))

                # Check if it's a PDF attachment
                if "attachment" in content_disposition or content_type == "application/pdf":
                    filename = part.get_filename()

                    if filename:
                        filename = self._decode_header(filename)

                    if not filename:
                        filename = "attachment.pdf"

                    # Check if it's a PDF
                    if filename.lower().endswith(".pdf") or content_type == "application/pdf":
                        # Get attachment content
                        payload = part.get_payload(decode=True)

                        if payload:
                            # Save to temp file
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            safe_filename = f"{timestamp}_{filename}"
                            filepath = os.path.join(self.temp_dir, safe_filename)

                            with open(filepath, "wb") as f:
                                f.write(cast(bytes, payload))

                            pdf_paths.append(filepath)
                            print(f"[EmailMonitor] Saved PDF: {filepath}")

        return pdf_paths

    def _get_email_body(self, msg: Message) -> str:
        """Extract email body text."""
        body = ""

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()

                if content_type == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        body = cast(bytes, payload).decode(charset, errors="replace")
                        break
                elif content_type == "text/html" and not body:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        html_body = cast(bytes, payload).decode(charset, errors="replace")
                        # Strip HTML tags
                        import re
                        body = re.sub(r'<[^>]+>', '', html_body)
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                body = cast(bytes, payload).decode(charset, errors="replace")

        return body

    def _mark_as_read(self, email_id: bytes):
        """Mark an email as read (add SEEN flag)."""
        try:
            if not self.imap_connection:
                return
            message_id = email_id.decode() if isinstance(email_id, bytes) else str(email_id)
            self.imap_connection.store(message_id, "+FLAGS", "\\Seen")
        except Exception as e:
            print(f"[EmailMonitor] Error marking email as read: {e}")

    def _parse_subject(self, subject: str) -> tuple:
        """Parse job_id and item_name from email subject."""
        # Expected format: "RE: Price Quotation Request - JOB-XXXXXXXX - Item Name"

        job_id = None
        item_name = None

        if not subject:
            return job_id, item_name

        # Remove RE:, FW:, Fwd: prefixes
        clean_subject = subject
        for prefix in ["RE:", "Re:", "re:", "FW:", "Fw:", "fw:", "Fwd:", "FWD:"]:
            clean_subject = clean_subject.replace(prefix, "").strip()

        # Split by " - "
        parts = clean_subject.split(" - ")

        for i, part in enumerate(parts):
            part = part.strip()
            # Look for JOB-XXXXXXXX pattern
            if part.startswith("JOB-") or part.startswith("COST-"):
                job_id = part
                # Item name is usually the next part
                if i + 1 < len(parts):
                    item_name = parts[i + 1].strip()
                break

        return job_id, item_name

    def _extract_price_from_text(self, text: str) -> Optional[float]:
        """Try to extract a price from plain text."""
        import re

        if not text:
            return None

        # Look for common price patterns
        patterns = [
            r'\$[\d,]+\.?\d*',  # $1,234.56
            r'USD\s*[\d,]+\.?\d*',  # USD 1234.56
            r'AED\s*[\d,]+\.?\d*',  # AED 1,234.56
            r'[\d,]+\.?\d*\s*(?:USD|AED|SAR)',  # 1234.56 USD
            r'(?:price|total|amount|cost)[\s:]*[\d,]+\.?\d*',  # price: 1234.56
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                # Extract numeric value from first match
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

                    # Use precise ID-based update instead of name matching
                    success = mark_quote_received_by_id(
                        line_item_id=matched_id,
                        price=cost_price,
                        job_id=job_id
                    )

                    if success:
                        print(f"[EmailMonitor] ✓ Updated price for {ocr_item.get('item_name', item_name)}: {cost_price}")

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

                # Update the database with unit cost only
                success = mark_quote_received(
                    job_id=job_id,
                    item_name=extracted_item_name,
                    price=cost_price
                )

                if success:
                    print(f"[EmailMonitor] Updated price for {extracted_item_name}: {cost_price}")

                    # Check if all quotes received
                    status = check_all_quotes_received(job_id)
                    if status["all_received"]:
                        print(f"[EmailMonitor] All quotes received for {job_id}. Regenerating costing sheet.")
                        self._regenerate_costing_sheet(job_id)

    def extract_prices_from_pdf(self, pdf_path: str) -> List[Dict[str, Any]]:
        """
        Extract item names and prices from a PDF quotation using Mistral OCR.
        """
        if PDF_EXTRACTOR_AVAILABLE and extract_line_items_from_pdf:
            try:
                # Use the pdf_extractor module
                items = extract_line_items_from_pdf(pdf_path)
                return items
            except Exception as e:
                print(f"[EmailMonitor] PDF extraction error: {e}")
                return []
        else:
            print("[EmailMonitor] PDF extractor not available. Using mock extraction.")
            return self._mock_price_extraction("Unknown Item")

    def _mock_price_extraction(self, item_name: str) -> List[Dict[str, Any]]:
        """Mock price extraction for demo purposes."""
        import random
        return [{
            "item_name": item_name,
            "unit_price": round(random.uniform(500, 3000), 2)
        }]

    def _regenerate_costing_sheet(self, job_id: str):
        """Regenerate the costing sheet with updated prices."""
        session = SessionLocal()
        try:
            costing_req = session.query(CostingRequest).filter(
                CostingRequest.job_id == job_id
            ).first()

            if not costing_req:
                return

            # Get all line items
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

            # Regenerate sheet
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
    """
    Manually process a mock email for testing purposes.
    Simulates receiving a quotation email with a specific price.
    """
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


def test_imap_connection():
    """Test IMAP connection and list recent emails."""
    print("[Test] Testing IMAP connection...")
    print(f"[Test] Server: {IMAP_SERVER}:{IMAP_PORT}")
    print(f"[Test] Email: {config.SMTP_EMAIL}")

    monitor = EmailMonitor()

    if not monitor._connect_imap():
        print("[Test] Failed to connect to IMAP")
        return False

    print("[Test] IMAP connection successful!")

    try:
        if not monitor.imap_connection:
            return False

        # Select inbox
        monitor.imap_connection.select("INBOX")

        # Get recent emails
        status, messages = monitor.imap_connection.search(None, "ALL")

        if status == "OK":
            email_ids = messages[0].split()
            recent_ids = email_ids[-5:] if len(email_ids) > 5 else email_ids

            print(f"[Test] Found {len(email_ids)} total emails. Showing last {len(recent_ids)}:")

            for email_id in reversed(recent_ids):
                message_id = email_id.decode() if isinstance(email_id, bytes) else str(email_id)
                status, msg_data = monitor.imap_connection.fetch(message_id, "(RFC822.HEADER)")
                if status == "OK" and msg_data and msg_data[0]:
                    header = email.message_from_bytes(cast(bytes, msg_data[0][1]))
                    subject = monitor._decode_header(header["Subject"])[:50]
                    from_addr = monitor._decode_header(header["From"])[:40]
                    print(f"  - From: {from_addr}... | Subject: {subject}...")

        monitor._disconnect_imap()
        return True

    except Exception as e:
        print(f"[Test] Error: {e}")
        monitor._disconnect_imap()
        return False


def check_for_quotation_emails():
    """Run a single check for quotation emails (for testing)."""
    print("[Check] Running single check for quotation emails...")

    monitor = EmailMonitor()

    if not monitor._connect_imap():
        print("[Check] Failed to connect to IMAP")
        return False

    print("[Check] Connected to IMAP. Checking for quotation emails...")

    try:
        monitor._check_for_emails()
        monitor._disconnect_imap()
        print("[Check] Done.")
        return True
    except Exception as e:
        print(f"[Check] Error: {e}")
        monitor._disconnect_imap()
        return False


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd == "test":
            test_imap_connection()
        elif cmd == "check":
            check_for_quotation_emails()
        elif cmd == "run":
            # Run the monitor continuously
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
            print("  test  - Test IMAP connection and show recent emails")
            print("  check - Run a single check for quotation emails")
            print("  run   - Start continuous monitoring")
    else:
        # Run test by default
        test_imap_connection()
