MAX_SEARCH_CALLS = 4
TAVILY_MAX_RESULTS = 10
MAX_RESULTS_PER_SEARCH = 5
MAX_URL_SELECTOR_EXTRACTS = 2
# Soft cap on document content chars per extract LLM call. A single oversized
# page (full extract) still gets its own batch rather than being truncated.
MAX_EXTRACT_BATCH_CHARS = 12_000
# Soft cap when persisting UrlSelectorDecision candidates for eval. The selector
# LLM still sees all candidates in one call; storage only is split.
MAX_URL_SELECTOR_STORE_CHARS = 12_000
MAX_RFP_TAVILY_CALLS = 6
TAVILY_RFP_TOOLS = frozenset({"tavily_search", "tavily_extract", "tavily_crawl"})
MAX_RESEARCH_CONCURRENCY = 5
# Google Maps / Apify scrape: retries for transient failures only (5xx, 429, timeouts).
GMAP_SCRAPE_MAX_ATTEMPTS = 3
GMAP_SCRAPE_BACKOFF_SECONDS = 2.0
