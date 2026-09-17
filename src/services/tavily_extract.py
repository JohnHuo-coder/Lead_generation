from tavily import TavilyClient

tavily_client = TavilyClient()


def extract_page_content(url: str) -> str:
    response = tavily_client.extract(
        urls=[url],
        extract_depth="advanced",
        format="text",
    )
    results = response.get("results") or []
    if results:
        return results[0]["raw_content"]

    failed_results = response.get("failed_results") or []
    if failed_results:
        error = failed_results[0].get("error", "unknown extract error")
        raise RuntimeError(f"Tavily extract failed for {url}: {error}")

    raise RuntimeError(f"Tavily extract returned no content for {url}")
