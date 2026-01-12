import smtplib
from email.message import EmailMessage

SMTP_HOST = "smtp.office365.com"
SMTP_PORT = 587

EMAIL = "ai.zaintech@gulfcraftinc.com"
PASSWORD = "P)814147666556ab"  # NOT your normal password

msg = EmailMessage()
msg["From"] = EMAIL
msg["To"] = "shahryar.ahmad@zaintech.com"
msg["Subject"] = "Gulfcraft Bot Email"
msg.set_content("Hi, I hope this email finds you well. I look forward to work with you. Kindly join the meeting.")

try:
    server = smtplib.SMTP(SMTP_HOST,SMTP_PORT)
    server.starttls()
    server.login(EMAIL, PASSWORD)
    server.send_message(msg)
    print("✅ Email sent")
except Exception as e:
    print(e)

