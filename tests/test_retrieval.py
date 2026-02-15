"""Unit tests for retrieval filtering logic."""

import asyncio

from app.models.schemas import SearchHit
from app.rag.retriever import Retriever


class FakeEmbeddingService:
    """Simple fake embedding service."""

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        assert texts
        return [[0.1, 0.2, 0.3]]


class FakeQdrantService:
    """Simple fake qdrant service."""

    async def search(
        self,
        query_vector: list[float],
        top_k: int,
        version: str | None = None,
        document_names: list[str] | None = None,
    ) -> list[SearchHit]:
        assert query_vector
        assert top_k == 3
        assert version == "v1"
        assert document_names is None
        return [
            SearchHit(
                id="1",
                score=0.7,
                text="relevant text",
                metadata={"document_name": "doc1", "version": "v1"},
            ),
            SearchHit(
                id="2",
                score=0.2,
                text="irrelevant text",
                metadata={"document_name": "doc2", "version": "v1"},
            ),
        ]


class FakeQdrantForRerank:
    """Returns candidates where lexical relevance should win."""

    async def search(
        self,
        query_vector: list[float],
        top_k: int,
        version: str | None = None,
        document_names: list[str] | None = None,
    ) -> list[SearchHit]:
        assert query_vector
        assert top_k == 5
        assert version is None
        assert document_names is None
        return [
            SearchHit(
                id="semantic_only",
                score=0.72,
                text="General platform information without pricing details.",
                metadata={"document_name": "doc_general", "version": "v1"},
            ),
            SearchHit(
                id="lexical_match",
                score=0.42,
                text="Recommended retail price for AstroSecure 5000 is 149900 RUB.",
                metadata={"document_name": "doc_price", "version": "v1"},
            ),
        ]


class FakeQdrantWithDocumentScope:
    """Ensures document_names filter is forwarded to vector search."""

    def __init__(self) -> None:
        self.last_document_names: list[str] | None = None

    async def search(
        self,
        query_vector: list[float],
        top_k: int,
        version: str | None = None,
        document_names: list[str] | None = None,
    ) -> list[SearchHit]:
        assert query_vector
        assert top_k == 3
        assert version is None
        self.last_document_names = document_names
        return [
            SearchHit(
                id="scoped",
                score=0.81,
                text="AstroSecure scoped text.",
                metadata={"document_name": "scope.docx", "version": "v1"},
            )
        ]


def test_retrieval_applies_similarity_threshold() -> None:
    retriever = Retriever(
        embedding_service=FakeEmbeddingService(),  # type: ignore[arg-type]
        qdrant_service=FakeQdrantService(),  # type: ignore[arg-type]
        top_k=3,
        similarity_threshold=0.3,
    )

    result = asyncio.run(retriever.retrieve(question="test?", version="v1"))

    assert len(result.hits) == 1
    assert result.hits[0].id == "1"
    assert result.confidence == 0.42


def test_retrieval_reranker_promotes_lexical_match() -> None:
    retriever = Retriever(
        embedding_service=FakeEmbeddingService(),  # type: ignore[arg-type]
        qdrant_service=FakeQdrantForRerank(),  # type: ignore[arg-type]
        top_k=2,
        similarity_threshold=0.2,
        candidate_k=5,
    )

    result = asyncio.run(
        retriever.retrieve(question="AstroSecure 5000 retail price", version=None)
    )

    assert result.hits
    assert result.hits[0].id == "lexical_match"
    assert result.confidence >= result.hits[-1].score


def test_retrieval_passes_document_scope_to_qdrant() -> None:
    qdrant = FakeQdrantWithDocumentScope()
    retriever = Retriever(
        embedding_service=FakeEmbeddingService(),  # type: ignore[arg-type]
        qdrant_service=qdrant,  # type: ignore[arg-type]
        top_k=3,
        similarity_threshold=0.2,
    )

    result = asyncio.run(
        retriever.retrieve(
            question="scope question",
            version=None,
            document_names=["scope.docx", "scope.docx", "  "],
        )
    )

    assert result.hits
    assert result.hits[0].id == "scoped"
    assert qdrant.last_document_names == ["scope.docx"]
