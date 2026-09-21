import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from schemas.research_schemas import (
    ExcerptDerivationResult,
    SearchBatchEvidenceResult,
    VerifyResult,
)
from schemas.fit_scoring_schemas import FitScoreResult

load_dotenv()

# Agent + structured research steps (override via .env).
RESEARCH_LLM_MODEL = os.getenv("RESEARCH_LLM_MODEL", "gpt-5-mini")
RESEARCH_DERIVATION_LLM_MODEL = os.getenv(
    "RESEARCH_DERIVATION_LLM_MODEL",
    "gpt-5-nano",
)

llm = ChatOpenAI(model=RESEARCH_LLM_MODEL)

structured_search_batch_evidence_llm = ChatOpenAI(
    model=RESEARCH_LLM_MODEL,
).with_structured_output(SearchBatchEvidenceResult)

structured_verification_llm = ChatOpenAI(
    model=RESEARCH_LLM_MODEL,
).with_structured_output(VerifyResult)

structured_excerpt_derivation_llm = ChatOpenAI(
    model=RESEARCH_DERIVATION_LLM_MODEL,
).with_structured_output(ExcerptDerivationResult)

structured_fit_score_llm = ChatOpenAI(
    model=RESEARCH_LLM_MODEL,
).with_structured_output(FitScoreResult)
