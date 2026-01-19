import smtplib
import os
from email.message import EmailMessage
from dotenv import load_dotenv

def test_ms_smtp():
    load_dotenv()
    
    # Get configuration
    smtp_server = "smtp.office365.com"
    smtp_port = 587
    # Use MS_GRAPH_SENDER_EMAIL as the login user for this test
    sender_email = os.getenv("MS_GRAPH_SENDER_EMAIL", "ai.zaintech@gulfcraftinc.com")
    # Use the SMTP_PASSWORD from .env
    password = os.getenv("SMTP_PASSWORD", "P)814147666556ab")
    
    receiver_email = "srikesava.pokkuluri@zaintech.com"
    
    print(f"--- Microsoft SMTP Test ---")
    print(f"Server: {smtp_server}:{smtp_port}")
    print(f"Login User: {sender_email}")
    print(f"Recipient: {receiver_email}")
    print(f"Password provided: {'Yes' if password else 'No'}")
    
    msg = EmailMessage()
    msg["From"] = sender_email
    msg["To"] = receiver_email
    msg["Subject"] = "Zaintech AI Costing - Microsoft SMTP Test"
    msg.set_content("This is a test email sent from the Microsoft account using SMTP via Python.")
    
    try:
        print("Connecting to server...")
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.set_debuglevel(1)  # Enable debug output to see the SMTP conversation
        server.starttls()
        print("Logging in...")
        server.login(sender_email, password)
        print("Sending email...")
        server.send_message(msg)
        server.quit()
        print("\nSUCCESS: Email sent successfully!")
    except Exception as e:
        print(f"\nFAILURE: {e}")

if __name__ == "__main__":
    test_ms_smtp()
