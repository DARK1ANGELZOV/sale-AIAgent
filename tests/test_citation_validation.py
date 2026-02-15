"""Unit tests for citation validation guarantees."""

from app.models.schemas import SearchHit
from app.rag.citation import CitationValidator


def test_citation_validator_accepts_existing_quote() -> None:
    validator = CitationValidator(max_sources=2)
    hits = [
        SearchHit(
            id="1",
            score=0.91,
            text="This product supports SSO and multi-tenant setup.",
            metadata={"document_name": "manual.pdf", "version": "v1", "page_number": 4},
        )
    ]
    sources = validator.build_sources(hits)

    assert validator.validate(sources, hits) is True


def test_citation_validator_rejects_nonexistent_quote() -> None:
    validator = CitationValidator(max_sources=1)
    hits = [
        SearchHit(
            id="1",
            score=0.91,
            text="Only this sentence exists in retrieval context.",
            metadata={"document_name": "manual.pdf", "version": "v1", "page_number": 2},
        )
    ]
    sources = validator.build_sources(hits)
    sources[0].quote = "Missing quote that is not present"

    assert validator.validate(sources, hits) is False
