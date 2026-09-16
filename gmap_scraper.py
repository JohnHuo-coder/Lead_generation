import os
from apify_client import ApifyClient
import json
from pathlib import Path
from dotenv import load_dotenv
from repositories.postgresProvider import upsert_initial_candidates
from psycopg.errors import Error

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
        "language": "en",
        "locationQuery": location,
        "maxCrawledPlacesPerSearch": target_number,
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
            "youtubes": False
        },
        "scrapeTableReservationProvider": False,
        "searchStringsArray": [company_type],
        "skipClosedPlaces": False,
        "verifyLeadsEnrichmentEmails": False,
        "website": "withWebsite"
    }


    # Run the Actor and wait for it to finish
    run = client.actor("nwua9Gu5YrADL7ZDj").call(run_input=run_input)

    dataset = client.dataset(run["defaultDatasetId"])
    items = list(dataset.iterate_items())
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    print(f"gmap scraped results saved to {OUTPUT_PATH}")

    return items