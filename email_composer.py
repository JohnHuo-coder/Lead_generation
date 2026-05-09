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
from pydantic import BaseModel, Field

from Anymail_finder import find_email_decision_maker
from web_scraper import MAX_PAGES, scrape_hotel_website_summary

load_dotenv()

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.4)

# Default ask — override with env OUTREACH_INTENT or pass collaboration_intent to compose_email.
DEFAULT_COLLABORATION_INTENT = (
    "Host a MedSpa & Wellness event for the guest in the hotel"
)


class IcebreakerEmail(BaseModel):
    subject: str = Field(description="Short, specific subject line")
    body: str = Field(
        description="Email body: one concrete fact from the site, then brief intro, then clear collaboration intent"
    )


ICE_BREAKER_SYSTEM = """You write concise B2B cold emails for hospitality/outreach.

Rules:
- Open with ONE specific, accurate detail from WEBSITE CONTENT (a fact: amenity, location angle, event, positioning—whatever is actually stated there). Do not invent awards, dates, or claims not present in the text.
- If the content is thin or generic, stay honest: refer broadly to what their site emphasizes without fabricating details.
- Then briefly introduce why you're reaching out and state the collaboration intent clearly (use the provided intent; you may rephrase but keep the meaning).
- Tone: professional, warm, not salesy; no flattery piles; no emojis unless the user content suggests casual brand voice.
- Length: roughly 90-160 words for the body.
- Do not include a fake "unsubscribe" block. Sign off simply (use sender name if provided).
"""


def extract_domain(url: str) -> str:
    cleaned = re.sub(r"^https?://", "", url.strip(), flags=re.IGNORECASE)
    host = cleaned.split("/")[0].lower()
    if host.startswith("www."):
        host = host[4:]
    return host

# needs modification, more detailed context is needed
def _format_scrape_for_prompt(summary: Dict[str, Any]) -> str:
    """Turn scrape_hotel_website_summary output into a single string for the LLM."""
    parts: List[str] = []
    parts.append(f"Status: {summary.get('status', 'unknown')}")
    parts.append(f"High-level summary: {summary.get('high_level_summary', '')}")

    style = summary.get("hotel_style") or {}
    if isinstance(style, dict) and style:
        parts.append(f"Style signal: {style}")

    segments = summary.get("target_customer_segments") or []
    if segments:
        parts.append(f"Audience hints: {segments}")

    events = summary.get("recent_events") or []
    if events:
        snippets = []
        for ev in events[:5]:
            if isinstance(ev, dict):
                snippets.append(
                    f"- {ev.get('event_summary', '')[:200]} (date hint: {ev.get('date_hint', '')})"
                )
        if snippets:
            parts.append("Possible event/meeting mentions:\n" + "\n".join(snippets))

    return "\n\n".join(parts)[:12000]


def generate_icebreaker_email(
    *,
    website_context: str,
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

    human = f"""Company / property name: {company_name or "Unknown"}
    Recipient fulll name (for greeting at the top): {recipient_name}
    Recipient email (for salutation context only): {recipient_email}
    Sender name (sign the email if non-empty): {sender}

    Collaboration intent (reflect in the close):
    {intent}

    WEBSITE CONTENT — facts must only come from this block:
    ---
    {website_context}
    ---
    """

    structured = llm.with_structured_output(IcebreakerEmail)
    out: IcebreakerEmail = structured.invoke(
        [SystemMessage(content=ICE_BREAKER_SYSTEM), HumanMessage(content=human)]
    )
    return {"subject": out.subject.strip(), "body": out.body.strip()}


def compose_email(
    leads: List[Dict[str, Any]],
    *,
    collaboration_intent: Optional[str] = None,
    sender_name: Optional[str] = None,
    max_pages: int = MAX_PAGES,
) -> List[Dict[str, Any]]:
    """
    For each Apify-style lead dict (title, website, ...): scrape site, find CEO email, return icebreaker.

    Returns a list of result dicts with subject/body or an error field.
    """
    intent = collaboration_intent or os.getenv("OUTREACH_INTENT") or DEFAULT_COLLABORATION_INTENT
    sender = sender_name or os.getenv("SENDER_NAME")

    results: List[Dict[str, Any]] = []
    for item in leads:
        company_name = (item.get("title") or "").strip() 
        website = (item.get("website") or "").strip()
        if not website:
            results.append(
                {
                    "title": company_name,
                    "website": "",
                    "error": "missing website",
                    "subject": None,
                    "body": None,
                }
            )
            continue

        summary = scrape_hotel_website_summary(website, max_pages=max_pages)
        context = _format_scrape_for_prompt(summary)

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
                website_context=context,
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
