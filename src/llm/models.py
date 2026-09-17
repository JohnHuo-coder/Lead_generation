from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from schemas.research_schemas import (
    ExcerptDerivationResult,
    SearchBatchEvidenceResult,
    VerifyResult,
)
from schemas.fit_scoring_schemas import FitScoreResult

load_dotenv()

llm = ChatOpenAI(model="gpt-5-nano")

structured_search_batch_evidence_llm = ChatOpenAI(model="gpt-5-nano").with_structured_output(
    SearchBatchEvidenceResult
)

structured_verification_llm = ChatOpenAI(model="gpt-5-nano").with_structured_output(VerifyResult)

structured_excerpt_derivation_llm = ChatOpenAI(model="gpt-5-nano").with_structured_output(
    ExcerptDerivationResult
)

structured_fit_score_llm = ChatOpenAI(model="gpt-5-nano").with_structured_output(FitScoreResult)