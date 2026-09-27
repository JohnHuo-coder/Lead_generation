"""Build query-generator eval + prompt-revision packs from a saved v6 batch.

A sample is one research_search call. The signal for prompt work is not
"did this query hit a gold URL" — it is what the query actually retrieved:

  effective   — this query produced verified claims (the pages had the facts)
  ineffective — this query kept 0 pages (nothing on-target reached extraction)
  uncertain   — pages were kept but no claim came out (query vs extractor unclear)

`data/gold_set.json` is optional scoring metadata, not the training label.
Hand-labeled traces live in `data/query_examples_human.json` and are merged
into the revision pack on every rebuild.

Writes:
  data/query_eval_v6.json            full samples
  data/query_eval_v6.jsonl           one sample per line
  data/query_revision_pack_v6.json   train-only contrastive pack for prompt revision

Usage (from repo root):
    .venv\\Scripts\\python.exe scripts\\build_query_eval.py
"""
from __future__ import annotations

import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from prompts.system_prompts import QUERY_GENERATOR_SYSTEM_PROMPT
from services.search_evidence_extractor import document_mentions_company

RAW_PATH = ROOT / "data" / "v6_raw_states.json"
GOLD_PATH = ROOT / "data" / "gold_set.json"
HUMAN_EXAMPLES_PATH = ROOT / "data" / "query_examples_human.json"
OUT_JSON = ROOT / "data" / "query_eval_v6.json"
OUT_JSONL = ROOT / "data" / "query_eval_v6.jsonl"
OUT_PACK = ROOT / "data" / "query_revision_pack_v6.json"

REQUIREMENT_NOT_MET = {
    "Citrus Sukhumvit 11 by Compass Hospitality",
    "Easy Planet Bangkok Asok",
    "Kingston Suites Bangkok Sukhumvit 15 by Kingston Hotels",
    "Citin Sukhumvit 11 Nana Bangkok by Compass Hospitality",
    "Courtyard by Marriott Bangkok Sukhumvit 20",
    "The Mandison Bangkok",
    "FuramaXclusive Asoke",
    "Staybridge Suites Bangkok Thonglor by IHG",
}

DROP_QUERY_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_term",
    "aid",
    "label",
}
AGGREGATOR_MARKERS = (
    "bookstaygo",
    "bangkokhotel24",
    "unionspace",
    "h-rez",
    "travelmyth",
    "hotelscombined",
    "trivago",
    "booking.com",
    "agoda",
    "expedia",
    "hotels.com",
)
SPLIT_SEED = 42
DEV_FRACTION = 0.30


def normalize_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    host = parsed.netloc.casefold()
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path.rstrip("/") or "/"
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.casefold() not in DROP_QUERY_KEYS
    ]
    return urlunparse(
        (parsed.scheme.casefold() or "https", host, path.casefold(), "", urlencode(query), "")
    )


def url_host(url: str) -> str:
    host = urlparse(url or "").netloc.casefold()
    return host.removeprefix("www.")


def unique_in_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def extract_site_domain(query: str) -> str | None:
    match = re.search(r"site:([^\s]+)", query or "", re.I)
    if not match:
        return None
    return match.group(1).rstrip("/").casefold().removeprefix("www.")


def site_matches_host(site: str, host: str) -> bool:
    if not site or not host:
        return False
    return site == host or host.endswith("." + site) or site.endswith("." + host) or site in host or host in site


def merge_call_order(doc_queries: list[str], rejection_queries: list[str]) -> tuple[list[str], bool]:
    doc = unique_in_order(doc_queries)
    rejected = unique_in_order(rejection_queries)
    merged: list[str] = []
    i = j = 0
    ambiguous = False

    while i < len(doc) or j < len(rejected):
        if i < len(doc) and j < len(rejected) and doc[i] == rejected[j]:
            merged.append(doc[i])
            i += 1
            j += 1
            continue

        doc_later = set(doc[i:])
        rej_later = set(rejected[j:])

        if i < len(doc) and doc[i] not in rej_later:
            merged.append(doc[i])
            i += 1
            continue
        if j < len(rejected) and rejected[j] not in doc_later:
            merged.append(rejected[j])
            j += 1
            continue

        ambiguous = True
        if j < len(rejected):
            merged.append(rejected[j])
            j += 1
        else:
            merged.append(doc[i])
            i += 1

    return unique_in_order(merged), ambiguous


def rejection_would_pass(company: str, rejection: dict) -> bool:
    document = {
        "query": rejection.get("query") or "",
        "search_focus": rejection.get("search_focus") or "",
        "title": rejection.get("title") or "",
        "url": rejection.get("url") or "",
        "content": "",
    }
    return document_mentions_company(document, company)


def load_human_gold() -> dict[str, list[str]]:
    if not GOLD_PATH.exists():
        return {}
    raw = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    return {
        company: unique_in_order([url for url in urls if url])
        for company, urls in raw.items()
    }


def load_human_examples() -> list[dict]:
    if not HUMAN_EXAMPLES_PATH.exists():
        return []
    raw = json.loads(HUMAN_EXAMPLES_PATH.read_text(encoding="utf-8"))
    return list(raw.get("examples") or [])


def collect_verified_urls(state: dict) -> list[str]:
    return unique_in_order(
        item["url"]
        for item in state.get("verified_evidence") or []
        if item.get("url")
    )


def build_calls(state: dict) -> tuple[list[dict], bool]:
    documents = state.get("search_documents") or {}
    rejections = state.get("off_target_rejections") or []
    verified = state.get("verified_evidence") or []

    docs_by_query: dict[str, list[dict]] = defaultdict(list)
    query_focus: dict[str, str] = {}
    doc_query_order: list[str] = []
    for result_id, document in documents.items():
        query = document["query"]
        query_focus[query] = document.get("search_focus") or ""
        doc_query_order.append(query)
        docs_by_query[query].append({"result_id": result_id, **document})

    rejections_by_query: dict[str, list[dict]] = defaultdict(list)
    rejection_query_order: list[str] = []
    for rejection in rejections:
        query = rejection["query"]
        query_focus.setdefault(query, rejection.get("search_focus") or "")
        rejection_query_order.append(query)
        rejections_by_query[query].append(rejection)

    evidence_by_result_id: dict[str, list[dict]] = defaultdict(list)
    for item in verified:
        evidence_by_result_id[item.get("result_id") or ""].append(item)

    query_order, ambiguous = merge_call_order(doc_query_order, rejection_query_order)

    calls: list[dict] = []
    for query in query_order:
        kept = docs_by_query.get(query, [])
        produced = []
        for document in kept:
            produced.extend(evidence_by_result_id.get(document["result_id"], []))
        calls.append(
            {
                "query": query,
                "search_focus": query_focus.get(query, ""),
                "kept": kept,
                "rejected": rejections_by_query.get(query, []),
                "verified_this_call": produced,
            }
        )
    return calls, ambiguous


def diagnose_query(
    *,
    query: str,
    prior_queries: list[str],
    prior_source_urls: list[str],
    n_kept: int,
    n_rejected: int,
    n_evidence: int,
) -> dict:
    site = extract_site_domain(query)
    prior_sites = [extract_site_domain(item) for item in prior_queries]
    prior_hosts = [url_host(url) for url in prior_source_urls]

    if n_evidence:
        if site:
            mode = "site_on_official"
            note = f"site:{site} still retrieved pages that produced claims."
        else:
            mode = "open_web"
            note = "Open keyword query (no site:) retrieved pages that produced claims."
        return {"outcome": "effective", "mode": mode, "note": note, "site_domain": site}

    if n_kept > 0:
        return {
            "outcome": "uncertain",
            "mode": "kept_no_claim",
            "note": "On-target pages were kept but no verified claim was extracted.",
            "site_domain": site,
        }

    if site and any(marker in site for marker in AGGREGATOR_MARKERS):
        return {
            "outcome": "ineffective",
            "mode": "site_on_aggregator",
            "note": f"site:{site} is an aggregator/OTA, not the property's own domain.",
            "site_domain": site,
        }

    locked_to_prior_site = bool(site) and any(
        prior and site_matches_host(site, prior) for prior in prior_sites if prior
    )
    locked_to_prior_host = bool(site) and any(
        site_matches_host(site, host) for host in prior_hosts if host
    )
    if site and (locked_to_prior_site or locked_to_prior_host):
        return {
            "outcome": "ineffective",
            "mode": "site_lockin",
            "note": (
                f"Follow-up locked to site:{site} after an earlier search already "
                "used that domain or retrieved pages from it; kept 0."
            ),
            "site_domain": site,
        }

    if site:
        return {
            "outcome": "ineffective",
            "mode": "site_zero_recall",
            "note": f"site:{site} returned no on-target page.",
            "site_domain": site,
        }

    if n_rejected >= 8:
        return {
            "outcome": "ineffective",
            "mode": "all_off_target",
            "note": "No site: restriction, but every result was off-target.",
            "site_domain": None,
        }

    return {
        "outcome": "ineffective",
        "mode": "empty_keep",
        "note": "Search kept 0 on-target pages.",
        "site_domain": None,
    }


_EXISTENCE_HINTS = (
    "meeting",
    "event space",
    "event venue",
    "ballroom",
    "mice",
    "function room",
    "private",
)
_CAPACITY_HINTS = (
    "capacity",
    "pax",
    "seat",
    "sqm",
    "square",
    "headcount",
    "20-60",
    "20 - 60",
    "floor plan",
    "seating",
    "size",
)
_CATERING_HINTS = ("cater", "banquet", "f&b", "dining", "menu", "food")
_CONFIRM_HINTS = (
    "confirm",
    "verify",
    "clarif",
    "accurate",
    "exact",
    "precise",
    "combined",
    "larger space",
    "already verified",
    "documentation that shows",
    "whether that",
)
_UNUSABLE_FOCUS_HINTS = (
    "finalize",
    "finalizing",
    "finalising",
    "final evaluation",
    "final check",
    "no new evidence",
)


def classify_search_focus(focus: str, *, call_index: int) -> dict:
    """A query-generator example is only usable when search_focus names a
    clear retrieval job: the whole requirement, or one/two of its dimensions.
    Confirm-the-last-room / finalize foci belong to the planner, not this model."""
    text = (focus or "").casefold().strip()
    if not text or any(hint in text for hint in _UNUSABLE_FOCUS_HINTS):
        return {
            "kind": "unusable",
            "dimensions": [],
            "usable_for_query_prompt": False,
            "reason": "Focus is empty or a finalize/no-new-evidence instruction.",
        }

    dimensions = []
    if any(hint in text for hint in _EXISTENCE_HINTS):
        dimensions.append("existence")
    if any(hint in text for hint in _CAPACITY_HINTS):
        dimensions.append("capacity")
    if any(hint in text for hint in _CATERING_HINTS):
        dimensions.append("catering")

    if any(hint in text for hint in _CONFIRM_HINTS) and call_index > 0:
        return {
            "kind": "confirm_refine",
            "dimensions": dimensions,
            "usable_for_query_prompt": False,
            "reason": (
                "Focus is confirming or tightening a previous hit "
                "(named room, combined capacity, official documentation) "
                "instead of stating a clean dimension."
            ),
        }

    if len(dimensions) >= 3:
        return {
            "kind": "whole_requirement",
            "dimensions": dimensions,
            "usable_for_query_prompt": True,
            "reason": "Asks for meeting/event space, capacity, and catering together.",
        }
    if len(dimensions) == 2:
        return {
            "kind": "two_dimension",
            "dimensions": dimensions,
            "usable_for_query_prompt": True,
            "reason": f"Asks for {' + '.join(dimensions)}.",
        }
    if len(dimensions) == 1:
        return {
            "kind": "one_dimension",
            "dimensions": dimensions,
            "usable_for_query_prompt": True,
            "reason": f"Asks only for {dimensions[0]}.",
        }
    return {
        "kind": "unusable",
        "dimensions": [],
        "usable_for_query_prompt": False,
        "reason": "Focus does not name a meeting, capacity, or catering job.",
    }


def assign_splits(companies: list[str]) -> dict[str, str]:
    rng = random.Random(SPLIT_SEED)
    names = sorted(companies)
    rng.shuffle(names)
    dev_count = max(1, round(len(names) * DEV_FRACTION))
    dev = set(names[:dev_count])
    return {name: ("dev" if name in dev else "train") for name in names}


def compact_page(item: dict, *, include_claims: bool) -> dict:
    page = {"url": item["url"], "title": item.get("title") or ""}
    if include_claims:
        page["claims"] = list(item.get("claims") or [])
    if item.get("missing_tokens"):
        page["missing_tokens"] = item["missing_tokens"]
    return page


def build_revision_pack(samples: list[dict], requirement: str) -> dict:
    train = [sample for sample in samples if sample["split"] == "train"]
    effective = [sample for sample in train if sample["outcome"]["label"] == "effective"]
    ineffective = [sample for sample in train if sample["outcome"]["label"] == "ineffective"]

    by_company: dict[str, list[dict]] = defaultdict(list)
    for sample in train:
        by_company[sample["company"]].append(sample)

    contrasts = []
    for company, group in by_company.items():
        good = [item for item in group if item["outcome"]["label"] == "effective"]
        bad = [item for item in group if item["outcome"]["label"] == "ineffective"]
        if not good or not bad:
            continue
        contrasts.append(
            {
                "company": company,
                "effective": [
                    {
                        "call_index": item["call_index"],
                        "search_focus": item["input"]["search_focus"],
                        "query": item["output"]["query"],
                        "mode": item["outcome"]["mode"],
                        "what_it_found": [
                            compact_page(page, include_claims=True)
                            for page in item["retrieval"]["kept"]
                            if page.get("produced_evidence")
                        ],
                    }
                    for item in good
                ],
                "ineffective": [
                    {
                        "call_index": item["call_index"],
                        "search_focus": item["input"]["search_focus"],
                        "query": item["output"]["query"],
                        "prior_queries": item["input"]["prior_queries"],
                        "mode": item["outcome"]["mode"],
                        "note": item["outcome"]["note"],
                        "n_kept": item["retrieval"]["n_kept"],
                        "n_rejected": item["retrieval"]["n_rejected"],
                        "what_came_back": [
                            compact_page(page, include_claims=False)
                            for page in (item["retrieval"]["rejected"][:6] or item["retrieval"]["kept"][:6])
                        ],
                    }
                    for item in bad
                ],
            }
        )

    mode_counts = Counter(sample["outcome"]["mode"] for sample in ineffective)
    patterns = []
    if mode_counts.get("site_lockin"):
        patterns.append(
            {
                "mode": "site_lockin",
                "count": mode_counts["site_lockin"],
                "implicated_prompt_line": (
                    "if prior queries found an official hotel domain, "
                    "prefer a NEW angle using site:domain"
                ),
                "what_effective_queries_did_instead": (
                    "First-call open keyword queries (company + meeting/capacity/catering, "
                    "no site:) retrieved official pages and MICE directories."
                ),
            }
        )
    if mode_counts.get("site_on_aggregator"):
        patterns.append(
            {
                "mode": "site_on_aggregator",
                "count": mode_counts["site_on_aggregator"],
                "implicated_prompt_line": (
                    "URLs already seen (use to infer official hotel domains for site: searches)"
                ),
                "what_effective_queries_did_instead": (
                    "Used a real brand domain (marriott.com, avanihotels.com, accor.com) "
                    "or skipped site: entirely."
                ),
            }
        )
    if mode_counts.get("all_off_target"):
        patterns.append(
            {
                "mode": "all_off_target",
                "count": mode_counts["all_off_target"],
                "implicated_prompt_line": "ALWAYS include the target company name",
                "what_effective_queries_did_instead": (
                    "Kept the distinctive property tokens in the query; "
                    "did not let soi numbers or parent-brand words dominate."
                ),
            }
        )

    return {
        "purpose": (
            "Train-only contrastive examples for revising QUERY_GENERATOR_SYSTEM_PROMPT. "
            "Do not score a new prompt by gold-URL hit alone: use these examples to see "
            "which query wording retrieved meeting/capacity/catering facts, and which wording "
            "returned nothing on-target."
        ),
        "requirement": requirement,
        "current_prompt": QUERY_GENERATOR_SYSTEM_PROMPT.strip(),
        "held_out_dev_companies": sorted(
            {sample["company"] for sample in samples if sample["split"] == "dev"}
        ),
        "train_counts": {
            "effective": len(effective),
            "ineffective": len(ineffective),
            "uncertain": sum(1 for sample in train if sample["outcome"]["label"] == "uncertain"),
            "contrasts": len(contrasts),
        },
        "failure_mode_counts": dict(mode_counts),
        "observed_patterns": patterns,
        "effective_queries": [
            {
                "sample_id": item["sample_id"],
                "company": item["company"],
                "search_focus": item["input"]["search_focus"],
                "focus": item["focus"],
                "prior_queries": item["input"]["prior_queries"],
                "query": item["output"]["query"],
                "mode": item["outcome"]["mode"],
                "what_it_found": [
                    compact_page(page, include_claims=True)
                    for page in item["retrieval"]["kept"]
                    if page.get("produced_evidence")
                ],
            }
            for item in effective
        ],
        "ineffective_queries": [
            {
                "sample_id": item["sample_id"],
                "company": item["company"],
                "search_focus": item["input"]["search_focus"],
                "focus": item["focus"],
                "prior_queries": item["input"]["prior_queries"],
                "query": item["output"]["query"],
                "mode": item["outcome"]["mode"],
                "note": item["outcome"]["note"],
                "n_kept": item["retrieval"]["n_kept"],
                "n_rejected": item["retrieval"]["n_rejected"],
                "what_came_back": [
                    compact_page(page, include_claims=False)
                    for page in item["retrieval"]["rejected"][:6]
                ],
            }
            for item in ineffective
        ],
        "contrasts": contrasts,
        "clean_training": _clean_training_slice(train),
    }


def _clean_training_slice(train: list[dict]) -> dict:
    """Examples whose search_focus is a clean retrieval job.

    These are the only ones that should drive QUERY_GENERATOR prompt edits.
    Confirm-refine and finalize foci are planner noise."""
    clean = [
        sample
        for sample in train
        if sample["focus"]["usable_for_query_prompt"]
        and sample["outcome"]["label"] in {"effective", "ineffective"}
    ]
    effective = [sample for sample in clean if sample["outcome"]["label"] == "effective"]
    ineffective = [sample for sample in clean if sample["outcome"]["label"] == "ineffective"]

    by_company: dict[str, list[dict]] = defaultdict(list)
    for sample in clean:
        by_company[sample["company"]].append(sample)

    contrasts = []
    for company, group in by_company.items():
        good = [item for item in group if item["outcome"]["label"] == "effective"]
        bad = [item for item in group if item["outcome"]["label"] == "ineffective"]
        if not good or not bad:
            continue
        contrasts.append(
            {
                "company": company,
                "effective": [
                    {
                        "call_index": item["call_index"],
                        "search_focus": item["input"]["search_focus"],
                        "focus": item["focus"],
                        "query": item["output"]["query"],
                        "mode": item["outcome"]["mode"],
                        "what_it_found": [
                            compact_page(page, include_claims=True)
                            for page in item["retrieval"]["kept"]
                            if page.get("produced_evidence")
                        ],
                    }
                    for item in good
                ],
                "ineffective": [
                    {
                        "call_index": item["call_index"],
                        "search_focus": item["input"]["search_focus"],
                        "focus": item["focus"],
                        "query": item["output"]["query"],
                        "prior_queries": item["input"]["prior_queries"],
                        "mode": item["outcome"]["mode"],
                        "note": item["outcome"]["note"],
                        "n_kept": item["retrieval"]["n_kept"],
                        "n_rejected": item["retrieval"]["n_rejected"],
                    }
                    for item in bad
                ],
            }
        )

    return {
        "rule": (
            "Keep a sample only when search_focus is the whole requirement, "
            "or one/two of existence, capacity, catering. Drop confirm-refine "
            "and finalize foci — those are planner inputs, not query-generator jobs."
        ),
        "effective": len(effective),
        "ineffective": len(ineffective),
        "contrast_count": len(contrasts),
        "focus_kind_counts": dict(Counter(sample["focus"]["kind"] for sample in clean)),
        "effective_queries": [
            {
                "sample_id": item["sample_id"],
                "company": item["company"],
                "search_focus": item["input"]["search_focus"],
                "focus": item["focus"],
                "prior_queries": item["input"]["prior_queries"],
                "query": item["output"]["query"],
                "mode": item["outcome"]["mode"],
                "what_it_found": [
                    compact_page(page, include_claims=True)
                    for page in item["retrieval"]["kept"]
                    if page.get("produced_evidence")
                ],
            }
            for item in effective
        ],
        "ineffective_queries": [
            {
                "sample_id": item["sample_id"],
                "company": item["company"],
                "search_focus": item["input"]["search_focus"],
                "focus": item["focus"],
                "prior_queries": item["input"]["prior_queries"],
                "query": item["output"]["query"],
                "mode": item["outcome"]["mode"],
                "note": item["outcome"]["note"],
                "n_kept": item["retrieval"]["n_kept"],
                "n_rejected": item["retrieval"]["n_rejected"],
                "what_came_back": [
                    compact_page(page, include_claims=False)
                    for page in item["retrieval"]["rejected"][:6]
                ],
            }
            for item in ineffective
        ],
        "contrasts": contrasts,
    }


def _human_focus(example: dict) -> dict:
    if example.get("focus"):
        return example["focus"]
    return classify_search_focus(
        example.get("search_focus") or "",
        call_index=len(example.get("prior_queries") or []),
    )


def _human_effective_entry(example: dict) -> dict:
    return {
        "sample_id": example["sample_id"],
        "company": example["company"],
        "search_focus": example.get("search_focus") or "",
        "focus": _human_focus(example),
        "prior_queries": example.get("prior_queries") or [],
        "query": example["query"],
        "mode": example.get("mode") or "human",
        "source": "human",
        "note": example.get("note") or "",
        "what_it_found": example.get("what_it_found") or [],
    }


def _human_ineffective_entry(example: dict) -> dict:
    return {
        "sample_id": example["sample_id"],
        "company": example["company"],
        "search_focus": example.get("search_focus") or "",
        "focus": _human_focus(example),
        "prior_queries": example.get("prior_queries") or [],
        "query": example["query"],
        "mode": example.get("mode") or "human",
        "source": "human",
        "note": example.get("note") or "",
        "n_kept": example.get("n_kept", 0),
        "n_rejected": example.get("n_rejected", 0),
        "what_came_back": example.get("what_came_back") or [],
    }


def _merge_found_pages(existing: list[dict], incoming: list[dict]) -> list[dict]:
    by_url = {page.get("url"): dict(page) for page in existing}
    for page in incoming:
        url = page.get("url")
        if not url:
            continue
        if url not in by_url:
            by_url[url] = dict(page)
            continue
        old_claims = by_url[url].get("claims") or []
        new_claims = page.get("claims") or []
        if len(new_claims) > len(old_claims):
            by_url[url]["claims"] = new_claims
        if page.get("title") and not by_url[url].get("title"):
            by_url[url]["title"] = page["title"]
    return list(by_url.values())


def _enrich_matching_effective(items: list[dict], example: dict) -> bool:
    """If this human query is already in the list, attach the human note and pages.

    Contrast entries are already scoped to one company and may omit the company field.
    """
    for item in items:
        same_company = item.get("company") in {None, example["company"]}
        if same_company and item.get("query") == example["query"]:
            item["human_confirmed"] = True
            item["source"] = "v6+human"
            if example.get("note"):
                item["note"] = example["note"]
            item["what_it_found"] = _merge_found_pages(
                item.get("what_it_found") or [],
                example.get("what_it_found") or [],
            )
            return True
    return False


def merge_human_examples(pack: dict, examples: list[dict], *, dev_companies: set[str]) -> dict:
    """Fold hand-labeled trace examples into the train revision pack."""
    train_examples = [
        example
        for example in examples
        if example.get("split", "train") != "dev"
        and example.get("company") not in dev_companies
    ]
    existing_queries = {
        (item["company"], item["query"])
        for item in pack["effective_queries"] + pack["ineffective_queries"]
    }

    added_effective = 0
    added_ineffective = 0
    confirmed = 0
    for example in train_examples:
        key = (example["company"], example["query"])
        if key in existing_queries:
            if example.get("outcome") == "effective":
                if _enrich_matching_effective(pack["effective_queries"], example):
                    confirmed += 1
                for contrast in pack["contrasts"]:
                    if contrast["company"] == example["company"]:
                        _enrich_matching_effective(contrast["effective"], example)
            continue
        existing_queries.add(key)
        if example.get("outcome") == "effective":
            pack["effective_queries"].append(_human_effective_entry(example))
            added_effective += 1
        elif example.get("outcome") == "ineffective":
            pack["ineffective_queries"].append(_human_ineffective_entry(example))
            added_ineffective += 1

        contrast = next(
            (item for item in pack["contrasts"] if item["company"] == example["company"]),
            None,
        )
        if contrast is None:
            contrast = {"company": example["company"], "effective": [], "ineffective": []}
            pack["contrasts"].append(contrast)
        if example.get("outcome") == "effective":
            contrast["effective"].append(
                {
                    "call_index": None,
                    "search_focus": example.get("search_focus") or "",
                    "query": example["query"],
                    "mode": example.get("mode") or "human",
                    "source": "human",
                    "what_it_found": example.get("what_it_found") or [],
                }
            )
        elif example.get("outcome") == "ineffective":
            contrast["ineffective"].append(
                {
                    "call_index": None,
                    "search_focus": example.get("search_focus") or "",
                    "query": example["query"],
                    "prior_queries": example.get("prior_queries") or [],
                    "mode": example.get("mode") or "human",
                    "source": "human",
                    "note": example.get("note") or "",
                    "n_kept": example.get("n_kept", 0),
                    "n_rejected": example.get("n_rejected", 0),
                    "what_came_back": example.get("what_came_back") or [],
                }
            )

    if any(example.get("mode") == "filetype_pdf" for example in train_examples):
        pack["observed_patterns"].append(
            {
                "mode": "filetype_pdf",
                "count": sum(
                    1
                    for example in train_examples
                    if example.get("mode") == "filetype_pdf"
                    and example.get("outcome") == "effective"
                ),
                "implicated_prompt_line": (
                    "if prior queries used broad OTAs, try official site, PDF, or MICE directory angles"
                ),
                "what_effective_queries_did_instead": (
                    "Added filetype:pdf to the first keyword query and retrieved an official "
                    "fact sheet with room-by-room theatre/classroom/banquet capacities."
                ),
            }
        )

    pack["train_counts"]["effective"] += added_effective
    pack["train_counts"]["ineffective"] += added_ineffective
    pack["train_counts"]["contrasts"] = len(pack["contrasts"])
    pack["train_counts"]["human_effective"] = added_effective
    pack["train_counts"]["human_ineffective"] = added_ineffective
    pack["train_counts"]["human_confirmed"] = confirmed
    pack["human_examples_file"] = str(HUMAN_EXAMPLES_PATH.as_posix())

    clean = pack.get("clean_training")
    if clean:
        for example in train_examples:
            if not _human_focus(example).get("usable_for_query_prompt"):
                continue
            key = (example["company"], example["query"])
            if example.get("outcome") == "effective":
                if _enrich_matching_effective(clean["effective_queries"], example):
                    for contrast in clean.get("contrasts") or []:
                        if contrast["company"] == example["company"]:
                            _enrich_matching_effective(contrast["effective"], example)
                    continue
                if any(
                    item["company"] == key[0] and item["query"] == key[1]
                    for item in clean["effective_queries"]
                ):
                    continue
                clean["effective_queries"].append(_human_effective_entry(example))
                clean["effective"] += 1
                for contrast in clean.get("contrasts") or []:
                    if contrast["company"] == example["company"]:
                        _enrich_matching_effective(contrast["effective"], example)
            elif example.get("outcome") == "ineffective":
                if any(
                    item["company"] == key[0] and item["query"] == key[1]
                    for item in clean["ineffective_queries"]
                ):
                    continue
                clean["ineffective_queries"].append(_human_ineffective_entry(example))
                clean["ineffective"] += 1
    return pack


def main() -> int:
    raw = json.loads(RAW_PATH.read_text(encoding="utf-8"))
    human_gold = load_human_gold()

    company_rows: list[dict] = []
    samples: list[dict] = []
    split_companies: list[str] = []

    for inputs, state in zip(raw["inputs"], raw["results"], strict=True):
        company = inputs["company"]
        if isinstance(state, dict) and state.get("__error__"):
            company_rows.append(
                {
                    "company": company,
                    "error": state["__error__"],
                    "error_message": state.get("message"),
                    "pipeline_sufficient": None,
                    "search_count": 0,
                    "verified_count": 0,
                }
            )
            continue

        calls, ambiguous = build_calls(state)
        verified_urls = collect_verified_urls(state)
        gold_urls = unique_in_order(human_gold.get(company, []) + verified_urls)
        gold_norm = {normalize_url(url) for url in gold_urls}
        gold_sources = {url: "verified_evidence" for url in verified_urls}
        gold_sources.update({url: "human" for url in human_gold.get(company, [])})

        split_companies.append(company)
        company_rows.append(
            {
                "company": company,
                "error": None,
                "pipeline_sufficient": state.get("sufficient"),
                "requirement_not_met": company in REQUIREMENT_NOT_MET,
                "search_count": len(calls),
                "verified_count": len(state.get("verified_evidence") or []),
                "call_order_ambiguous": ambiguous,
                "gold_urls": gold_urls,
                "gold_url_sources": gold_sources,
            }
        )

        prior_queries: list[str] = []
        prior_claims: list[str] = []
        prior_urls: list[str] = []

        for call_index, call in enumerate(calls):
            kept_out = []
            for document in call["kept"]:
                produced = [
                    item
                    for item in call["verified_this_call"]
                    if item.get("result_id") == document["result_id"]
                ]
                kept_out.append(
                    {
                        "url": document["url"],
                        "title": document.get("title") or "",
                        "full_page": bool(document.get("full_page")),
                        "result_id": document["result_id"],
                        "produced_evidence": bool(produced),
                        "claims": [item["claim"] for item in produced],
                    }
                )

            rejected_out = []
            for rejection in call["rejected"]:
                rejected_out.append(
                    {
                        "url": rejection["url"],
                        "title": rejection.get("title") or "",
                        "missing_tokens": rejection.get("missing_tokens") or [],
                        "would_pass_new_filter": rejection_would_pass(company, rejection),
                    }
                )

            n_evidence = sum(1 for item in kept_out if item["produced_evidence"])
            focus_meta = classify_search_focus(call["search_focus"], call_index=call_index)
            diagnosis = diagnose_query(
                query=call["query"],
                prior_queries=prior_queries,
                prior_source_urls=prior_urls,
                n_kept=len(kept_out),
                n_rejected=len(rejected_out),
                n_evidence=n_evidence,
            )

            hit_urls = unique_in_order(
                [
                    item["url"]
                    for item in kept_out + rejected_out
                    if normalize_url(item["url"]) in gold_norm
                ]
            )

            samples.append(
                {
                    "sample_id": f"{company}#{call_index + 1}",
                    "company": company,
                    "call_index": call_index,
                    "requirement_not_met": company in REQUIREMENT_NOT_MET,
                    "pipeline_sufficient": state.get("sufficient"),
                    "input": {
                        "company": company,
                        "requirement": inputs["requirement"],
                        "search_focus": call["search_focus"],
                        "prior_verified_claims": list(prior_claims),
                        "prior_queries": list(prior_queries),
                        "prior_source_urls": list(prior_urls),
                    },
                    "focus": focus_meta,
                    "output": {"query": call["query"]},
                    "retrieval": {
                        "kept": kept_out,
                        "rejected": rejected_out,
                        "n_kept": len(kept_out),
                        "n_rejected": len(rejected_out),
                        "n_evidence": n_evidence,
                        "n_filter_rescued": sum(
                            1 for item in rejected_out if item["would_pass_new_filter"]
                        ),
                    },
                    "outcome": {
                        "label": diagnosis["outcome"],
                        "mode": diagnosis["mode"],
                        "note": diagnosis["note"],
                        "site_domain": diagnosis["site_domain"],
                    },
                    "scoring": {
                        "gold_urls": gold_urls,
                        "target_hit_at_10": bool(hit_urls) if gold_urls else None,
                        "hit_urls": hit_urls,
                    },
                }
            )

            prior_queries.append(call["query"])
            prior_claims.extend(
                item["claim"] for item in call["verified_this_call"] if item.get("claim")
            )
            prior_urls = unique_in_order(
                prior_urls + [document["url"] for document in call["kept"]]
            )

    splits = assign_splits(split_companies)
    for row in company_rows:
        if row.get("error"):
            continue
        row["split"] = splits[row["company"]]
    for sample in samples:
        sample["split"] = splits[sample["company"]]

    requirement = raw["inputs"][0]["requirement"]
    pack = build_revision_pack(samples, requirement)
    pack = merge_human_examples(
        pack,
        load_human_examples(),
        dev_companies=set(pack["held_out_dev_companies"]),
    )

    outcome_counts = Counter(sample["outcome"]["label"] for sample in samples)
    mode_counts = Counter(sample["outcome"]["mode"] for sample in samples)
    split_counts = Counter(sample["split"] for sample in samples)
    focus_kind_counts = Counter(sample["focus"]["kind"] for sample in samples)

    payload = {
        "source_batch": "v6",
        "label_definition": {
            "effective": "This query produced at least one verified claim.",
            "ineffective": "This query kept 0 on-target pages.",
            "uncertain": "Pages were kept but extraction produced no claim.",
        },
        "raw_states": str(RAW_PATH.as_posix()),
        "requirement": requirement,
        "collaboration_intent": raw["inputs"][0]["collaboration_intent"],
        "n_companies": len(company_rows),
        "n_samples": len(samples),
        "outcome_counts": dict(outcome_counts),
        "mode_counts": dict(mode_counts),
        "focus_kind_counts": dict(focus_kind_counts),
        "split_counts": dict(split_counts),
        "companies": company_rows,
        "samples": samples,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with OUT_JSONL.open("w", encoding="utf-8") as handle:
        for sample in samples:
            handle.write(json.dumps(sample, ensure_ascii=False) + "\n")
    OUT_PACK.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"wrote {OUT_JSON}  ({OUT_JSON.stat().st_size:,} bytes)")
    print(f"wrote {OUT_JSONL} ({OUT_JSONL.stat().st_size:,} bytes)")
    print(f"wrote {OUT_PACK} ({OUT_PACK.stat().st_size:,} bytes)")
    print()
    print(f"samples: {len(samples)}   split: {dict(split_counts)}")
    print(f"outcome: {dict(outcome_counts)}")
    print(f"modes:   {dict(mode_counts)}")
    print()
    print("train revision pack:")
    print(f"  effective   {pack['train_counts']['effective']}")
    print(f"  ineffective {pack['train_counts']['ineffective']}")
    print(f"  contrasts   {pack['train_counts']['contrasts']} companies with both")
    print(f"  human added {pack['train_counts'].get('human_effective', 0)} effective / "
          f"{pack['train_counts'].get('human_ineffective', 0)} ineffective / "
          f"{pack['train_counts'].get('human_confirmed', 0)} confirmed existing")
    print(f"  failure modes: {pack['failure_mode_counts']}")
    clean = pack.get("clean_training") or {}
    print()
    print("clean search_focus only (use this for prompt edits):")
    print(f"  effective   {clean.get('effective')}")
    print(f"  ineffective {clean.get('ineffective')}")
    print(f"  contrasts   {clean.get('contrast_count')}")
    print(f"  kinds:      {clean.get('focus_kind_counts')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
