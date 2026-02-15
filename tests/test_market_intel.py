"""Tests for market comparison enrichment."""

import asyncio

from app.models.schemas import SearchHit
from app.services.market_intel_service import MarketIntelService, MarketTickerSnapshot


class StubMarketIntelService(MarketIntelService):
    """Market service with deterministic data for tests."""

    async def _fetch_snapshots(self, tickers: tuple[str, ...]):  # type: ignore[override]
        return [
            MarketTickerSnapshot(ticker="CRWD", last_close=300.0, return_30d=12.0, currency="USD"),
            MarketTickerSnapshot(ticker="PANW", last_close=320.0, return_30d=5.5, currency="USD"),
        ]


def test_market_enrichment_contains_mermaid() -> None:
    service = StubMarketIntelService(enabled=True)
    hits = [
        SearchHit(
            id="1",
            score=0.8,
            text="Рекомендованная цена: 149900 RUB для базовой лицензии.",
            metadata={},
        )
    ]
    block = asyncio.run(service.build_market_block("Сравни с рынком", hits))

    assert block is not None
    assert "```mermaid" in block
    assert "xychart-beta" in block
    assert "CRWD" in block


def test_market_enrichment_disabled_for_non_market_question() -> None:
    service = StubMarketIntelService(enabled=True)
    block = asyncio.run(service.build_market_block("Как включить функцию?", []))
    assert block is None
