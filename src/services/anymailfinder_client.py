from __future__ import annotations

import os
from typing import Literal, TypedDict
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

from repositories.contact_discovery_repository import (
    save_anymail_contact,
    update_anymail_finder_status,
)

load_dotenv()

ANYMAILFINDER_API_URL = "https://api.anymailfinder.com/v5.1/find-email/decision-maker"
ANYMAILFINDER_API_KEY = os.getenv("ANYMAILFINDER_API_KEY")

KNOWN_ERROR_MESSAGES = {
    401: "Missing or invalid API key",
    402: "Your account does not have enough credits",
}


class AnymailFinderResult(TypedDict):
    status: Literal["ok", "failed"]
    email: str | None
    message: str | None


def extract_domain(domain_or_url: str) -> str:
    value = domain_or_url.strip()
    if not value:
        raise ValueError("company_domain is required")

    if "://" not in value:
        value = f"https://{value}"

    host = urlparse(value).netloc
    if not host:
        host = value.split("/")[0]

    return host.removeprefix("www.").lower()


def _fail(
    place_id: str,
    config_id: str,
    message: str,
) -> AnymailFinderResult:
    update_anymail_finder_status(place_id, config_id, message)
    return {"status": "failed", "email": None, "message": message}


def find_email_fallback(
    place_id: str,
    config_id: str,
    decision_maker_category: list[str],
    company_domain: str,
) -> AnymailFinderResult:
    if not ANYMAILFINDER_API_KEY:
        return _fail(place_id, config_id, "Missing ANYMAIL_API_KEY or ANYMAILFINDER_API_KEY")

    try:
        domain = extract_domain(company_domain)
    except ValueError as exc:
        return _fail(place_id, config_id, str(exc))

    try:
        response = httpx.post(
            ANYMAILFINDER_API_URL,
            json={
                "decision_maker_category": decision_maker_category,
                "domain": domain,
            },
            headers={
                "Authorization": f"Bearer {ANYMAILFINDER_API_KEY}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
    except httpx.RequestError as exc:
        return _fail(place_id, config_id, f"Request failed: {exc}")

    if not response.is_success:
        payload = {}
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        message = payload.get("message") or KNOWN_ERROR_MESSAGES.get(
            response.status_code,
            f"Anymail Finder request failed with status {response.status_code}",
        )
        return _fail(place_id, config_id, message)

    data = response.json()
    email = data.get("email") or data.get("valid_email")
    if not email:
        return _fail(place_id, config_id, "Email not found")

    if data.get("email_status") != "valid":
        return _fail(place_id, config_id, "Email not valid")

    save_anymail_contact(
        place_id,
        config_id,
        email,
        data.get("person_first_name"),
        data.get("person_last_name"),
        data.get("person_full_name"),
        data.get("person_job_title"),
        data.get("person_linkedin_url"),
    )
    update_anymail_finder_status(place_id, config_id, "ok")
    return {"status": "ok", "email": email, "message": None}
