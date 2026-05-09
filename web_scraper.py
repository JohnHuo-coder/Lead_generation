import re
from collections import Counter, deque
from datetime import datetime
from typing import Dict, List, Set, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

MAX_PAGES = 12
REQUEST_TIMEOUT = 15

EVENT_KEYWORDS = (
    "event",
    "events",
    "wedding",
    "meeting",
    "conference",
    "banquet",
    "celebration",
    "festive",
    "offer",
    "promotion",
    "special",
    "happening",
)

LUXURY_KEYWORDS = (
    "luxury",
    "5-star",
    "five star",
    "premium",
    "exclusive",
    "fine dining",
    "spa",
    "suite",
    "concierge",
    "resort",
    "private beach",
    "michelin",
)

BUDGET_KEYWORDS = (
    "budget",
    "affordable",
    "economy",
    "value",
    "low cost",
    "hostel",
    "basic",
    "best price",
    "discount",
    "deal",
)

CUSTOMER_SEGMENTS = {
    "business travelers": (
        "business",
        "corporate",
        "meeting room",
        "conference",
        "work desk",
        "airport shuttle",
    ),
    "families": (
        "family",
        "kids",
        "children",
        "family room",
        "play area",
        "child-friendly",
    ),
    "couples": (
        "romantic",
        "honeymoon",
        "couple",
        "anniversary",
        "wedding",
    ),
    "luxury leisure travelers": (
        "spa",
        "resort",
        "wellness",
        "fine dining",
        "luxury",
        "private",
    ),
    "budget-conscious travelers": (
        "budget",
        "affordable",
        "value",
        "deal",
        "discount",
        "economy",
    ),
}

DATE_PATTERNS = (
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s,.-]+\d{1,2}(?:[\s,.-]+\d{4})?\b",
    r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b",
    r"\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b",
)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _is_same_domain(base_url: str, candidate_url: str) -> bool:
    return urlparse(base_url).netloc == urlparse(candidate_url).netloc


def _extract_internal_links(base_url: str, soup: BeautifulSoup) -> Set[str]:
    links: Set[str] = set()
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"].strip()
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        absolute = urljoin(base_url, href)
        if _is_same_domain(base_url, absolute):
            links.add(absolute.split("#")[0])
    return links


def _fetch_page(url: str) -> Tuple[str, BeautifulSoup]:
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    return response.text, soup


def _pick_next_links(links: Set[str]) -> List[str]:
    scored = []
    for link in links:
        lower_link = link.lower()
        score = 0
        if any(keyword in lower_link for keyword in EVENT_KEYWORDS):
            score += 4
        if any(token in lower_link for token in ("about", "stay", "rooms", "offers", "dining")):
            score += 2
        scored.append((score, link))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [link for _, link in scored]

def _clean_content_without_a(soup):
    for tag in soup.select(
        "script, style, noscript, svg, iframe, "
        "header, nav, footer, aside, "
        "[role='navigation'], [role='contentinfo']"
    ):
        tag.decompose()
    
    # delete common cookie/banner popup（based on class/id keyword）
    noisy_keywords = ("cookie", "consent", "banner", "popup", "modal", "subscribe")
    to_remove = []
    for tag in soup.find_all(True):
        joined = " ".join(tag.get("class", [])) + " " + (tag.get("id") or "")
        low = joined.lower()
        if any(k in low for k in noisy_keywords):
            to_remove.append(tag)
    for tag in to_remove:
        tag.decompose()

    text = soup.get_text(" ", strip=True)
    text = _normalize_text(text)
    return text


def _collect_site_content(base_url: str, max_pages: int = MAX_PAGES) -> Dict[str, str]:
    queue = deque([base_url])
    visited: Set[str] = set()
    visited.add(base_url)
    succeeded = set()
    pages: Dict[str, str] = {}

    while queue and len(succeeded) < max_pages:
        current = queue.popleft()
        try:
            _, soup = _fetch_page(current)
            succeeded.add(current)
        except requests.RequestException:
            print("request failed")
            continue
        text = _clean_content_without_a(soup) # get all text within tags for this page
        pages[current] = text[:40000]
        links = _extract_internal_links(base_url, soup)
        ranked =  _pick_next_links(links)
        for link in ranked:
            if link not in visited and len(queue) < max_pages * 2:
                visited.add(link)
                queue.append(link)
    return pages


def _extract_recent_events(pages: Dict[str, str], top_n: int = 5) -> List[Dict[str, str]]:
    now = datetime.now()
    found_events: List[Dict[str, str]] = []
    event_trigger = re.compile("|".join(EVENT_KEYWORDS), re.IGNORECASE)

    for url, text in pages.items():
        if not event_trigger.search(text):
            continue
        snippets = re.split(r"(?<=[.!?])\s+", text)
        for snippet in snippets:
            if not event_trigger.search(snippet):
                continue
            matched_date = ""
            for pattern in DATE_PATTERNS:
                date_match = re.search(pattern, snippet, re.IGNORECASE)
                if date_match:
                    matched_date = date_match.group(0)
                    break
            if matched_date:
                # Keep only events likely from current or previous year.
                year_match = re.search(r"\b(20\d{2})\b", matched_date)
                if year_match:
                    year_val = int(year_match.group(1))
                    if year_val < now.year - 1:
                        continue
            found_events.append(
                {
                    "source_url": url,
                    "date_hint": matched_date,
                    "event_summary": snippet[:260],
                }
            )

    # Deduplicate by summary text.
    dedup = []
    seen = set()
    for event in found_events:
        key = event["event_summary"].lower()
        if key not in seen:
            seen.add(key)
            dedup.append(event)
    return dedup[:top_n]


def _classify_hotel_style(combined_text: str) -> Dict[str, object]:
    lower_text = combined_text.lower()
    luxury_hits = sum(1 for keyword in LUXURY_KEYWORDS if keyword in lower_text)
    budget_hits = sum(1 for keyword in BUDGET_KEYWORDS if keyword in lower_text)

    if luxury_hits >= budget_hits + 2:
        label = "luxury"
        confidence = min(1.0, 0.45 + luxury_hits * 0.08)
    elif budget_hits >= luxury_hits + 2:
        label = "economy"
        confidence = min(1.0, 0.45 + budget_hits * 0.08)
    else:
        label = "midscale / mixed"
        confidence = 0.5

    evidence = [
        keyword
        for keyword in (LUXURY_KEYWORDS + BUDGET_KEYWORDS)
        if keyword in lower_text
    ][:10]
    return {
        "label": label,
        "confidence": round(confidence, 2),
        "evidence_keywords": evidence,
        "score": {
            "luxury_hits": luxury_hits,
            "economy_hits": budget_hits,
        },
    }


def _infer_customer_segments(combined_text: str, top_n: int = 3) -> List[Dict[str, object]]:
    lower_text = combined_text.lower()
    segment_scores = Counter()
    segment_evidence: Dict[str, List[str]] = {}

    for segment, keywords in CUSTOMER_SEGMENTS.items():
        matches = [keyword for keyword in keywords if keyword in lower_text]
        if matches:
            segment_scores[segment] = len(matches)
            segment_evidence[segment] = matches

    results = []
    for segment, score in segment_scores.most_common(top_n):
        confidence = min(1.0, 0.35 + score * 0.15)
        results.append(
            {
                "segment": segment,
                "confidence": round(confidence, 2),
                "evidence_keywords": segment_evidence.get(segment, [])[:6],
            }
        )
    return results


def scrape_hotel_website_summary(
    website_url: str,
    max_pages: int = MAX_PAGES, 
    recent_events: int = 5
) -> Dict[str, object]:
    """
    Generic hotel website summarizer.
    Returns:
    - recent_events: recent event snippets if found
    - hotel_style: economy / luxury / mixed classification
    - target_customer_segments: inferred audience segments
    - high_level_summary: concise plain-language summary
    """
    if not website_url.startswith(("http://", "https://")):
        website_url = f"https://{website_url}"

    pages = _collect_site_content(website_url, max_pages=max_pages)
    if not pages:
        return {
            "website_url": website_url,
            "status": "failed",
            "error": "Could not fetch website pages.",
            "recent_events": [],
            "hotel_style": {},
            "target_customer_segments": [],
            "high_level_summary": "",
        }

    combined_text = "\n\n".join(pages.values())
    events = _extract_recent_events(pages, recent_events)
    style = _classify_hotel_style(combined_text)
    segments = _infer_customer_segments(combined_text)

    summary_parts = [
        f"Analyzed {len(pages)} page(s).",
        f"Hotel style is likely {style.get('label', 'unknown')}.",
    ]
    if events:
        summary_parts.append(f"Found {len(events)} likely recent event mention(s).")
    else:
        summary_parts.append("No clear recent event mention found.")
    if segments:
        primary = ", ".join(seg["segment"] for seg in segments)
        summary_parts.append(f"Likely target segments: {primary}.")

    return {
        "full_content": combined_text,
        "website_url": website_url,
        "status": "ok",
        "pages_scanned": len(pages),
        "recent_events": events,
        "hotel_style": style,
        "target_customer_segments": segments,
        "high_level_summary": " ".join(summary_parts),
    }