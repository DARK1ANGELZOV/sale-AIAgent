"""Dependency container for application services."""

from __future__ import annotations

from app.config.settings import Settings
from app.ingestion.parsers import DocumentParser
from app.ingestion.pipeline import IngestionPipeline
from app.rag.chunking import TextChunker
from app.rag.citation import CitationValidator
from app.rag.embeddings import EmbeddingService
from app.rag.generator import RAGService
from app.rag.reranker import HybridReranker
from app.rag.retriever import Retriever
from app.services.document_service import DocumentService
from app.services.llm_service import LLMService
from app.services.auth_service import AuthService
from app.services.market_intel_service import MarketIntelService
from app.services.qdrant_service import QdrantService


class ServiceContainer:
    """Create and hold singleton service instances."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

        self.embedding_service = EmbeddingService(
            model_name=settings.embedding_model_name,
            batch_size=settings.embedding_batch_size,
            cache_size=settings.embedding_cache_size,
            retry_attempts=settings.embedding_retry_attempts,
        )
        self.qdrant_service = QdrantService(
            mode=settings.qdrant_mode,
            url=settings.qdrant_url,
            path=settings.qdrant_path,
            collection_name=settings.qdrant_collection,
            timeout_sec=settings.qdrant_timeout_sec,
            api_key=settings.qdrant_api_key,
        )
        self.retriever = Retriever(
            embedding_service=self.embedding_service,
            qdrant_service=self.qdrant_service,
            top_k=settings.retrieval_top_k,
            similarity_threshold=settings.similarity_threshold,
            candidate_k=settings.retrieval_candidate_k,
            reranker=HybridReranker(
                semantic_weight=settings.reranker_semantic_weight,
                lexical_weight=settings.reranker_lexical_weight,
                numeric_weight=settings.reranker_numeric_weight,
                phrase_bonus=settings.reranker_phrase_bonus,
            ),
        )
        self.llm_service = LLMService(
            provider=settings.llm_provider,
            model_name=settings.llm_model_name,
            timeout_sec=settings.llm_timeout_sec,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            local_model_path=settings.local_model_path,
            local_model_repo_id=settings.local_model_repo_id,
            local_model_filename=settings.local_model_filename,
            local_context_size=settings.local_model_context_size,
            local_threads=settings.local_model_threads,
        )
        self.citation_validator = CitationValidator(
            max_sources=settings.max_sources_per_answer
        )
        self.market_intel_service = MarketIntelService(
            enabled=settings.market_intel_enabled,
            timeout_sec=settings.market_intel_timeout_sec,
        )
        self.rag_service = RAGService(
            retriever=self.retriever,
            llm_service=self.llm_service,
            citation_validator=self.citation_validator,
            market_intel_service=self.market_intel_service,
        )

        parser = DocumentParser()
        chunker = TextChunker(
            chunk_size_words=settings.chunk_size_words,
            chunk_overlap_words=settings.chunk_overlap_words,
        )
        ingestion_pipeline = IngestionPipeline(parser=parser, chunker=chunker)
        self.document_service = DocumentService(
            storage_path=settings.document_storage_path,
            ingestion_pipeline=ingestion_pipeline,
            embedding_service=self.embedding_service,
            qdrant_service=self.qdrant_service,
        )
        self.auth_service = AuthService(
            db_path=settings.app_db_path,
            session_ttl_hours=settings.auth_session_ttl_hours,
        )
