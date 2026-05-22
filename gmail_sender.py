import os
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from email.mime.text import MIMEText
from base64 import urlsafe_b64encode


SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
def get_gmail_service():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port = 0)
        
        with open("token.json", "w", encoding = "utf-8") as f:
            f.write(creds.to_json())
    service = build("gmail", "v1", credentials = creds)
    return service

service = get_gmail_service()

def send_gmail(to_email, subject, body):
    message = MIMEText(body, "plain", "utf-8")
    message["to"] = to_email
    message["subject"] = subject
    raw = urlsafe_b64encode(message.as_bytes()).decode()

    service.users().messages().send(
        userId = "me",
        body = {"raw": raw}
    ).execute()