# services/anymailfinder_client.py
import httpx
import os
from dotenv import load_dotenv

load_dotenv()
ANYMAILFINDER_API_KEY = os.getenv("ANYMAILFINDER_API_KEY")

def find_email_fallback(decision_maker_category: list, company_domain: str) -> str | None:
    response = httpx.post(
        "https://api.anymailfinder.com/v5.1/find-email/decision-maker",
        json={"decision_maker_category": decision_maker_category, "domain": company_domain},
        headers={"Authorization": f"Bearer {ANYMAILFINDER_API_KEY}"},
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()

[
  {
    "credits_charged": 2,
    "decision_maker_category": "sales",
    "email": "shabnam.ali@accor.com",
    "email_status": "valid",
    "input": {
      "decision_maker_category": [
        "sales",
        "marketing"
      ],
      "domain": "https://all.accor.com/lien_externe.svlt?goto=fiche_hotel&code_hotel=7295&merchantid=seo-maps-TH-7295&sourceid=aw-cen&utm_medium=seo%20maps&utm_source=google%20Maps&utm_campaign=seo%20maps"
    },
    "mx_domain": "trendmicro.eu",
    "mx_host": "accor.in.tmes.trendmicro.eu",
    "person_first_name": "Ali",
    "person_full_name": "Ali Shabnam",
    "person_job_title": "Senior Sales Manager",
    "person_last_name": "Shabnam",
    "person_linkedin_url": null,
    "valid_email": "shabnam.ali@accor.com"
  }
]