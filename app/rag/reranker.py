"""Hybrid reranker for semantic + lexical retrieval quality."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.schemas import SearchHit

TOKEN_PATTERN = re.compile(r"[0-9A-Za-zА-Яа-яЁё]+", re.IGNORECASE)
NUMBER_PATTERN = re.compile(r"\d+(?:[.,]\d+)?")


def tokenize_text(text: str, min_token_length: int = 2) -> set[str]:
    """Tokenize latin/cyrillic alphanumeric content."""
    tokens = {token.lower() for token in TOKEN_PATTERN.findall(text)}
    return {token for token in tokens if len(token) >= min_token_length}


@dataclass(slots=True)
class HybridReranker:
    """Fuse vector score with lexical and numeric overlaps."""

    semantic_weight: float = 0.6
    lexical_weight: float = 0.3
    numeric_weight: float = 0.1
    phrase_bonus: float = 0.05
    min_token_length: int = 2

    def rerank(self, question: str, hits: list[SearchHit], top_k: int) -> list[SearchHit]:
        """Return top-k hits sorted by fused relevance score."""
        if not hits:
            return []

        question_tokens = self._tokenize(question)
        question_numbers = self._extract_numbers(question)
        question_clean = " ".join(question.lower().split())

        rescored: list[SearchHit] = []
        for hit in hits:
            semantic = self._clamp01(hit.score)
            lexical = self._lexical_overlap(question_tokens, hit.text)
            numeric = self._numeric_overlap(question_numbers, hit.text)
            phrase = self.phrase_bonus if question_clean and question_clean in hit.text.lower() else 0.0

            fused = (
                semantic * self.semantic_weight
                + lexical * self.lexical_weight
                + numeric * self.numeric_weight
                + phrase
            )

            hit.score = self._clamp01(fused)
            rescored.append(hit)

        rescored.sort(key=lambda item: item.score, reverse=True)
        return rescored[:top_k]

    def _tokenize(self, text: str) -> set[str]:
        return tokenize_text(text=text, min_token_length=self.min_token_length)

    def _extract_numbers(self, text: str) -> set[str]:
        return {raw.replace(",", ".") for raw in NUMBER_PATTERN.findall(text)}

    def _lexical_overlap(self, question_tokens: set[str], chunk_text: str) -> float:
        if not question_tokens:
            return 0.0
        chunk_tokens = self._tokenize(chunk_text)
        if not chunk_tokens:
            return 0.0
        shared = question_tokens.intersection(chunk_tokens)
        return len(shared) / len(question_tokens)

    def _numeric_overlap(self, question_numbers: set[str], chunk_text: str) -> float:
        if not question_numbers:
            return 0.0
        chunk_numbers = self._extract_numbers(chunk_text)
        if not chunk_numbers:
            return 0.0
        shared = question_numbers.intersection(chunk_numbers)
        return len(shared) / len(question_numbers)

    def _clamp01(self, value: float) -> float:
        return max(0.0, min(1.0, value))
