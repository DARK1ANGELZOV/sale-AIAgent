"""Citation construction and validation utilities."""

from __future__ import annotations

from app.models.schemas import SearchHit, SourceItem


class CitationValidator:
    """Build and verify answer citations against retrieved context."""

    def __init__(self, max_sources: int) -> None:
        self._max_sources = max_sources

    def build_sources(self, hits: list[SearchHit]) -> list[SourceItem]:
        """Build deterministic citations from top retrieved chunks."""
        sources: list[SourceItem] = []
        for hit in hits[: self._max_sources]:
            quote = self._compact_quote(hit.text)
            sources.append(
                SourceItem(
                    document_name=str(hit.metadata.get("document_name", "unknown")),
                    page_number=self._resolve_page_number(hit.metadata),
                    section=(
                        str(hit.metadata.get("section"))
                        if hit.metadata.get("section") is not None
                        else None
                    ),
                    quote=quote,
                    version=str(hit.metadata.get("version", "unknown")),
                )
            )
        return sources

    def validate(self, sources: list[SourceItem], hits: list[SearchHit]) -> bool:
        """Ensure each quote exists in at least one retrieved chunk."""
        context_texts = [hit.text for hit in hits]
        for source in sources:
            if not source.quote:
                return False
            quote = source.quote
            if quote.endswith("..."):
                quote = quote[:-3].rstrip()
            if not any(quote in text for text in context_texts):
                return False
        return True

    def format_answer(self, answer: str, sources: list[SourceItem]) -> str:
        """Return enforced final answer template."""
        lines = ["Ответ:", answer.strip(), "", "Источники:"]
        for idx, source in enumerate(sources, start=1):
            page_value = str(source.page_number) if source.page_number else "не указана"
            section_value = source.section or "n/a"
            lines.append(f"{idx}. Документ: {source.document_name}")
            lines.append(f"   Страница: {page_value}")
            lines.append(f"   Раздел: {section_value}")
            lines.append(f"   Цитата: \"{source.quote}\"")
        return "\n".join(lines).strip()

    def _compact_quote(self, text: str) -> str:
        cleaned = " ".join(text.split()).strip()
        max_len = 240
        if len(cleaned) <= max_len:
            return cleaned
        return cleaned[:max_len].rstrip()

    def _resolve_page_number(self, metadata: dict) -> int | None:
        raw_page = metadata.get("page_number")
        if raw_page is not None:
            try:
                page_number = int(raw_page)
                if page_number > 0:
                    return page_number
            except (TypeError, ValueError):
                pass

        section = str(metadata.get("section", "")).lower()
        if section.startswith("page_"):
            try:
                return int(section.replace("page_", "", 1))
            except ValueError:
                pass

        chunk_order = metadata.get("chunk_order")
        if chunk_order is not None:
            try:
                estimated = int(chunk_order) + 1
                return estimated if estimated > 0 else None
            except (TypeError, ValueError):
                return None
        return None
