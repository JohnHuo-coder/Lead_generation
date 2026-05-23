import re
from collections import Counter, deque
from datetime import datetime
from typing import Dict, List, Set, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, NavigableString, Tag, Comment, Doctype, ProcessingInstruction, Declaration
from collections import defaultdict

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

MAX_PAGES = 30
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
    "news",
    "special",
    "happening",
)

AMENITY_KEYWORDS = (
    "facility", 
    "facilities", 
    "amenities", 
    "amenity", 
    "services",
    "dining"
)



def normalize_keep_newlines(text: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(lines)


def _is_same_domain(base_url: str, candidate_url: str) -> bool:
    return urlparse(base_url).netloc == urlparse(candidate_url).netloc


def _extract_internal_links(base_url: str, soup: BeautifulSoup) -> Set[str]:
    links: Set[str] = set()
    link_to_name = {}
    for a_tag in soup.find_all("a", href=True):
        link_name = a_tag.get_text(" ", strip = True)
        href = a_tag["href"].strip()
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        absolute = urljoin(base_url, href)
        if _is_same_domain(base_url, absolute):
            link = absolute.split("#")[0]
            links.add(link)
            link_to_name[link] = link_name
    return links, link_to_name


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
        if any(keyword in lower_link for keyword in AMENITY_KEYWORDS):
            score += 2
        scored.append((score, link))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [link for _, link in scored]

def render_table(table: Tag) -> str:
    rows = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["th", "td"], recursive=False)
        values = [c.get_text(" ", strip=True) for c in cells if c.get_text(" ", strip=True)]

        if not values:
            continue

        if len(values) >= 2:
            rows.append(f"{values[0]}: {' | '.join(values[1:])}")
        else:
            rows.append(values[0])

    return "\n".join(rows)


def render_list(lst: Tag) -> str:
    items = []
    for li in lst.find_all("li", recursive = False):
        txt = render_inline(li)
        if txt:
            items.append(f"- {txt}")
    return "\n".join(items)



BLOCK_TAGS = {"p", "div", "section", "article", "h1", "h2", "h3", "h4"}
INLINE_TAGS = {"a", "span", "strong", "b", "em", "i", "u", "small", "code"}
LIST_TAGS = {"ul", "ol"}

def norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()

def render_inline(node: Tag, cur: str = "inline") -> str:
    """Render one block's internal text; inline tags do not force new lines."""
    parts: List[Tuple[str, str]] = []
    for child in node.children:
        if isinstance(child, (Comment, Doctype, ProcessingInstruction, Declaration)):
            continue
        elif isinstance(child, NavigableString):
            text = norm_ws(str(child))
            if text:
                parts.append((text, "inline"))
        elif isinstance(child, Tag):
            name = child.name.lower()
            if name in {"br"}:
                parts.append(("\n", "break"))
            elif name == "table":
                text = render_table(child)
                if text.strip():
                    parts.append((text, "block"))
            elif name in LIST_TAGS:
                text = render_list(child)
                if text:
                    parts.append((text, "block"))
            elif name in INLINE_TAGS:
                text = render_inline(child, "inline")
                if text:
                    parts.append((text, "inline"))
            elif name in BLOCK_TAGS:
                text = render_inline(child, "block")
                if text:
                    parts.append((text, "block"))
            else:
                text = render_inline(child, "inline")
                if text:
                    parts.append((text, "inline"))

    out_parts: List[str] = []
    prev_kind = "block" if cur == "block" else None

    for text, kind in parts:
        if kind == "break":
            if out_parts and not out_parts[-1].endswith("\n"):
                out_parts.append("\n")
            prev_kind = "break"
            continue

        if not out_parts:
            out_parts.append(text)
        else:
            if prev_kind == "block" or kind == "block":
                sep = "\n"
            else:
                sep = " "
            if out_parts[-1].endswith("\n"):
                sep = ""
            out_parts.append(sep + text)
        prev_kind = kind

    joined = "".join(out_parts)
    joined = re.sub(r"[ \t]+\n", "\n", joined)
    joined = re.sub(r"\n[ \t]+", "\n", joined)
    joined = re.sub(r"\n{3,}", "\n\n", joined)
    joined = re.sub(r" {2,}", " ", joined)
    return joined.strip()

def smart_render(root: Tag) -> str:
    chunks = []

    for el in root.find_all(BLOCK_TAGS | LIST_TAGS | {"table"}, recursive=False):
        name = el.name.lower()

        if name in LIST_TAGS:
            items = []
            for li in el.find_all("li", recursive = False):
                txt = render_inline(li)
                if txt:
                    items.append(f"- {txt}")
            if items:
                chunks.append("\n".join(items))

        elif name == "table":
            txt = render_table(el)
            if txt:
                chunks.append(txt)

        elif name in BLOCK_TAGS:
            txt = render_inline(el)
            if txt: 
                chunks.append(txt)
    
    out = "\n\n".join(chunks)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out

def _clean_content(soup):
    for tag in soup.select(
        "script, style, noscript, svg, iframe, "
        "header, nav, footer, aside, "
        "[role='navigation'], [role='contentinfo']"
    ):
        tag.decompose()

    # remove booking availability form and sales link sections
    for tag in soup.select("form[name='availabilitysearchform']"):
        tag.decompose()
    for tag in soup.select("section[id*='sale' i]"):
        tag.decompose()

    # remove common reservation widgets and chat launchers
    for tag in soup.select(
        "[id*='booking' i], [class*='booking' i], "
        "[id*='reservation' i], [class*='reservation' i], "
        "[id*='availability' i], [class*='availability' i], "
        "[id*='chat' i], [class*='chat' i], "
        "[id*='contact' i], [class*='contact' i], "
        "[id*='enquiry' i], [class*='enquiry' i], [name*='enquiry' i], "
        "[id*='search' i], [class*='search' i], [name*='search' i]"
    ):
        tag.decompose()
    
    # remove language menu and currency menu
    for tag in soup.select(
        "li[class*='language' i], ul[class*='language' i], "
        "li[class*='currencies' i], ul[class*='currencies' i], "
        "li[class*='currency' i], ul[class*='currency' i]"
    ):
        tag.decompose()
    
    # delete common cookie/banner popup（based on class/id keyword）
    noisy_keywords = (
        "cookie",
        "consent",
        "banner",
        "popup",
        "modal",
        "subscribe",
        "newsletter",
        "floating",
        "drawer",
    )
    # tags that are allowed to be removed by keyword rule
    removable_tags = {"div", "section", "aside", "form", "dialog"}
    # never remove these structural roots
    protected_tags = {"html", "body", "main", "article"}

    to_remove = []
    for tag in soup.find_all(True):
        if tag.name in protected_tags or tag.name not in removable_tags:
            continue

        joined = " ".join(tag.get("class", [])) + " " + (tag.get("id") or "")
        low = joined.lower()
        text_len = len(tag.get_text(" ", strip=True))

        # keyword hit + short content => likely popup/widget noise
        if any(k in low for k in noisy_keywords) and text_len < 800:
            to_remove.append(tag)

    for tag in to_remove:
        tag.decompose()

    root = (
        soup.select_one("main, article, [role='main'], #content, .content, .entry-content")
        or soup.body
        or soup
    )
    text = render_inline(root)
    return text


def collect_site_content(base_url: str, max_pages: int = MAX_PAGES):
    queue = deque([base_url])
    link_queue = deque(["home"])
    visited: Set[str] = set()
    visited.add(base_url)
    succeeded = set()
    pages: Dict[str, str] = {}

    # return event_contnt, always check this first, then whole pages for events
    # no link to events or meeting, likely not considered

    key_words = ["event", "meeting", "conference", "venue",
                 "promotion", "news", 
                 "about", 
                 "facility", "facilities", "amenities", "amenity", "services",
                 "dining"]

    classified_results = defaultdict(list)
    seen_by_key = defaultdict(set)

    while queue and len(succeeded) < max_pages:
        current = queue.popleft()
        link_name = link_queue.popleft()
        try:
            _, soup = _fetch_page(current)
            succeeded.add(current)
        except requests.RequestException:
            continue
        
        soup_for_text = BeautifulSoup(str(soup), "html.parser")
        text = _clean_content(soup_for_text) 
        # locate the content if content in class,  
        # check keyword in url

        if text:
            if link_name == "home":
                classified_results["about"].append(text)
            for key in key_words:
                if (key in current or key in link_name.lower()) and text not in seen_by_key[key]:
                    seen_by_key[key].add(text)
                    classified_results[key].append(text)
            pages[current] = text[:40000]
            
        links, link_to_name = _extract_internal_links(base_url, soup)
        ranked =  _pick_next_links(links)
        for link in ranked:
            if link not in visited and len(queue) < max_pages * 2:
                visited.add(link)
                queue.append(link)
                link_name = link_to_name[link]
                link_queue.append(link_name)

    return pages, classified_results




def scrape_hotel_website_summary(
    website_url: str,
    max_pages: int = MAX_PAGES,
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

    pages, classified_results = collect_site_content(website_url, max_pages=max_pages)
    events_meetings = [key.upper() + "\n" + "\n".join(classified_results.get(key, [])) + "\n" for key in ["event", "meeting", "conference", "venue"]]
    promotion_news = [key.upper() + "\n" + "\n".join(classified_results.get(key, [])) + "\n" for key in ["promotion", "news"]]
    facility_amenity = [key.upper() + "\n" + "\n".join(classified_results.get(key, [])) + "\n" for key in ["facility", "facilities", "amenities", "amenity", "dining"]]
    
    events_meetings = "\n\n".join(events_meetings)
    promotion_news = "\n\n".join(promotion_news)
    facility_amenity = "\n\n".join(facility_amenity)
    
    about = "\n".join(classified_results.get("about", []))

    if not pages:
        return {
            "website_url": website_url,
            "status": "failed",
            "error": "Could not fetch website pages.",
            "about": "",
            "events_meetings": "",
            "promotion_news": "",
            "facility_amenity": "",
            "dining": ""
        }

    dedup_contents = list(set(pages.values()))
    combined_text = "\n\n".join(dedup_contents)

    return {
        "full_content": combined_text,
        "website_url": website_url,
        "status": "ok",
        "pages_scanned": len(pages),
        "about": about,
        "events_meetings": events_meetings,
        "promotion_news": promotion_news,
        "facility_amenity": facility_amenity,
    }