"""Backward-compatible CLI wrapper around services.gmap_scrape. """

from __future__ import annotations

import json
from pathlib import Path

from dotenv import load_dotenv

from services.gmap_scrape import OUTPUT_PATH, scrape_companies

load_dotenv()


def get_companies_info(data):
    company_type = data["Company Type"]
    location = data["Location"]
    target_number = data["Number"]
    return scrape_companies(
        location=location,
        company_type=company_type,
        number=int(target_number),
        persist_json=True,
    )


if __name__ == "__main__":
    sample = {
        "Company Type": "hotel",
        "Location": "Bangkok",
        "Number": 5,
    }
    items = get_companies_info(sample)
    print(f"scraped {len(items)} companies; raw dump at {OUTPUT_PATH}")
    print(json.dumps(items[:3], ensure_ascii=False, indent=2))
