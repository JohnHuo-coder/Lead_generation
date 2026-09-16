"""
Compose icebreaker emails from scraped website context + recipient email.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from Anymail_finder import find_email_decision_maker
from prompts import build_icebreaker_user_prompt, ICE_BREAKER_SYSTEM
from schemas import IcebreakerEmail

load_dotenv()

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.4)

# Default ask — override with env OUTREACH_INTENT or pass collaboration_intent to compose_email.
DEFAULT_COLLABORATION_INTENT = (
    "Host a MedSpa & Wellness event for the guest in the hotel"
)



def extract_domain(url: str) -> str:
    cleaned = re.sub(r"^https?://", "", url.strip(), flags=re.IGNORECASE)
    host = cleaned.split("/")[0].lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def generate_icebreaker_email(
    *,
    about_text: str,
    meetings_events_text: str,
    amenities_text: str,
    location_text: str,
    recipient_email: str,
    recipient_name: str,
    company_name: str = "",
    collaboration_intent: Optional[str] = None,
    sender_name: Optional[str] = None,
) -> Dict[str, str]:
    """
    Generate subject + body: one grounded fact from website_context + collaboration ask.
    """
    intent = collaboration_intent or os.getenv("OUTREACH_INTENT") or DEFAULT_COLLABORATION_INTENT
    sender = sender_name or os.getenv("SENDER_NAME") or ""

    human = build_icebreaker_user_prompt(
        company_name = company_name,
        recipient_name = recipient_name,
        recipient_email = recipient_email,
        sender_name = sender,
        collaboration_intent = intent,
        about_text = about_text,
        meetings_events_text = meetings_events_text,
        amenities_text = amenities_text,
        location_text = location_text,
        other_context= ""
    ) 

    structured = llm.with_structured_output(IcebreakerEmail)
    out: IcebreakerEmail = structured.invoke(
        [SystemMessage(content=ICE_BREAKER_SYSTEM), HumanMessage(content=human)]
    )
    return {"subject": out.subject.strip(), "body": out.body.strip()}


def compose_email(
    leads: List[Dict[str, Any]],
    summaries: List[Dict[str, Any]],
    *,
    collaboration_intent: Optional[str] = None,
    sender_name: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    For each Apify-style lead dict (title, website, ...): scrape site, find CEO email, return icebreaker.

    Returns a list of result dicts with subject/body or an error field.
    """
    intent = collaboration_intent or os.getenv("OUTREACH_INTENT") or DEFAULT_COLLABORATION_INTENT
    sender = sender_name or os.getenv("SENDER_NAME")

    results: List[Dict[str, Any]] = []
    # leads after fit scoring
    for item, summary in zip(leads, summaries, strict=True):
        company_name = (item.get("title") or "").strip() 

        # summary could be passed in after fit scoring
        context = summary["full_content"]

        about = summary["about"]
        events_meetings = summary["events_meetings"]
        promotion_news = summary["promotion_news"]
        facility_amenity = summary["facility_amenity"]

        events_meetings_text = "\n".join(events_meetings)
        promotion_news_text = "\n".join(promotion_news)
        facility_amenity_text = "\n".join(facility_amenity)

        website = item["website"]
        domain = extract_domain(website)
        request_success, email_valid, error_message, finder_result = find_email_decision_maker(
            domain, ["ceo"]
        )
        ceo_name = finder_result["person_full_name"] or "there"

        if not request_success:
            results.append(
                {
                    "title": company_name,
                    "website": website,
                    "domain": domain,
                    "error": str(error_message),
                    "subject": None,
                    "body": None,
                    "scrape_status": summary.get("status"),
                }
            )
            continue

        raw = finder_result or {}
        recipient_email = raw.get("email") if isinstance(raw, dict) else None
        if not email_valid or not recipient_email:
            results.append(
                {
                    "title": company_name,
                    "website": website,
                    "domain": domain,
                    "error": "no valid decision-maker email",
                    "subject": None,
                    "body": None,
                    "scrape_status": summary.get("status"),
                }
            )
            continue

        try:
            composed = generate_icebreaker_email(
                about_text = about, 
                meetings_events_text = events_meetings_text,
                amenities_text = facility_amenity_text,
                location_text = "", 
                recipient_email=recipient_email,
                recipient_name = ceo_name,
                company_name=company_name,
                collaboration_intent=intent,
                sender_name=sender,
            )
        except Exception as exc:  # noqa: BLE001 — surface to caller row-by-row
            results.append(
                {
                    "title": company_name,
                    "website": website,
                    "domain": domain,
                    "recipient_email": recipient_email,
                    "error": str(exc),
                    "subject": None,
                    "body": None,
                    "scrape_status": summary.get("status"),
                }
            )
            continue

        results.append(
            {
                "title": company_name,
                "website": website,
                "domain": domain,
                "recipient_email": recipient_email,
                "recipient_name": ceo_name,
                "subject": composed["subject"],
                "body": composed["body"],
                "scrape_status": summary.get("status"),
                "pages_scanned": summary.get("pages_scanned"),
            }
        )

    return results
