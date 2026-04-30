from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from astrbot.api import logger

from .config import CsNewsSettings
from .models import NewsItem


class NewsStorage:
    def __init__(self, data_dir: Path, settings: CsNewsSettings) -> None:
        self.data_dir = data_dir
        self.settings = settings
        self.cache_file = data_dir / settings.cache_file_name
        self.raw_content_file = data_dir / settings.raw_content_file_name

    def read_cache(self) -> dict[str, Any]:
        if not self.cache_file.exists():
            return {}

        try:
            with self.cache_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"csnews failed to read cache: {e}")
            return {}

        return data if isinstance(data, dict) else {}

    def read_cached_items(self) -> list[NewsItem] | None:
        cache = self.read_cache()
        if not cache:
            return None

        fetched_at = int(cache.get("fetched_at", 0))
        if int(time.time()) - fetched_at >= self.settings.list_cache_ttl_seconds:
            return None

        items = cache.get("items", [])
        if not isinstance(items, list):
            return None

        return [NewsItem.from_mapping(item) for item in items if isinstance(item, dict)]

    def write_cache(self, items: list[NewsItem]) -> None:
        payload = {
            "fetched_at": int(time.time()),
            "items": [item.to_payload() for item in items],
        }
        self._write_json_atomic(self.cache_file, payload, indent=None)

    def write_raw_contents(self, item: NewsItem, raw_contents: str) -> None:
        payload = {
            "gid": item.gid,
            "title": item.title,
            "url": item.url,
            "fetched_at": int(time.time()),
            "contents": raw_contents,
        }
        self._write_json_atomic(self.raw_content_file, payload, indent=2)

    @staticmethod
    def _write_json_atomic(
        path: Path,
        payload: dict[str, Any],
        *,
        indent: int | None,
    ) -> None:
        tmp_file = path.with_suffix(".tmp")
        try:
            with tmp_file.open("w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=indent)
            tmp_file.replace(path)
        except OSError as e:
            logger.warning(f"csnews failed to write {path.name}: {e}")
