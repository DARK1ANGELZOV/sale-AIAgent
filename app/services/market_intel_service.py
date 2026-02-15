"""External market intelligence service for comparison blocks."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime

import httpx

from app.core.constants import UTC_TIMEZONE
from app.models.schemas import SearchHit

MARKET_KEYWORDS = {
    "market",
    "compare",
    "pricing",
    "price",
    "competitor",
    "vs",
    "\u0440\u044b\u043d\u043e\u043a",
    "\u0441\u0440\u0430\u0432\u043d\u0438",
    "\u0446\u0435\u043d\u0430",
    "\u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442",
    "\u0442\u0430\u0440\u0438\u0444",
    "\u043a\u043e\u043d\u043a\u0443\u0440\u0435\u043d\u0442",
}


@dataclass(slots=True)
class MarketTickerSnapshot:
    """One ticker market snapshot."""

    ticker: str
    last_close: float
    return_30d: float
    currency: str


class MarketIntelService:
    """Fetch market snapshots and build comparison + mermaid blocks."""

    def __init__(self, enabled: bool = True, timeout_sec: int = 8) -> None:
        self._enabled = enabled
        self._timeout_sec = timeout_sec
        self._default_tickers = ("CRWD", "PANW", "FTNT", "CHKP")
        self._base_url = "https://query1.finance.yahoo.com/v8/finance/chart"

    def should_enrich(self, question: str) -> bool:
        """Return true if question likely asks market comparison."""
        q = question.lower()
        return any(keyword in q for keyword in MARKET_KEYWORDS)

    async def build_market_block(self, question: str, hits: list[SearchHit]) -> str | None:
        """Return markdown block with market comparison and mermaid chart."""
        if not self._enabled or not self.should_enrich(question):
            return None

        snapshots = await self._fetch_snapshots(self._default_tickers)
        internal_price = self._extract_internal_price(hits)

        lines = ["Market comparison (auto):"]
        if internal_price is not None:
            lines.append(
                f"- By your documents: indicative internal price/value is about {internal_price:.2f}."
            )
        else:
            lines.append("- By your documents: no explicit numeric price anchor found.")

        if snapshots:
            market_avg_close = sum(item.last_close for item in snapshots) / len(snapshots)
            market_avg_return = sum(item.return_30d for item in snapshots) / len(snapshots)
            lines.append(
                f"- Market benchmark (public analogs): avg close price {market_avg_close:.2f}, "
                f"avg 30d return {market_avg_return:+.2f}%."
            )
            mermaid_body = self._build_mermaid_xychart(snapshots)
        else:
            lines.append(
                "- Market benchmark data is temporarily unavailable, showing internal-only fallback view."
            )
            mermaid_body = self._build_fallback_mermaid(internal_price)

        lines.extend(
            [
                "",
                "```mermaid",
                mermaid_body,
                "```",
                "",
                (
                    f"_Market data source: Yahoo Finance / Stooq, updated "
                    f"{datetime.now(tz=UTC_TIMEZONE).strftime('%Y-%m-%d %H:%M UTC')}_"
                ),
            ]
        )
        return "\n".join(lines)

    async def _fetch_snapshots(self, tickers: tuple[str, ...]) -> list[MarketTickerSnapshot]:
        async with httpx.AsyncClient(timeout=self._timeout_sec) as client:
            tasks = [self._fetch_one(client, ticker) for ticker in tickers]
            results = await asyncio.gather(*tasks, return_exceptions=True)
        snapshots: list[MarketTickerSnapshot] = []
        for result in results:
            if isinstance(result, MarketTickerSnapshot):
                snapshots.append(result)
        return snapshots

    async def _fetch_one(
        self,
        client: httpx.AsyncClient,
        ticker: str,
    ) -> MarketTickerSnapshot | None:
        try:
            snapshot = await self._fetch_one_yahoo(client=client, ticker=ticker)
            if snapshot is not None:
                return snapshot
            return await self._fetch_one_stooq(client=client, ticker=ticker)
        except Exception:  # noqa: BLE001
            return None

    async def _fetch_one_yahoo(
        self,
        client: httpx.AsyncClient,
        ticker: str,
    ) -> MarketTickerSnapshot | None:
        url = f"{self._base_url}/{ticker}"
        params = {"range": "1mo", "interval": "1d"}
        response = await client.get(url, params=params)
        if response.status_code >= 400:
            return None

        payload = response.json()
        result = payload.get("chart", {}).get("result", [])
        if not result:
            return None
        data = result[0]
        closes = data.get("indicators", {}).get("quote", [{}])[0].get("close", [])
        closes = [float(value) for value in closes if value is not None]
        if len(closes) < 2:
            return None

        meta = data.get("meta", {}) or {}
        currency = str(meta.get("currency", "USD"))
        first_close = closes[0]
        last_close = closes[-1]
        return_30d = ((last_close - first_close) / first_close) * 100.0
        return MarketTickerSnapshot(
            ticker=ticker,
            last_close=last_close,
            return_30d=return_30d,
            currency=currency,
        )

    async def _fetch_one_stooq(
        self,
        client: httpx.AsyncClient,
        ticker: str,
    ) -> MarketTickerSnapshot | None:
        stooq_symbol = f"{ticker.lower()}.us"
        response = await client.get(
            "https://stooq.com/q/d/l/",
            params={"s": stooq_symbol, "i": "d"},
        )
        if response.status_code >= 400:
            return None

        rows = response.text.strip().splitlines()
        if len(rows) < 3:
            return None

        closes: list[float] = []
        for row in rows[1:]:
            parts = row.split(",")
            if len(parts) < 5:
                continue
            try:
                closes.append(float(parts[4]))
            except ValueError:
                continue

        if len(closes) < 3:
            return None

        window = closes[-22:] if len(closes) > 22 else closes
        first_close = window[0]
        last_close = window[-1]
        return_30d = ((last_close - first_close) / first_close) * 100.0
        return MarketTickerSnapshot(
            ticker=ticker,
            last_close=last_close,
            return_30d=return_30d,
            currency="USD",
        )

    def _extract_internal_price(self, hits: list[SearchHit]) -> float | None:
        number_pattern = re.compile(r"\b\d{2,7}(?:[.,]\d{1,2})?\b")
        anchors = (
            "price",
            "pricing",
            "\u0446\u0435\u043d",
            "\u0441\u0442\u043e\u0438\u043c",
            "\u0442\u0430\u0440\u0438\u0444",
        )

        for hit in hits[:5]:
            text = hit.text.lower()
            if not any(anchor in text for anchor in anchors):
                continue
            for raw_number in number_pattern.findall(text):
                number = raw_number.replace(",", ".")
                try:
                    value = float(number)
                except ValueError:
                    continue
                if 10 <= value <= 1_000_000:
                    return value
        return None

    def _build_mermaid_xychart(self, snapshots: list[MarketTickerSnapshot]) -> str:
        labels = ", ".join(f'"{item.ticker}"' for item in snapshots)
        values = ", ".join(f"{item.return_30d:.2f}" for item in snapshots)
        min_value = min(item.return_30d for item in snapshots)
        max_value = max(item.return_30d for item in snapshots)

        y_min = int(min(-25, min_value - 5))
        y_max = int(max(25, max_value + 5))

        return (
            "xychart-beta\n"
            '    title "Market Return 30d (%)"\n'
            f"    x-axis [{labels}]\n"
            f'    y-axis "Return %" {y_min} --> {y_max}\n'
            f"    bar [{values}]"
        )

    def _build_fallback_mermaid(self, internal_price: float | None) -> str:
        internal_value = internal_price if internal_price is not None else 0.0
        return (
            "xychart-beta\n"
            '    title "Internal Benchmark"\n'
            '    x-axis ["Internal"]\n'
            '    y-axis "Value" 0 --> 1000000\n'
            f"    bar [{internal_value:.2f}]"
        )
