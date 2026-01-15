"""
Email Monitor Service
Polls inbox for incoming quotation emails and extracts prices using Mistral OCR.
"""
import os
import time
import base64
import json
import threading
from datetime import datetime
from typing import List, Dict, Any, Optional
import config
from database import (
    SessionLocal, CostingRequest, CostingLineItem,
    PendingQuoteRequest
)
from tools import (
    mark_quote_received, check_all_quotes_received,
    update_costing_sheet_with_price, create_costing_sheet_with_items
)

# Try to import Mistral client
try:
    from mistralai import Mistral
    MISTRAL_AVAILABLE = True
except ImportError:
    MISTRAL_AVAILABLE = False
    print("[Warning] Mistral AI SDK not installed. OCR functionality will be mocked.")


class EmailMonitor:
    """
    Monitors inbox for incoming price quotation responses.
    Uses Mistral OCR to extract prices from PDF attachments.
    """

    def __init__(self, poll_interval: int = 60):
        self.poll_interval = poll_interval
        self.running = False
        self._thread = None

        # Initialize Mistral client if available
        self.mistral_client = None
        if MISTRAL_AVAILABLE and os.getenv("MISTRAL_API_KEY"):
            self.mistral_client = Mistral(api_key=os.getenv("MISTRAL_API_KEY"))

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

            time.sleep(self.poll_interval)

    def _check_for_emails(self):
        """Check inbox for new quotation emails."""
        print("[EmailMonitor] Checking for new emails...")

        # Get all pending quote requests
        pending_requests = self._get_pending_requests()

        if not pending_requests:
            print("[EmailMonitor] No pending quote requests")
            return

        for request in pending_requests:
            job_id = request["job_id"]
            item_name = request["item_name"]

            # In production, this would check the actual inbox
            # For now, we simulate finding an email
            email_data = self._fetch_email_for_job(job_id, item_name)

            if email_data:
                self._process_email(email_data, request)

    def _get_pending_requests(self) -> List[Dict[str, Any]]:
        """Get all pending quote requests from database."""
        session = SessionLocal()
        try:
            requests = session.query(PendingQuoteRequest).filter(
                PendingQuoteRequest.status == "pending"
            ).all()

            return [{
                "id": req.id,
                "job_id": req.job_id,
                "item_name": req.item_name,
                "vendor_email": req.vendor_email,
                "costing_request_id": req.costing_request_id
            } for req in requests]
        except Exception as e:
            print(f"[EmailMonitor] DB Error: {e}")
            return []
        finally:
            session.close()

    def _fetch_email_for_job(self, job_id: str, item_name: str) -> Optional[Dict[str, Any]]:
        """
        Fetch email for a specific job ID from inbox.
        In production, this would use IMAP/Graph API to fetch actual emails.
        """
        # Mock implementation - simulates finding an email 20% of the time
        import random
        if random.random() > 0.8:
            print(f"[EmailMonitor] Found email for {job_id}")
            return {
                "job_id": job_id,
                "item_name": item_name,
                "subject": f"RE: Price Quotation Request - {job_id} - {item_name}",
                "from": "vendor@supplier.com",
                "has_attachment": True,
                "attachment_path": None,  # Would be actual PDF path in production
                "body": f"Please find attached our quotation for {item_name}."
            }
        return None

    def _process_email(self, email_data: Dict[str, Any], request: Dict[str, Any]):
        """Process an incoming quotation email."""
        job_id = email_data["job_id"]
        item_name = email_data["item_name"]

        print(f"[EmailMonitor] Processing email for {job_id}, item: {item_name}")

        # Extract price from PDF attachment using OCR
        if email_data.get("has_attachment"):
            attachment_path = email_data.get("attachment_path")

            if attachment_path and os.path.exists(attachment_path):
                # Use Mistral OCR to extract price
                extracted_data = self.extract_prices_from_pdf(attachment_path)
            else:
                # Mock extraction for demo
                extracted_data = self._mock_price_extraction(item_name)

            if extracted_data:
                for item in extracted_data:
                    if item.get("item_name") and item.get("price"):
                        # Update the database with received price
                        success = mark_quote_received(
                            job_id=job_id,
                            item_name=item["item_name"],
                            price=item["price"]
                        )

                        if success:
                            print(f"[EmailMonitor] Updated price for {item['item_name']}: {item['price']}")

                            # Check if all quotes received
                            status = check_all_quotes_received(job_id)
                            if status["all_received"]:
                                print(f"[EmailMonitor] All quotes received for {job_id}. Regenerating costing sheet.")
                                self._regenerate_costing_sheet(job_id)

    def extract_prices_from_pdf(self, pdf_path: str) -> List[Dict[str, Any]]:
        """
        Extract item names and prices from a PDF quotation using Mistral OCR.
        """
        if not self.mistral_client:
            print("[EmailMonitor] Mistral client not available. Using mock extraction.")
            return self._mock_price_extraction("Unknown Item")

        try:
            # Read PDF file
            with open(pdf_path, "rb") as f:
                pdf_content = base64.b64encode(f.read()).decode("utf-8")

            # Use Mistral's vision capability for OCR
            # Note: This uses pixtral model for vision tasks
            response = self.mistral_client.chat.complete(
                model="pixtral-12b-2409",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": """Analyze this quotation document and extract a table of items with their prices.
Return the data as a JSON array with objects containing:
- item_name: the name of the item
- price: the unit price as a number

Only include items that have clear prices listed. Format:
[{"item_name": "Item 1", "price": 1500.00}, ...]"""
                            },
                            {
                                "type": "image_url",
                                "image_url": f"data:application/pdf;base64,{pdf_content}"
                            }
                        ]
                    }
                ]
            )

            # Parse response
            content = response.choices[0].message.content

            # Try to extract JSON from response
            try:
                # Find JSON array in response
                start = content.find("[")
                end = content.rfind("]") + 1
                if start >= 0 and end > start:
                    json_str = content[start:end]
                    return json.loads(json_str)
            except json.JSONDecodeError:
                print(f"[EmailMonitor] Failed to parse OCR response: {content}")

            return []

        except Exception as e:
            print(f"[EmailMonitor] OCR Error: {e}")
            return self._mock_price_extraction("Unknown Item")

    def _mock_price_extraction(self, item_name: str) -> List[Dict[str, Any]]:
        """Mock price extraction for demo purposes."""
        import random
        return [{
            "item_name": item_name,
            "price": round(random.uniform(500, 3000), 2)
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
                costing_req.status = "Completed"
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
