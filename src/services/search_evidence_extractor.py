from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from llm.models import structured_search_batch_evidence_llm
from prompts.system_prompts import SEARCH_BATCH_EVIDENCE_PROMPT
from schemas.research_schemas import Evidence, SearchDocument


def _normalize_for_match(text: str) -> str:
    return " ".join(text.split()).casefold()


def _excerpt_in_content(excerpt: str, content: str) -> bool:
    normalized_excerpt = _normalize_for_match(excerpt)
    if not normalized_excerpt:
        return False
    return normalized_excerpt in _normalize_for_match(content)


def _format_batch_results(batch_documents: dict[str, SearchDocument]) -> str:
    blocks: list[str] = []
    for result_id, document in batch_documents.items():
        blocks.append(
            f"result_id: {result_id}\n"
            f"title: {document['title']}\n"
            f"url: {document['url']}\n"
            f"content: {document['content']}"
        )
    return "\n\n---\n\n".join(blocks)


def _resolve_evidence_to_batch(
    evidence: Evidence,
    batch_documents: dict[str, SearchDocument],
) -> Evidence | None:
    def _matches_document(result_id: str) -> bool:
        document = batch_documents.get(result_id)
        if document is None:
            return False
        return all(
            _excerpt_in_content(excerpt, document["content"])
            for excerpt in evidence.source_excerpts
        )

    if evidence.result_id in batch_documents and _matches_document(evidence.result_id):
        document = batch_documents[evidence.result_id]
        return evidence.model_copy(update={"url": document["url"]})

    matching_ids = [
        result_id
        for result_id in batch_documents
        if _matches_document(result_id)
    ]
    if len(matching_ids) == 1:
        document = batch_documents[matching_ids[0]]
        return evidence.model_copy(
            update={
                "result_id": matching_ids[0],
                "url": document["url"],
            }
        )

    return None


def extract_evidence_from_search_batch(
    *,
    company: str,
    collaboration_intent: str,
    requirement: str,
    batch_documents: dict[str, SearchDocument],
) -> list[Evidence]:
    if not batch_documents:
        return []

    result = structured_search_batch_evidence_llm.invoke([
        SystemMessage(content=SEARCH_BATCH_EVIDENCE_PROMPT),
        HumanMessage(content=(
            f"Company: {company}\n"
            f"Collaboration intent: {collaboration_intent}\n"
            f"Requirement: {requirement}\n\n"
            f"Search results from this search only:\n"
            f"{_format_batch_results(batch_documents)}"
        )),
    ])

    resolved: list[Evidence] = []
    for item in result.evidence:
        matched = _resolve_evidence_to_batch(item, batch_documents)
        if matched is not None:
            resolved.append(matched)
    return resolved
