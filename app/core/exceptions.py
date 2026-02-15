"""Custom exception hierarchy for the RAG service."""


class AppError(Exception):
    """Base application error."""


class IngestionError(AppError):
    """Raised when document ingestion fails."""


class UnsupportedFileTypeError(IngestionError):
    """Raised for unsupported upload extension."""


class QdrantUnavailableError(AppError):
    """Raised when vector database is unavailable."""


class RetrievalError(AppError):
    """Raised when retrieval pipeline fails."""


class EmbeddingError(AppError):
    """Raised when embedding generation fails."""


class LLMTimeoutError(AppError):
    """Raised when LLM request exceeds timeout."""


class EmptyLLMResponseError(AppError):
    """Raised when LLM returns an empty response."""


class ModelMemoryError(AppError):
    """Raised when local model cannot be loaded or run due to memory."""


class CitationValidationError(AppError):
    """Raised when citations cannot be verified."""
