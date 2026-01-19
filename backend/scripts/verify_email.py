import os
import sys
from dotenv import load_dotenv

# Add backend to path
sys.path.append(os.path.join(os.getcwd()))

from utils import tools
from core.database import SessionLocal, CostingRequest

def test_vendor_email():
    load_dotenv()
    
    print("--- Verifying Email Sending ---")
    
    # Check config
    from core import config
    print(f"SMTP Email: {config.SMTP_EMAIL}")
    has_pass = bool(os.getenv("GMAIL_APP_PASSWORD") or config.SMTP_PASSWORD)
    print(f"Password Configured: {has_pass}")
    
    # Create a dummy costing request if none exists for testing
    session = SessionLocal()
    dummy_job_id = "TEST-EMAIL-SENT"
    existing = session.query(CostingRequest).filter(CostingRequest.job_id == dummy_job_id).first()
    
    if not existing:
        new_req = CostingRequest(
            user_id=1,
            quotation_id="MOCK-Q",
            line_num=1,
            job_id=dummy_job_id,
            item_details="Email Verification Test",
            status="Draft"
        )
        session.add(new_req)
        session.commit()
        print(f"Created temporary mock job: {dummy_job_id}")
    
    # Attempt to send email
    # This will now use the live sender configuration
    success = tools.send_price_request_email(
        job_id=dummy_job_id,
        item_name="Zaintech Final Verification",
        item_code="ZT-PROD-001",
        quantity=1,
        vendor_email="srikesava.pokkuluri@zaintech.com"
    )
    
    if success:
        print("\nSUCCESS: The system successfully processed the email request.")
        print("Check the logs above for '[SMTP] Email sent to shehryarshahid49@gmail.com'.")
    else:
        print("\nFAILURE: Failed to send email. Check SMTP credentials.")
    
    session.close()

if __name__ == "__main__":
    test_vendor_email()
