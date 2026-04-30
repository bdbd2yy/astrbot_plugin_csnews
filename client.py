from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import aiohttp

from astrbot.api import logger

from .config import CsNewsSettings
from .models import NewsItem


class CounterStrikeNewsClient:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        settings: CsNewsSettings,
    ) -> None:
        self._session = session
        self._settings = settings
        self._fetch_lock = asyncio.Lock()

    async def fetch_latest_news(self) -> list[NewsItem]:
        return await self.fetch_news(count=self._settings.latest_fetch_count)

    async def fetch_all_recent_news(self) -> list[NewsItem]:
        items: list[NewsItem] = []
        seen_gids: set[str] = set()
        offset = 0
        reached_old_news = False
        cutoff = self._recent_cutoff_timestamp()

        while len(items) < self._settings.list_fetch_limit and not reached_old_news:
            count = min(100, self._settings.list_fetch_limit - len(items))
            batch = await self.fetch_news(count=count, offset=offset)
            if not batch:
                break

            added = self._append_unique_items(items, batch, seen_gids)
            reached_old_news = any(item.date and item.date < cutoff for item in batch)

            if added == 0 or len(batch) < count:
                break
            offset += len(batch)

        return self.filter_recent(
            sorted(items, key=lambda item: item.date, reverse=True)
        )

    async def fetch_news(self, count: int, offset: int = 0) -> list[NewsItem]:
        params: dict[str, str | int] = {
            "clan_accountid": 0,
            "appid": self._settings.app_id,
            "offset": offset,
            "count": count,
            "l": self._settings.language,
            "origin": self._settings.origin,
        }

        async with self._fetch_lock:
            data = await self._request_events_page(params)

        events = data.get("events", []) if isinstance(data, dict) else []
        if not isinstance(events, list):
            return []

        return [
            self._normalize_event(event) for event in events if isinstance(event, dict)
        ]

    def filter_recent(self, items: list[NewsItem]) -> list[NewsItem]:
        cutoff = self._recent_cutoff_timestamp()
        return [item for item in items if item.date >= cutoff]

    async def _request_events_page(
        self, params: dict[str, str | int]
    ) -> dict[str, Any]:
        try:
            async with self._session.get(self._settings.api_url, params=params) as resp:
                if resp.status != 200:
                    logger.warning(
                        f"csnews Counter-Strike API returned status {resp.status}"
                    )
                    return {}
                data = await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError) as e:
            logger.warning(f"csnews failed to fetch Counter-Strike news: {e}")
            return {}

        return data if isinstance(data, dict) else {}

    def _normalize_event(self, event: dict[str, Any]) -> NewsItem:
        return NewsItem.from_steam_event(
            event,
            news_origin=self._settings.origin,
            updates_url=self._settings.updates_url,
            news_event_type=self._settings.news_event_type,
        )

    @staticmethod
    def _append_unique_items(
        items: list[NewsItem],
        batch: list[NewsItem],
        seen_gids: set[str],
    ) -> int:
        before = len(items)
        for item in batch:
            if item.gid and item.gid not in seen_gids:
                seen_gids.add(item.gid)
                items.append(item)
        return len(items) - before

    def _recent_cutoff_timestamp(self) -> int:
        return int(time.time()) - self._settings.recent_days * 24 * 60 * 60
