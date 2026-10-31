from langchain.tools import tool, ToolRuntime
from tavily import TavilyClient
from langchain.messages import ToolMessage
from langgraph.types import Command

from components.constants import (
    MAX_EXTRACT_BATCH_CHARS,
    MAX_RESULTS_PER_SEARCH,
    MAX_SEARCH_CALLS,
    MAX_URL_SELECTOR_EXTRACTS,
    MAX_URL_SELECTOR_STORE_CHARS,
    TAVILY_MAX_RESULTS,
)
from components.evidence_verification import merge_verification_updates, verify_evidence_item
from components.state import ResearchAgentState
from schemas.research_schemas import (
    EvidenceExtractorDecision,
    ExtractorClaim,
    ExtractorDocument,
    OffTargetRejection,
    QueryGeneratorDecision,
    ResearchAgentStep,
    SearchDocument,
    UrlSelectorChoice,
    UrlSelectorDecision,
    UrlSelectorPage,
)
from services.search_evidence_extractor import (
    document_mentions_company,
    extract_evidence_from_search_batch,
    missing_company_tokens,
)
from services.tavily_extract import extract_page_content
from services.query_generator import generate_search_query
from services.url_selector import filter_valid_selections, select_urls_for_full_extract

tavily_client = TavilyClient()


def _format_tool_message_for_agent(
    *,
    searches_used: int,
    verified_batch: list,
    tavily_hit_count: int = 0,
    eligible_count: int = 0,
    off_target_count: int = 0,
) -> str:
    lines = [f"Searches used: {searches_used} / {MAX_SEARCH_CALLS}", "", "Verified this search:"]

    if verified_batch:
        lines.extend(f"- {item.claim}" for item in verified_batch)
    else:
        lines.append("- none")
        if tavily_hit_count == 0:
            lines.append(
                "Search returned no results. Next search must shorten the "
                "company name or change source (official domain or Cvent)."
            )
        elif eligible_count == 0 and off_target_count:
            lines.append(
                "Results did not mention this property. Shorten the name; "
                "do not treat sibling or neighborhood businesses as this company."
            )
        else:
            lines.append(
                "No verified evidence from this search; try a different "
                "search angle (official meetings/facilities/faqs page)."
            )

    return "\n".join(lines)


def _collect_prior_queries(
    search_queries_used: list[str] | None,
    search_documents: dict[str, SearchDocument],
) -> list[str]:
    prior_queries: list[str] = []
    seen: set[str] = set()
    for query in search_queries_used or []:
        normalized = query.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            prior_queries.append(normalized)
    for document in search_documents.values():
        normalized = document["query"].strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            prior_queries.append(normalized)
    return prior_queries


def _collect_prior_source_urls(search_documents: dict[str, SearchDocument]) -> list[str]:
    return sorted({document["url"] for document in search_documents.values()})


def _build_known_document_indexes(
    prior_search_documents: dict[str, SearchDocument],
) -> tuple[dict[str, str], set[str]]:
    known_documents: dict[str, str] = {}
    full_page_urls: set[str] = set()
    for document in prior_search_documents.values():
        url = document["url"]
        known_documents[url] = document["content"]
        if document.get("full_page"):
            full_page_urls.add(url)
    return known_documents, full_page_urls


def _is_duplicate_document(
    url: str,
    content: str,
    *,
    known_documents: dict[str, str],
    full_page_urls: set[str],
) -> bool:
    if url in full_page_urls:
        return True
    return url in known_documents and known_documents[url] == content


def _document_from_result(item: dict, *, query: str, search_focus: str) -> SearchDocument:
    return {
        "query": query,
        "search_focus": search_focus,
        "title": item["title"],
        "url": item["url"],
        "content": item["content"],
        "full_page": False,
    }


def _filter_eligible_results(
    results: list[dict],
    *,
    query: str,
    search_focus: str,
    company: str,
    known_documents: dict[str, str],
    full_page_urls: set[str],
) -> tuple[list[SearchDocument], int, list[OffTargetRejection]]:
    eligible: list[SearchDocument] = []
    skipped_duplicate_results = 0
    off_target_rejections: list[OffTargetRejection] = []

    for item in results:
        url = item["url"]
        content = item["content"]
        if _is_duplicate_document(
            url,
            content,
            known_documents=known_documents,
            full_page_urls=full_page_urls,
        ):
            skipped_duplicate_results += 1
            continue

        document = _document_from_result(item, query=query, search_focus=search_focus)
        if not document_mentions_company(document, company):
            off_target_rejections.append({
                "query": query,
                "search_focus": search_focus,
                "title": document["title"],
                "url": url,
                "missing_tokens": missing_company_tokens(document, company),
            })
            continue

        eligible.append(document)

    return eligible, skipped_duplicate_results, off_target_rejections


def _url_selector_page(item: dict) -> UrlSelectorPage:
    return UrlSelectorPage(
        title=item.get("title") or "",
        url=item.get("url") or "",
        content=item.get("content") or "",
    )


def _url_selector_decision(
    *,
    search_focus: str,
    search_query: str,
    candidates: list[SearchDocument],
    selections: list[tuple[str, str]],
) -> UrlSelectorDecision:
    return UrlSelectorDecision(
        search_focus=search_focus,
        search_query=search_query,
        candidates=[_url_selector_page(document) for document in candidates],
        selections=[
            UrlSelectorChoice(url=url, reason=reason)
            for url, reason in selections
        ],
    )


def _split_url_selector_decision_for_storage(
    decision: UrlSelectorDecision,
    *,
    max_chars: int = MAX_URL_SELECTOR_STORE_CHARS,
) -> list[UrlSelectorDecision]:
    """Split one selector decision into char-budgeted records for eval storage.

    Does not change selector LLM behavior: candidates were already chosen over
    the full set. Each shard keeps the same search_focus / search_query;
    selections land only in the shard that contains that candidate URL.
    """
    candidates = list(decision.candidates or [])
    if not candidates:
        return [decision]

    selections = list(decision.selections or [])
    batches: list[list[UrlSelectorPage]] = []
    current: list[UrlSelectorPage] = []
    current_chars = 0

    for page in candidates:
        size = len(page.content or "")
        if current and current_chars + size > max_chars:
            batches.append(current)
            current = []
            current_chars = 0
        current.append(page)
        current_chars += size

    if current:
        batches.append(current)

    shards: list[UrlSelectorDecision] = []
    for batch in batches:
        urls = {page.url for page in batch}
        shards.append(
            UrlSelectorDecision(
                search_focus=decision.search_focus,
                search_query=decision.search_query,
                candidates=batch,
                selections=[
                    choice for choice in selections if choice.url in urls
                ],
            )
        )
    return shards


def _apply_url_selector_full_extracts(
    eligible_documents: list[SearchDocument],
    *,
    company: str,
    search_query: str,
    search_focus: str,
    known_documents: dict[str, str],
    full_page_urls: set[str],
    skill_ids: list[str] | None = None,
) -> tuple[list[SearchDocument], int, int, int, UrlSelectorDecision]:
    selector_candidates = [
        document
        for document in eligible_documents
        if document["url"] not in full_page_urls
    ]
    if not selector_candidates:
        return (
            eligible_documents,
            0,
            0,
            0,
            _url_selector_decision(
                search_focus=search_focus,
                search_query=search_query,
                candidates=[],
                selections=[],
            ),
        )

    selection_result = select_urls_for_full_extract(
        company=company,
        search_focus=search_focus,
        candidates=selector_candidates,
        skill_ids=skill_ids,
    )
    allowed_urls = {document["url"] for document in selector_candidates}
    selections = filter_valid_selections(
        selection_result,
        allowed_urls=allowed_urls,
        max_selections=MAX_URL_SELECTOR_EXTRACTS,
    )
    decision = _url_selector_decision(
        search_focus=search_focus,
        search_query=search_query,
        candidates=selector_candidates,
        selections=selections,
    )

    full_content_by_url: dict[str, str] = {}
    extract_attempts = 0
    extract_failures = 0

    for url, _reason in selections:
        extract_attempts += 1
        if url in full_page_urls:
            full_content_by_url[url] = known_documents[url]
            continue
        try:
            full_content_by_url[url] = extract_page_content(url)
        except RuntimeError:
            extract_failures += 1
            continue
        full_page_urls.add(url)
        known_documents[url] = full_content_by_url[url]

    if not full_content_by_url:
        return eligible_documents, extract_attempts, 0, extract_failures, decision

    updated_documents: list[SearchDocument] = []
    for document in eligible_documents:
        url = document["url"]
        if url not in full_content_by_url:
            updated_documents.append(document)
            continue
        updated_documents.append({
            **document,
            "content": full_content_by_url[url],
            "full_page": True,
        })

    successful_extracts = len(full_content_by_url)
    return updated_documents, extract_attempts, successful_extracts, extract_failures, decision


def _prioritize_selected_urls(
    eligible_documents: list[SearchDocument],
    selected_urls: set[str],
) -> list[SearchDocument]:
    if not selected_urls:
        return eligible_documents
    selected = [document for document in eligible_documents if document["url"] in selected_urls]
    others = [document for document in eligible_documents if document["url"] not in selected_urls]
    return [*selected, *others]


def _take_extraction_batch(
    eligible_documents: list[SearchDocument],
    *,
    tool_call_id: str,
) -> dict[str, SearchDocument]:
    """Keep the top-ranked eligible documents and assign result_ids."""
    batch_documents: dict[str, SearchDocument] = {}
    for document in eligible_documents[:MAX_RESULTS_PER_SEARCH]:
        result_id = f"{tool_call_id}_{len(batch_documents)}"
        batch_documents[result_id] = document
    return batch_documents


def _document_content_chars(document: SearchDocument) -> int:
    return len(document.get("content") or "")


def _pack_extract_batches(
    batch_documents: dict[str, SearchDocument],
    *,
    max_chars: int = MAX_EXTRACT_BATCH_CHARS,
) -> list[dict[str, SearchDocument]]:
    """Split ordered docs into micro-batches under a content-char budget.

    Keeps document order. Starts a new batch when adding the next doc would
    exceed ``max_chars``. A single doc larger than the budget still forms its
    own batch (no truncation).
    """
    if not batch_documents:
        return []

    batches: list[dict[str, SearchDocument]] = []
    current: dict[str, SearchDocument] = {}
    current_chars = 0

    for result_id, document in batch_documents.items():
        size = _document_content_chars(document)
        if current and current_chars + size > max_chars:
            batches.append(current)
            current = {}
            current_chars = 0
        current[result_id] = document
        current_chars += size

    if current:
        batches.append(current)
    return batches


def _merge_verification_dicts(target: dict, source: dict) -> None:
    for key in (
        "verified_evidence",
        "failed_evidence_checks",
        "verifier_judgments",
        "unclear_ownership_judgments",
    ):
        values = source.get(key) or []
        if values:
            target.setdefault(key, []).extend(values)
    extracts = source.get("evidence_full_page_extracts")
    if extracts:
        target["evidence_full_page_extracts"] = (
            target.get("evidence_full_page_extracts", 0) + extracts
        )


def _collect_search_batch(
    results: list[dict],
    *,
    query: str,
    search_focus: str,
    company: str,
    known_documents: dict[str, str],
    full_page_urls: set[str],
    tool_call_id: str,
    skill_ids: list[str] | None = None,
) -> tuple[
    dict[str, SearchDocument],
    int,
    list[OffTargetRejection],
    int,
    int,
    int,
    UrlSelectorDecision,
]:
    eligible, skipped_duplicate_results, off_target_rejections = _filter_eligible_results(
        results,
        query=query,
        search_focus=search_focus,
        company=company,
        known_documents=known_documents,
        full_page_urls=full_page_urls,
    )

    (
        eligible, # updated, at most 2 documents now has full page content, with full_page = True
        url_selector_extract_attempts,
        url_selector_full_page_extracts,
        url_selector_extract_failures,
        url_selector_decision, # for evaluation
    ) = _apply_url_selector_full_extracts(
        eligible,
        company=company,
        search_query=query,
        search_focus=search_focus,
        known_documents=known_documents,
        full_page_urls=full_page_urls,
        skill_ids=skill_ids,
    )
    selected_urls = {
        document["url"]
        for document in eligible
        if document.get("full_page")
    }
    eligible = _prioritize_selected_urls(eligible, selected_urls) # rerank, to keep selected result in top 5

    batch_documents = _take_extraction_batch(
        eligible,
        tool_call_id=tool_call_id,
    )

    return (
        batch_documents,
        skipped_duplicate_results,
        off_target_rejections,
        url_selector_extract_attempts,
        url_selector_full_page_extracts,
        url_selector_extract_failures,
        url_selector_decision,
    )


def _extract_and_verify_batch(
    batch_documents: dict[str, SearchDocument],
    *,
    company: str,
    requirement: str,
    search_query: str,
    search_focus: str,
    prior_verified_evidence: list,
    all_search_documents: dict[str, SearchDocument],
    positive_when: str = "",
    negative_when: str = "",
    does_not_count: list[str] | None = None,
    skill_ids: list[str] | None = None,
) -> tuple[dict, int, int, list[EvidenceExtractorDecision]]:
    """Extract+verify in char-budgeted micro-batches so full pages do not swamp snippets."""
    if not batch_documents:
        return {}, 0, 0, []

    merged_verification: dict = {}
    result_id_match_failures = 0
    duplicate_claim_skips = 0
    extractor_decisions: list[EvidenceExtractorDecision] = []

    running_prior = list(prior_verified_evidence)
    prior_verified_claims = [item.claim for item in running_prior]

    for micro_batch in _pack_extract_batches(batch_documents):
        batch_evidence, id_failures = extract_evidence_from_search_batch(
            company=company,
            requirement=requirement,
            search_query=search_query,
            search_focus=search_focus,
            prior_verified_claims=prior_verified_claims,
            batch_documents=micro_batch,
            positive_when=positive_when,
            negative_when=negative_when,
            does_not_count=does_not_count,
            skill_ids=skill_ids,
        )
        result_id_match_failures += id_failures
        extractor_decisions.append(
            EvidenceExtractorDecision(
                search_focus=search_focus,
                search_query=search_query,
                requirement_id="",
                prior_verified_claims=list(prior_verified_claims),
                documents=[
                    ExtractorDocument(
                        result_id=result_id,
                        title=document.get("title") or "",
                        url=document.get("url") or "",
                        content=document.get("content") or "",
                        full_page=bool(document.get("full_page")),
                    )
                    for result_id, document in micro_batch.items()
                ],
                extracted=[
                    ExtractorClaim(
                        claim=item.claim,
                        result_id=item.result_id,
                        source_excerpts=list(item.source_excerpts),
                    )
                    for item in batch_evidence
                ],
            )
        )
        verification_updates = [
            verify_evidence_item(
                evidence,
                company=company,
                search_documents=all_search_documents,
            )
            for evidence in batch_evidence
        ]
        micro_merged, micro_dup_skips = merge_verification_updates(
            verification_updates,
            running_prior,
        )
        duplicate_claim_skips += micro_dup_skips
        _merge_verification_dicts(merged_verification, micro_merged)

        newly_verified = micro_merged.get("verified_evidence") or []
        if newly_verified:
            running_prior.extend(newly_verified)
            prior_verified_claims = [item.claim for item in running_prior]

    return (
        merged_verification,
        result_id_match_failures,
        duplicate_claim_skips,
        extractor_decisions,
    )


@tool
def research_search(
    search_focus: str,
    runtime: ToolRuntime[ResearchAgentState] = None,
) -> dict:
    """Search for one missing fact.

    search_focus: the unresolved fact in plain language, e.g.
    "whether the property offers on-site catering for group events".
    Not a search query: no company name, keywords, quotes, or site:.
    The tool generates the retrieval query. The requirement comes from state.
    """
    prior_search_documents = runtime.state.get("search_documents") or {}
    company = runtime.state.get("company", "")
    requirement = runtime.state.get("requirement", "")
    positive_when = runtime.state.get("positive_when") or ""
    negative_when = runtime.state.get("negative_when") or ""
    does_not_count = list(runtime.state.get("does_not_count") or [])
    prior_verified = runtime.state.get("verified_evidence") or []
    prior_verified_claims = [item.claim for item in prior_verified]
    prior_queries = _collect_prior_queries(
        runtime.state.get("search_queries_used"),
        prior_search_documents,
    )
    prior_source_urls = _collect_prior_source_urls(prior_search_documents)

    # Turn search_focus into a Tavily keyword query; prior queries/URLs block repeats.
    generated = generate_search_query(
        company=company,
        search_focus=search_focus,
        prior_verified_claims=prior_verified_claims,
        prior_queries=prior_queries,
        prior_source_urls=prior_source_urls,
        skill_ids=list(runtime.state.get("skills") or []),
    )
    query = generated.query.strip()

    response = tavily_client.search(query, max_results=TAVILY_MAX_RESULTS)
    tavily_results = response.get("results") or []
    # know_documents: URL -> snippet (or full text) from earlier batches; full_page_urls: URLs already extracted in full.
    known_documents, full_page_urls = _build_known_document_indexes(prior_search_documents)
    # Filter Tavily hits (drop duplicates / off-target), pick 1-2 URLs for full extract,
    # then keep the top snippet/full-page docs as this batch.
    (
        search_documents,
        skipped_duplicate_results,
        off_target_rejections,
        url_selector_extract_attempts,
        url_selector_full_page_extracts,
        url_selector_extract_failures,
        url_selector_decision,
    ) = _collect_search_batch(
        tavily_results,
        query=query,  # stored on each SearchDocument
        search_focus=search_focus,  # off-target filter + URL selector
        company=company,  # drop results that never mention this company
        known_documents=known_documents,  # reuse prior snippet/full text for the same URL
        full_page_urls=full_page_urls,  # skip extract if this URL was already fetched
        tool_call_id=runtime.tool_call_id,  # prefix for this batch's result_ids
        skill_ids=list(runtime.state.get("skills") or []),
    )

    # Verifier may rematch excerpts against any document seen this run, not just this batch.
    all_search_documents = {**prior_search_documents, **search_documents}

    # Extract claims in char-budgeted micro-batches, then LLM-verify each claim.
    (
        merged_verification,
        result_id_match_failures,
        duplicate_claim_skips,
        extractor_decisions,
    ) = _extract_and_verify_batch(
        search_documents,  # only this search's pages (split further by char budget)
        company=company,  # extractor identity rule + verifier about_this_company
        requirement=requirement,
        search_query=query,  # recorded on each extractor decision
        search_focus=search_focus,
        prior_verified_evidence=prior_verified,  # do not re-extract or re-accept duplicates
        all_search_documents=all_search_documents,  # verifier looks up source by result_id
        positive_when=positive_when,
        negative_when=negative_when,
        does_not_count=does_not_count,
        skill_ids=list(runtime.state.get("skills") or []),
    )

    verified_batch = merged_verification.get("verified_evidence") or []
    empty_evidence_tool_calls = 1 if search_documents and not verified_batch else 0

    searches_used = runtime.state.get("tool_call_count", 0) + 1
    result_string = _format_tool_message_for_agent(
        searches_used=searches_used,
        verified_batch=verified_batch,
        tavily_hit_count=len(tavily_results),
        eligible_count=len(search_documents),
        off_target_count=len(off_target_rejections),
    )

    update: dict = {
        "tool_call_count": 1,
        "search_queries_used": [query] if query else [],
        "search_documents": search_documents,
        "batch_result_id_match_failures": result_id_match_failures,
        "off_target_company_rejections": len(off_target_rejections),
        "off_target_rejections": off_target_rejections,
        "duplicate_search_result_skips": skipped_duplicate_results,
        "duplicate_claim_skips": duplicate_claim_skips,
        "empty_evidence_tool_calls": empty_evidence_tool_calls,
        "url_selector_extract_attempts": url_selector_extract_attempts,
        "url_selector_full_page_extracts": url_selector_full_page_extracts,
        "url_selector_extract_failures": url_selector_extract_failures,
        "url_selector_decisions": _split_url_selector_decision_for_storage(
            url_selector_decision
        ),
        "query_generator_decisions": [
            QueryGeneratorDecision(
                search_focus=search_focus,
                prior_verified_claims=prior_verified_claims,
                prior_source_urls=prior_source_urls,
                query=query,
            )
        ],
        "evidence_extractor_decisions": extractor_decisions,
        "research_agent_steps": [
            ResearchAgentStep(
                search_focus=search_focus,
                evidence_received=[item.claim for item in verified_batch],
            )
        ],
        "messages": [
            ToolMessage(
                content=result_string,
                tool_call_id=runtime.tool_call_id,
            )
        ],
    }
    update.update(merged_verification)

    return Command(update=update)
