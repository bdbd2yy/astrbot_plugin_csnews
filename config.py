from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class CsNewsSettings:
    api_url: str = "https://store.steampowered.com/events/ajaxgetpartnereventspageable/"
    origin: str = "https://www.counter-strike.net"
    updates_url: str = "https://www.counter-strike.net/news/updates"
    steam_clan_image_base: str = "https://clan.fastly.steamstatic.com/images"
    app_id: int = 730
    language: str = "schinese"
    update_event_type: int = 12
    news_event_type: int = 13
    list_page_size: int = 10
    list_fetch_limit: int = 300
    list_cache_ttl_seconds: int = 10 * 60
    recent_days: int = 365
    latest_fetch_count: int = 10
    push_interval_seconds: int = 10 * 60
    detail_max_chars: int = 3500
    request_timeout_seconds: int = 20
    cache_file_name: str = "news_cache.json"
    raw_content_file_name: str = "latest_raw_contents.txt"
    patch_note_section_titles: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "地图",
                "音效",
                "杂项",
                "游戏玩法",
                "动画",
                "图形",
                "库存",
                "武器",
                "网络",
                "UI",
            }
        )
    )
