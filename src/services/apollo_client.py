from __future__ import annotations

import os
from typing import Any, Literal, TypedDict

import httpx
from dotenv import load_dotenv

from repositories.contact_discovery_repository import (
    save_apollo_contact,
    update_apollo_status,
)
from services.anymailfinder_client import extract_domain

load_dotenv()

APOLLO_API_KEY = os.getenv("APOLLO_API_KEY")
APOLLO_COMPANY_SEARCH_URL = "https://api.apollo.io/api/v1/mixed_companies/search"
APOLLO_PERSON_SEARCH_URL = "https://api.apollo.io/api/v1/mixed_people/api_search"
APOLLO_PERSON_MATCH_URL = "https://api.apollo.io/api/v1/people/match"
APOLLO_TIMEOUT = 30.0


class ApolloLookupResult(TypedDict):
    status: Literal["ok", "failed"]
    email: str | None
    message: str | None


class ApolloCompanyLookup(TypedDict):
    org_id: str
    domains_list: list[str]


def _apollo_headers() -> dict[str, str]:
    return {
        "X-Api-Key": APOLLO_API_KEY or "",
        "Content-Type": "application/json",
    }


def _fail(place_id: str, config_id: str, message: str) -> ApolloLookupResult:
    update_apollo_status(place_id, config_id, message)
    return {"status": "failed", "email": None, "message": message}


def _request_json(
    url: str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        response = httpx.post(
            url,
            json=payload,
            headers=_apollo_headers(),
            timeout=APOLLO_TIMEOUT,
        )
    except httpx.RequestError as exc:
        return None, f"Request failed: {exc}"

    if not response.is_success:
        body: dict[str, Any] = {}
        try:
            body = response.json()
        except ValueError:
            body = {}
        message = body.get("error") or body.get("message") or (
            f"Apollo request failed with status {response.status_code}"
        )
        return None, message

    try:
        return response.json(), None
    except ValueError:
        return None, "Apollo returned invalid JSON"


def _organization_domains(
    organization: dict[str, Any],
    fallback_domain: str,
) -> list[str]:
    domains: list[str] = []
    for key in ("primary_domain", "website_url", "domain"):
        value = organization.get(key)
        if not value:
            continue
        if key == "website_url":
            domains.append(extract_domain(str(value)))
        else:
            domains.append(str(value).removeprefix("www.").lower())
    if domains:
        return domains
    return [fallback_domain]


def find_company_id(
    place_id: str,
    config_id: str,
    company: str,
    company_domain: str,
) -> ApolloCompanyLookup | ApolloLookupResult:
    data, error = _request_json(
        APOLLO_COMPANY_SEARCH_URL,
        {
            "q_organization_name": company,
            "q_organization_domains_list": [company_domain],
            "page": 1,
            "per_page": 1,
        },
    )
    if error:
        return _fail(place_id, config_id, f"[company_lookup] {error}")

    organizations = data.get("organizations") or []
    total_entries = (data.get("pagination") or {}).get("total_entries", 0)
    if total_entries <= 0 or not organizations:
        return _fail(place_id, config_id, "[company_lookup] Organization not found")

    organization = organizations[0]
    org_id = organization.get("id")
    if not org_id:
        return _fail(place_id, config_id, "[company_lookup] Organization id missing")

    return {
        "org_id": org_id,
        "domains_list": _organization_domains(organization, company_domain),
    }


def find_person_id(
    place_id: str,
    config_id: str,
    org_id: str,
    contact_titles: list[str],
    domains_list: list[str],
) -> str | ApolloLookupResult:
    data, error = _request_json(
        APOLLO_PERSON_SEARCH_URL,
        {
            "organization_ids": [org_id],
            "q_organization_domains_list": domains_list,
            "contact_email_status": ["verified"],
            "person_titles": contact_titles,
            "per_page": 1,
            "page": 1,
        },
    )
    if error:
        return _fail(place_id, config_id, f"[person_lookup] {error}")

    people = data.get("people") or []
    total_entries = data.get("total_entries", 0)
    if total_entries <= 0 or not people:
        return _fail(place_id, config_id, "[person_lookup] No matching contact found")

    person_id = people[0].get("id")
    if not person_id:
        return _fail(place_id, config_id, "[person_lookup] Contact id missing")

    return person_id


def find_person_email(
    place_id: str,
    config_id: str,
    person_id: str,
) -> dict[str, Any] | ApolloLookupResult:
    data, error = _request_json(
        APOLLO_PERSON_MATCH_URL,
        {"id": person_id},
    )
    if error:
        return _fail(place_id, config_id, f"[email_lookup] {error}")

    person = data.get("person") or {}
    email = person.get("email")
    if not email:
        return _fail(place_id, config_id, "[email_lookup] Email not found")

    return person


def find_email_apollo(
    place_id: str,
    config_id: str,
    company: str,
    company_domain: str,
    contact_titles: list[str],
) -> ApolloLookupResult:
    if not APOLLO_API_KEY:
        return _fail(place_id, config_id, "Missing APOLLO_API_KEY")

    try:
        domain = extract_domain(company_domain)
    except ValueError as exc:
        return _fail(place_id, config_id, f"[company_lookup] {exc}")

    company_result = find_company_id(place_id, config_id, company, domain)
    if company_result.get("status") == "failed":
        return company_result

    person_result = find_person_id(
        place_id,
        config_id,
        company_result["org_id"],
        contact_titles,
        company_result["domains_list"],
    )
    if isinstance(person_result, dict):
        return person_result

    person = find_person_email(place_id, config_id, person_result)
    if person.get("status") == "failed":
        return person

    save_apollo_contact(place_id, config_id, person["email"], person)
    update_apollo_status(place_id, config_id, "ok")
    return {"status": "ok", "email": person["email"], "message": None}
