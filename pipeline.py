

import time
import requests
import gspread
from oauth2client.service_account import ServiceAccountCredentials

from gmap_scraper import get_companies_info
from web_scraper import scrape_hotel_website_summary
from fit_scoring import filter_matches
from email_composer import compose_email

SHEET_NAME = "lead_gen"
TARGET_COLUMN = "Status"
WEBHOOK_URL = ""
COL = "Status"

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

creds = ServiceAccountCredentials.from_json_keyfile_name(
    "sheet-monitor-495716-74189a665319.json", scope
)

client = gspread.authorize(creds)
sheet = client.open(SHEET_NAME).sheet1


def fetch_rows():
    rows = sheet.get_all_records()
    return rows

def gmap_scraper(data):

    return 

def monitor():

    while True:
        rows = fetch_rows()
        for i, row in enumerate(rows):

            status = row.get(TARGET_COLUMN)
            if status == "Run!":
                print(f"Run for row {i}")
                matches = get_companies_info(row)
                filtered = filter_matches(matches)
                emails = compose_email(filtered)

                sheet.update_cell(i+2, 4, "Done")


        time.sleep(60)  

if __name__ == "__main__":
    monitor()