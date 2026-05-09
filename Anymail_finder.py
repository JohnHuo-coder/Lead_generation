import requests
from dotenv import load_dotenv
import os

load_dotenv()

ANYMAIL_API_KEY = os.getenv("ANYMAIL_API_KEY")

def find_email_decision_maker(domain, decision_maker_category):
    request_success = True
    email_valid = True
    error_message = None
    data: dict = {}
    try:
        response = requests.post(
            "https://api.anymailfinder.com/v5.1/find-email/decision-maker",
            json={
                "domain": domain,
                "decision_maker_category": decision_maker_category
            },
            headers={
                "Authorization": "YOUR_API_KEY",
                "Content-Type": "application/json"
            }
        )
        data = response.json()

        if response.status_code == 200:
            status = data.get('email_status')
            if status != "valid":
                email_valid = False
        elif response.status_code in [400, 401, 402]:
            request_success = False
            error_message = data.get('message')
        else:
            request_success = False
            error_message = f"Unknown error: {response.status_code} {data.get('message', '')}"
    except requests.RequestException as error:
        request_success = False
        error_message = str(error)
    return request_success, email_valid, error_message, data