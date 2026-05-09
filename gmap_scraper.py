import os
from apify_client import ApifyClient
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

APIFY_API_KEY = os.getenv("APIFY_API_KEY")

client = ApifyClient()

current_path = Path(__file__).resolve().parent()
OUTPUT_PATH = current_path / "aplify_results.json"

def get_companies_info(data): 
    company_type = data["Company Type"]
    location = data["Location"]
    target_number = data["Number"]
    # Prepare the Actor input
    run_input = {
        "searchStringsArray": [company_type],
        "locationQuery": location,
        "maxCrawledPlacesPerSearch": target_number,
        "language": "en",
        "searchMatching": "all",
        "placeMinimumStars": "",
        "website": "withWebsite",
        "skipClosedPlaces": False,
        "scrapePlaceDetailPage": False,
        "scrapeTableReservationProvider": False,
        "includeWebResults": False,
        "scrapeDirectories": False,
        "maxQuestions": 0,
        "scrapeContacts": False,
        "scrapeSocialMediaProfiles": {
            "facebooks": False,
            "instagrams": False,
            "youtubes": False,
            "tiktoks": False,
            "twitters": False,
        },
        "maximumLeadsEnrichmentRecords": 0,
        "leadsEnrichmentDepartments": [
            "sales",
            "marketing",
        ],
        "verifyLeadsEnrichmentEmails": False,
        "maxReviews": 0,
        "reviewsStartDate": "2024-01-01",
        "reviewsSort": "newest",
        "reviewsFilterString": "",
        "reviewsOrigin": "all",
        "scrapeReviewsPersonalData": True
    }


    # Run the Actor and wait for it to finish
    run = client.actor("nwua9Gu5YrADL7ZDj").call(run_input=run_input)

    dataset = client.dataset(run["defaultDatasetId"])

    # with open("apify_results.jsonl", "w", encoding="utf-8") as f:
    #     for item in dataset.iterate_items():
    #         f.write(json.dumps(item, ensure_ascii=False))

    items = list(dataset.iterate_items())
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

    print(f"result saved to {OUTPUT_PATH}")
    return items