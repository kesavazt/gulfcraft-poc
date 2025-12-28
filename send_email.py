import smtplib
from email.message import EmailMessage

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

EMAIL = "your_email@gmail.com"
PASSWORD = "your_app_password"  # NOT your normal password

msg = EmailMessage()
msg["From"] = EMAIL
msg["To"] = "receiver@example.com"
msg["Subject"] = "Test email from Python"
msg.set_content("Hello, this email was sent using Python SMTP.")

with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
    server.starttls()
    server.login(EMAIL, PASSWORD)
    server.send_message(msg)

print("✅ Email sent")

