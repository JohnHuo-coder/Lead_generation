import httpx
import os
from dotenv import load_dotenv

load_dotenv()
APOLLO_API_KEY = os.getenv("APOLLO_API_KEY")
APOLLO_BASE_URL = "https://api.apollo.io/v1"
APOLLO_GET_COMPANY_ID_URL = "https://api.apollo.io/api/v1/mixed_companies/search"
APOLLO_GET_PERSON_ID_URL = "https://api.apollo.io/api/v1/mixed_people/api_search"
APOLLO_GET_PERSON_EMAIL_URL = "https://api.apollo.io/api/v1/people/match"

def find_company_id(company: str, company_domain: str) -> dict | None:
    response = httpx.post(
        f"{APOLLO_GET_COMPANY_ID_URL}",
        json={"q_organization_name": company, "q_organization_domains_list": [company_domain]},
        headers={"X-Api-Key": APOLLO_API_KEY},
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    has_result = data["pagination"]["total_entries"] > 0
    if has_result:
        org_id = data["organizations"][0]["id"]
        domains_list = data["breadcrumbs"][1]["value"]

def find_person_id(org_id, contact_titles, domains_list):
    response = httpx.post(
        f"{APOLLO_GET_PERSON_ID_URL}",
        json = {
            "organization_ids": [org_id],
            "q_organization_domains_list": domains_list,
            "contact_email_status": ["verified"],
            "person_titles": contact_titles,
            "per_page": 1,
            "page": 1
        },
        headers = {"X-Api-Key": APOLLO_API_KEY},
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    has_result = data["total_entries"] > 0
    if has_result:
        person_id = data["people"][0]["id"]
    

def find_person_email(person_id):
    response = httpx.post(
        f"{APOLLO_GET_PERSON_EMAIL_URL}",
        json = {
            "id": person_id
        },
        headers = {"X-Api-Key": APOLLO_API_KEY},
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    profile = data["person"]

    