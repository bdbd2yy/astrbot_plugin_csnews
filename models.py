from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


@dataclass(slots=True)
class NewsItem:
    gid: str = ""
    title: str = ""
    url: str = ""
    contents: str = ""
    feedlabel: str = ""
    feedname: str = ""
    feed_type: int = 0
    date: int = 0
    tags: list[str] = field(default_factory=list)
    event_type: int = 0
    language: int = 0

    @classmethod
    def from_mapping(cls, item: dict[str, Any]) -> NewsItem:
        tags = item.get("tags", [])
        if not isinstance(tags, list):
            tags = []

        return cls(
            gid=str(item.get("gid") or ""),
            title=str(item.get("title") or ""),
            url=str(item.get("url") or ""),
            contents=str(item.get("contents") or ""),
            feedlabel=str(item.get("feedlabel") or ""),
            feedname=str(item.get("feedname") or ""),
            feed_type=to_int(item.get("feed_type")),
            date=to_int(item.get("date")),
            tags=[str(tag) for tag in tags if tag],
            event_type=to_int(item.get("event_type")),
            language=to_int(item.get("language")),
        )

    @classmethod
    def from_steam_event(
        cls,
        event: dict[str, Any],
        *,
        news_origin: str,
        updates_url: str,
        news_event_type: int,
    ) -> NewsItem:
        body = event.get("announcement_body", {})
        if not isinstance(body, dict):
            body = {}

        tags = body.get("tags", [])
        if not isinstance(tags, list):
            tags = []

        event_gid = str(
            event.get("gid") or body.get("event_gid") or body.get("gid") or ""
        )
        body_gid = str(body.get("gid") or event_gid)
        gid = event_gid or body_gid
        event_type = to_int(event.get("event_type"))

        return cls(
            gid=gid,
            title=str(body.get("headline") or event.get("event_name") or ""),
            url=(
                f"{news_origin}/newsentry/{gid}"
                if event_type == news_event_type and gid
                else updates_url
            ),
            contents=str(body.get("body") or ""),
            feedlabel="Counter-Strike Official",
            feedname="counter-strike_official",
            feed_type=1,
            date=to_int(body.get("posttime") or event.get("rtime32_start_time")),
            tags=[str(tag) for tag in tags if tag],
            event_type=event_type,
            language=to_int(body.get("language")),
        )

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def lowercase_tags(self) -> list[str]:
        return [tag.lower() for tag in self.tags if tag]
