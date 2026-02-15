"""Application settings loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Runtime settings for API, RAG, and infrastructure layers."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "sales-tech-rag-agent"
    environment: str = "dev"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "INFO"

    qdrant_mode: str = "local"
    qdrant_url: str = "http://localhost:6333"
    qdrant_path: Path = Field(default=BASE_DIR / "data" / "qdrant")
    qdrant_api_key: str | None = None
    qdrant_collection: str = "knowledge_base"
    qdrant_timeout_sec: int = 10

    embedding_model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_batch_size: int = 32
    embedding_cache_size: int = 4096
    embedding_retry_attempts: int = 3

    chunk_size_words: int = 220
    chunk_overlap_words: int = 40

    retrieval_top_k: int = 8
    retrieval_candidate_k: int = 24
    similarity_threshold: float = 0.2
    reranker_semantic_weight: float = 0.6
    reranker_lexical_weight: float = 0.3
    reranker_numeric_weight: float = 0.1
    reranker_phrase_bonus: float = 0.05
    max_sources_per_answer: int = 3

    llm_provider: str = "local"
    llm_model_name: str = "Qwen2.5-7B-Instruct-GGUF"
    llm_temperature: float = 0.0
    llm_max_tokens: int = 500
    llm_timeout_sec: int = 30

    openai_api_key: str | None = None
    openai_base_url: str | None = None

    local_model_path: str = str(BASE_DIR / "models" / "Qwen2.5-7B-Instruct-Q4_K_M.gguf")
    local_model_repo_id: str = "bartowski/Qwen2.5-7B-Instruct-GGUF"
    local_model_filename: str = "Qwen2.5-7B-Instruct-Q4_K_M.gguf"
    local_model_context_size: int = 4096
    local_model_threads: int = 8

    document_storage_path: Path = Field(default=BASE_DIR / "data" / "documents")
    app_db_path: Path = Field(default=BASE_DIR / "data" / "app.db")
    uploaded_file_max_size_mb: int = 50
    auth_session_ttl_hours: int = 168

    market_intel_enabled: bool = True
    market_intel_timeout_sec: int = 8

    @model_validator(mode="after")
    def normalize_paths(self) -> "Settings":
        """Resolve relative paths against project base directory."""
        if not self.qdrant_path.is_absolute():
            self.qdrant_path = (BASE_DIR / self.qdrant_path).resolve()
        if not self.document_storage_path.is_absolute():
            self.document_storage_path = (BASE_DIR / self.document_storage_path).resolve()
        if not self.app_db_path.is_absolute():
            self.app_db_path = (BASE_DIR / self.app_db_path).resolve()
        model_path = Path(self.local_model_path)
        if not model_path.is_absolute():
            self.local_model_path = str((BASE_DIR / model_path).resolve())
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return singleton settings instance."""
    return Settings()
