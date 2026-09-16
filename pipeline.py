
import json
from pathlib import Path
import time
import requests
import gspread
from oauth2client.service_account import ServiceAccountCredentials

from gmap_scraper import get_companies_info
from fit_scoring import filter_matches
from email_composer import compose_email
from utils import haversine
from repositories.postgresProvider import upsert_initial_candidates
from psycopg.errors import Error

ROOT = Path(__file__).resolve.parent
SHEET_NAME = "lead_gen"
TARGET_COLUMN = "Status"
WEBHOOK_URL = ""
COL = "Status"
BUSINESS_CONFIG_PATH = "business_config.json"

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

creds = ServiceAccountCredentials.from_json_keyfile_name(
    "sheet-monitor-495716-74189a665319.json", scope
)

client = gspread.authorize(creds)
sheet = client.open(SHEET_NAME).sheet1

with open(BUSINESS_CONFIG_PATH, "r", encoding="utf-8") as f:
    bconfig: dict = json.load(f)


def fetch_rows():
    rows = sheet.get_all_records()
    return rows

def workflow(row):
    matches = get_companies_info(row)
    filtered = [m for m in matches if m["website"]]
    if bconfig["distance_sensitive"]:
        filtered = [m for m in filtered if m["location"]["lat"] is not None
                                        and m["location"]["lng"] is not None]
        b_lat, b_lon = bconfig["lat"], bconfig["lon"]
        result = []
        for l in filtered:
            l_lat, l_lon = l["location"]["lat"], l["location"]["lng"]
            l["dist_from_client_km"] = haversine(b_lat, b_lon, l_lat, l_lon)
            if l["dist_from_client_km"] <= bconfig["max_distance_km"]
                result.append(l) 
        filtered = result

    db_errors = 0
    other_errors = 0
    for l in filtered:
        try:
            id = upsert_initial_candidates(l)
        except Error as e:
            print("Database Error")
            db_errors +=1
        except Exception as e:
            print("Other Error")
            other_errors+=1
    print(db_errors)
    print(other_errors)
    if (db_errors == 0 and other_errors == 0):
        print("write initial candidates to db succeed")

    if bconfig["target_partner_type"] == "luxury hotel":
        # pass in section want to scrape (always contain about page) from most important to least
        section_to_scrape = bconfig["sections_to_scrape"]
        



def monitor():

    while True:
        rows = fetch_rows()
        for i, row in enumerate(rows):

            status = row.get(TARGET_COLUMN)
            if status == "Run!":
                print(f"Run for row {i}")
                matches = get_companies_info(row)
                qualified_leads, qualified_summaries = filter_matches(matches)
                email_objects = compose_email(qualified_leads, qualified_summaries)

                sheet.update_cell(i+2, 4, "Done")


        time.sleep(60)  

if __name__ == "__main__":
    monitor()