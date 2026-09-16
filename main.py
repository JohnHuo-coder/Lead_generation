from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Any
import os
from urllib.parse import urlparse, unquote

import sys
from pathlib import Path
from web_scraper import scrape_hotel_website_summary
import json

ROOT = Path(__file__).resolve().parent

app = FastAPI(title="hotel_web_sraper")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class QueryBody(BaseModel):
    webUrl: str
    maxPage: int

@app.post("/api/scrape")
def run_query(body: QueryBody):
    try:
        result = scrape_hotel_website_summary(body.webUrl, body.maxPage)
        return result
    except Exception as e:
        return {
            "website_url": body.webUrl,
            "status": "failed",
            "error": f"Internal Server Error: {e}",
            "about": "",
            "events_meetings": "",
            "promotion_news": "",
            "facility_amenity": "",
            "dining": ""
        }

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}