from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from components.constants import (
    GMAP_SCRAPE_BACKOFF_SECONDS,
    GMAP_SCRAPE_MAX_ATTEMPTS,
)

load_dotenv()

logger = logging.getLogger(__name__)

OUTPUT_PATH = Path(__file__).resolve().parents[2] / "aplify_results.json"

# HTTP statuses that are usually transient for Apify / network.
_RETRYABLE_STATUS_CODES = frozenset({408, 409, 425, 429})


@dataclass
class CandidateRecord:
    place_id: str
    company_name: str
    website: str | None
    phone: str | None
    distance_from_center: float | None
    stars: float | None
    description: str | None


def _apify_item_to_candidate(item: dict[str, Any]) -> CandidateRecord | None:
    place_id = (
        item.get("placeId")
        or item.get("place_id")
        or item.get("id")
        or ""
    )
    company_name = (
        item.get("title")
        or item.get("name")
        or item.get("company_name")
        or ""
    )
    if not place_id or not company_name:
        return None

    website = item.get("website") or item.get("websiteUrl") or None
    phone = item.get("phone") or item.get("phoneUnformatted") or None
    stars_raw = item.get("totalScore") or item.get("stars") or item.get("rating")
    try:
        stars = float(stars_raw) if stars_raw is not None else None
    except (TypeError, ValueError):
        stars = None

    distance_raw = item.get("distance_from_center") or item.get("distance")
    try:
        distance = float(distance_raw) if distance_raw is not None else None
    except (TypeError, ValueError):
        distance = None

    description = item.get("description") or item.get("categoryName") or None
    return CandidateRecord(
        place_id=str(place_id),
        company_name=str(company_name),
        website=str(website) if website else None,
        phone=str(phone) if phone else None,
        distance_from_center=distance,
        stars=stars,
        description=str(description) if description else None,
    )


def _upsert_candidate(record: CandidateRecord) -> None:
    try:
        from repositories.postgresProvider import upsert_initial_candidates
    except Exception as exc:  # pragma: no cover - optional DB
        logger.warning("Skipping candidate upsert (import failed): %s", exc)
        return
    try:
        upsert_initial_candidates(record)
    except Exception as exc:  # pragma: no cover - DB may be down
        logger.warning(
            "Failed to upsert candidate %s (%s): %s",
            record.company_name,
            record.place_id,
            exc,
        )


def _http_status(exc: BaseException) -> int | None:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    response = getattr(exc, "response", None)
    if response is not None:
        code = getattr(response, "status_code", None)
        if isinstance(code, int):
            return code
    return None


def _retry_after_seconds(exc: BaseException, attempt: int) -> float:
    """Backoff delay; prefer Retry-After when present (common on 429)."""
    headers = getattr(exc, "headers", None)
    if headers is None:
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None) if response is not None else None
    if headers is not None:
        raw = None
        try:
            raw = headers.get("Retry-After") or headers.get("retry-after")
        except Exception:
            raw = None
        if raw is not None:
            try:
                return max(float(raw), 0.0)
            except (TypeError, ValueError):
                pass
    return GMAP_SCRAPE_BACKOFF_SECONDS * (2 ** (attempt - 1))


def _is_retryable_scrape_error(exc: BaseException) -> bool:
    """Retry timeouts / connection blips / 429 / 5xx; do not retry auth or client errors."""
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return True

    name = type(exc).__name__
    if name in {
        "TimeoutException",
        "ConnectError",
        "ReadTimeout",
        "WriteTimeout",
        "PoolTimeout",
        "RemoteProtocolError",
        "NetworkError",
    }:
        return True

    try:
        from apify_client.errors import ApifyApiError
    except ImportError:
        ApifyApiError = ()  # type: ignore[misc, assignment]

    status = _http_status(exc)
    if status is None:
        # Unknown non-HTTP failures (e.g. actor logic) — do not burn credits retrying.
        return False

    if status in _RETRYABLE_STATUS_CODES or status >= 500:
        return True

    # Explicitly non-retryable: 401/403/402/404/422 etc.
    if isinstance(exc, ApifyApiError) or 400 <= status < 500:
        return False

    return False


def _run_apify_scrape(
    *,
    location: str,
    company_type: str,
    number: int,
) -> list[dict[str, Any]]:
    from apify_client import ApifyClient

    token = os.getenv("APIFY_API_KEY") or os.getenv("APIFY_TOKEN")
    client = ApifyClient(token) if token else ApifyClient()

    run_input = {
        "language": "en",
        "locationQuery": location,
        "maxCrawledPlacesPerSearch": int(number),
        "maximumLeadsEnrichmentRecords": 0,
        "placeMinimumStars": "threeAndHalf",
        "scrapeContacts": False,
        "scrapeDirectories": False,
        "scrapeImageAuthors": False,
        "scrapeOrderOnline": False,
        "scrapePlaceDetailPage": False,
        "scrapeReviewsPersonalData": False,
        "scrapeSocialMediaProfiles": {
            "facebooks": False,
            "instagrams": False,
            "tiktoks": False,
            "twitters": False,
            "youtubes": False,
        },
        "scrapeTableReservationProvider": False,
        "searchStringsArray": [company_type],
        "skipClosedPlaces": False,
        "verifyLeadsEnrichmentEmails": False,
        "website": "withWebsite",
    }

    run = client.actor("nwua9Gu5YrADL7ZDj").call(run_input=run_input)
    dataset = client.dataset(run["defaultDatasetId"])
    return list(dataset.iterate_items())


def scrape_companies(
    *,
    location: str,
    company_type: str,
    number: int,
    persist_json: bool = True,
    upsert: bool = True,
) -> list[dict[str, Any]]:
    """Run Google Maps Apify scrape and return normalized company dicts.

    Retries transient failures (5xx, 429, timeouts). Does not retry auth,
    payment, or other 4xx client errors.
    """
    try:
        import apify_client  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "apify-client is not installed. Install requirements and set APIFY_TOKEN."
        ) from exc

    attempts = max(1, int(GMAP_SCRAPE_MAX_ATTEMPTS))
    last_error: BaseException | None = None
    raw_items: list[Any] = []

    for attempt in range(1, attempts + 1):
        try:
            raw_items = _run_apify_scrape(
                location=location,
                company_type=company_type,
                number=number,
            )
            last_error = None
            break
        except Exception as exc:
            last_error = exc
            retryable = _is_retryable_scrape_error(exc)
            status = _http_status(exc)
            if not retryable or attempt >= attempts:
                logger.exception(
                    "Google Maps scrape failed (attempt %s/%s, status=%s, retryable=%s)",
                    attempt,
                    attempts,
                    status,
                    retryable,
                )
                raise
            delay = _retry_after_seconds(exc, attempt)
            logger.warning(
                "Google Maps scrape transient error (attempt %s/%s, status=%s): %s; "
                "retrying in %.1fs",
                attempt,
                attempts,
                status,
                exc,
                delay,
            )
            time.sleep(delay)

    if last_error is not None:
        raise last_error

    if persist_json:
        OUTPUT_PATH.write_text(
            json.dumps(raw_items, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    companies: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        record = _apify_item_to_candidate(item)
        if record is None or record.place_id in seen:
            continue
        seen.add(record.place_id)
        if upsert:
            _upsert_candidate(record)
        companies.append(
            {
                "place_id": record.place_id,
                "company": record.company_name,
                "website": record.website,
                "phone": record.phone,
                "stars": record.stars,
                "description": record.description,
            }
        )
    return companies
