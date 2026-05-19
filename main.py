from __future__ import annotations

import asyncio
import random
import re
from collections.abc import AsyncGenerator, Callable
from datetime import datetime, timedelta

import aiohttp

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, MessageEventResult, filter
from astrbot.api.message_components import BaseMessageComponent, Node, Nodes, Plain
from astrbot.api.star import Context, Star, StarTools, register
from astrbot.core.platform.message_type import MessageType

from .client import CounterStrikeNewsClient
from .config import CsNewsSettings
from .formatter import NewsFormatter
from .models import NewsItem
from .storage import NewsStorage


@register("csnews", "bdbd2yy", "CS2 official news push plugin", "1.0.0")
class CsNewsPlugin(Star):
    KV_ENABLED_SESSIONS = "enabled_sessions"
    KV_LAST_PUSHED_GID = "last_pushed_gid"
    CONFIG_ENABLED_SESSIONS = "enabled_sessions"
    CONFIG_PUSH_TIME = "push_time"
    DEFAULT_PUSH_HOUR = 9
    DEFAULT_PUSH_MINUTE = 0

    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context, config)
        self._context = context
        self.settings = CsNewsSettings()
        self.plugin_config: dict = config or {}
        self._push_hour, self._push_minute = self._parse_push_time()
        self.data_dir = StarTools.get_data_dir()
        self.storage = NewsStorage(self.data_dir, self.settings)
        self.formatter = NewsFormatter(self.settings)
        self._session: aiohttp.ClientSession | None = None
        self._client: CounterStrikeNewsClient | None = None
        self._push_task: asyncio.Task[None] | None = None

    async def initialize(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.settings.request_timeout_seconds),
        )
        self._client = CounterStrikeNewsClient(self._session, self.settings)
        self._push_task = asyncio.create_task(self._push_loop())
        logger.info("csnews plugin initialized")

    @filter.command_group("csnews")
    async def csnews(
        self,
    ):
        pass

    @csnews.command("ls")
    async def list(self, event: AstrMessageEvent, page: int = 1):
        yield event.plain_result(
            self._render_news_list(
                page=page,
                items=await self._get_yearly_news_items(),
                title="CS 新闻列表",
                command_name="csnews",
                empty_text="暂时没有获取到 CS 新闻，请稍后再试。",
            )
        )

    @csnews.command("help")
    async def help(self, event: AstrMessageEvent):
        yield event.plain_result(self._help_text())

    @csnews.command("cat")
    async def cat(self, event: AstrMessageEvent, index: int):
        yield self._render_news_detail(
            event,
            index=int(index),
            items=await self._get_yearly_news_items(),
            empty_text="暂时没有获取到 CS 新闻，请稍后再试。",
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @csnews.command("on")
    async def enable_push(self, event: AstrMessageEvent):
        yield event.plain_result(await self._enable_push(event))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @csnews.command("off")
    async def disable_push(self, event: AstrMessageEvent):
        yield event.plain_result(await self._disable_push(event))

    @filter.command("csupdates")
    async def csupdates(
        self,
        event: AstrMessageEvent,
    ) -> AsyncGenerator[MessageEventResult, None]:
        args = self._parse_command_args(event, "csupdates")
        if not args:
            yield event.plain_result(self._updates_help_text())
            return

        action = args[0].lower()
        if action == "ls":
            yield event.plain_result(
                self._render_news_list(
                    page=self._parse_page(args[1:]),
                    items=await self._get_latest_update_items(),
                    title="CS 更新列表",
                    command_name="csupdates",
                    empty_text="最近暂时没有获取到 CS 更新公告，请稍后再试。",
                )
            )
            return

        if action.isdigit():
            yield self._render_news_detail(
                event,
                int(action),
                await self._get_latest_update_items(),
                "最近暂时没有获取到 CS 更新公告，请稍后再试。",
            )
            return

        yield event.plain_result(self._updates_help_text())

    def _render_news_list(
        self,
        *,
        page: int,
        items: list[NewsItem],
        title: str,
        command_name: str,
        empty_text: str,
    ) -> str:
        return self.formatter.render_list(
            page=page,
            items=items,
            title=title,
            command_name=command_name,
            empty_text=empty_text,
        )

    def _render_news_detail(
        self,
        event: AstrMessageEvent,
        index: int,
        items: list[NewsItem],
        empty_text: str,
    ) -> MessageEventResult:
        if not items:
            return event.plain_result(empty_text)
        if index < 1 or index > len(items):
            return event.plain_result(
                f"序号超出范围，请输入 1 到 {len(items)} 之间的数字"
            )

        item = items[index - 1]
        self.storage.write_raw_contents(
            item, self.formatter.normalize_markup(item.contents)
        )
        node = Node(
            name="CS News",
            uin=event.get_self_id() or "0",
            content=self.formatter.render_components(item),
        )
        chain: list[BaseMessageComponent] = [Nodes([node])]
        return event.chain_result(chain)

    async def _enable_push(self, event: AstrMessageEvent) -> str:
        if (
            event.get_message_type() != MessageType.GROUP_MESSAGE
            or not event.get_group_id()
        ):
            return "csnews on 只能在群聊中使用"

        session = event.unified_msg_origin
        kv_sessions = await self._get_kv_sessions()
        if session not in kv_sessions:
            kv_sessions.append(session)
            await self.put_kv_data(self.KV_ENABLED_SESSIONS, kv_sessions)

        latest_items = await self._fetch_latest_news()
        if latest_items and not await self._get_last_pushed_gid():
            await self.put_kv_data(self.KV_LAST_PUSHED_GID, latest_items[0].gid)

        return "CS 新闻推送开启了！"

    async def _disable_push(self, event: AstrMessageEvent) -> str:
        session = event.unified_msg_origin

        if session in self._get_config_sessions():
            return "此群聊推送在插件配置中开启，请在 Web UI 配置页面移除后重试。"

        kv_sessions = await self._get_kv_sessions()
        if session in kv_sessions:
            kv_sessions.remove(session)
            await self.put_kv_data(self.KV_ENABLED_SESSIONS, kv_sessions)
            return "CS 新闻推送被关闭了！"
        return "本群还没有开启过新闻推送！"

    async def _push_loop(self) -> None:
        while True:
            try:
                sleep_seconds = self._seconds_until_next_push()
                logger.info(
                    f"csnews next daily push at {self._push_time_display}, "
                    f"sleeping {sleep_seconds:.0f}s"
                )
                await asyncio.sleep(sleep_seconds)

                for attempt in range(3):
                    try:
                        await self._check_and_push_new_news()
                        break
                    except Exception:
                        logger.error(
                            f"csnews daily push failed (attempt {attempt + 1}/3)",
                            exc_info=True,
                        )
                        if attempt < 2:
                            await asyncio.sleep(60)
            except asyncio.CancelledError:
                raise

    async def _check_and_push_new_news(self) -> None:
        sessions = await self._get_enabled_sessions()
        if not sessions:
            return

        items = await self._fetch_latest_news()
        if not items or not items[0].gid:
            return

        latest_gid = items[0].gid
        last_gid = await self._get_last_pushed_gid()
        if not last_gid:
            await self.put_kv_data(self.KV_LAST_PUSHED_GID, latest_gid)
            return

        new_items = self._items_after_last_gid(items, last_gid)
        if not new_items:
            return

        for item in reversed(new_items):
            await self._push_news_to_sessions(item, sessions)

        await self.put_kv_data(self.KV_LAST_PUSHED_GID, latest_gid)

    async def _push_news_to_sessions(
        self,
        item: NewsItem,
        sessions: list[str],
    ) -> None:
        failed_sessions = [
            session for session in sessions if not await self._push_news(session, item)
        ]
        if failed_sessions:
            logger.warning(
                "csnews failed to push to sessions: " + ", ".join(failed_sessions),
            )

    async def _push_news(self, session: str, item: NewsItem) -> bool:
        try:
            notice_sent = await self._context.send_message(
                session,
                MessageChain([Plain("最爱的cs更新了！")]),
            )
            if not notice_sent:
                return False

            sent = await self._context.send_message(
                session,
                MessageChain(self.formatter.render_components(item)),
            )
        except Exception as e:
            logger.warning(f"csnews failed to push to {session}: {e}")
            return False
        return bool(sent)

    async def _fetch_latest_news(self) -> list[NewsItem]:
        if self._client is None:
            return []
        return await self._client.fetch_latest_news()

    async def _get_cached_or_fetch_all_news(self) -> list[NewsItem]:
        if self._client is None:
            return []

        cached_items = self.storage.read_cached_items()
        if cached_items is not None:
            return self._client.filter_recent(cached_items)

        items = await self._client.fetch_all_recent_news()
        if items:
            self.storage.write_cache(items)
        return items

    async def _get_filtered_news(
        self,
        item_filter: Callable[[NewsItem], bool],
    ) -> list[NewsItem]:
        return [
            item
            for item in await self._get_cached_or_fetch_all_news()
            if item_filter(item)
        ]

    async def _get_yearly_news_items(self) -> list[NewsItem]:
        return await self._get_filtered_news(self._is_news_item)

    async def _get_latest_update_items(self) -> list[NewsItem]:
        if self._client is None:
            return []

        items = await self._client.fetch_news(count=100)
        return [item for item in items if self._is_update_item(item)][
            : self.settings.latest_fetch_count
        ]

    def _get_config_sessions(self) -> list[str]:
        return [
            str(s).strip()
            for s in self.plugin_config.get(self.CONFIG_ENABLED_SESSIONS, [])
            if str(s).strip()
        ]

    async def _get_enabled_sessions(self) -> list[str]:
        config_sessions = self._get_config_sessions()
        kv_sessions = await self._get_kv_sessions()
        return list(dict.fromkeys(config_sessions + kv_sessions))

    async def _get_kv_sessions(self) -> list[str]:
        value = await self.get_kv_data(self.KV_ENABLED_SESSIONS, [])
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, str) and item]

    @property
    def _push_time_display(self) -> str:
        return f"{self._push_hour:02d}:{self._push_minute:02d}"

    def _parse_push_time(self) -> tuple[int, int]:
        raw = self.plugin_config.get(self.CONFIG_PUSH_TIME, "")
        try:
            hour, minute = map(int, str(raw).split(":"))
            return hour, minute
        except (ValueError, AttributeError):
            return self.DEFAULT_PUSH_HOUR, self.DEFAULT_PUSH_MINUTE

    def _seconds_until_next_push(self) -> int:
        now = datetime.now()
        target = now.replace(
            hour=self._push_hour, minute=self._push_minute, second=0, microsecond=0
        )
        if target <= now:
            target += timedelta(days=1)

        jitter = random.randint(0, 60)
        return max(int((target - now).total_seconds()) + jitter, 1)

    async def _get_last_pushed_gid(self) -> str:
        value = await self.get_kv_data(self.KV_LAST_PUSHED_GID, "")
        return str(value or "")

    @staticmethod
    def _parse_command_args(
        event: AstrMessageEvent,
        command_name: str,
    ) -> list[str]:
        text = re.sub(r"\s+", " ", event.get_message_str().strip())
        if not text:
            return []

        parts = text.split(" ")
        if parts and parts[0].lstrip("/!！").lower() == command_name:
            return parts[1:]
        return []

    def _is_update_item(self, item: NewsItem) -> bool:
        return (
            "patchnotes" in item.lowercase_tags
            or item.event_type == self.settings.update_event_type
        )

    def _is_news_item(self, item: NewsItem) -> bool:
        return not self._is_update_item(item)

    @staticmethod
    def _parse_page(args: list[str]) -> int:
        if not args:
            return 1
        try:
            return max(int(args[0]), 1)
        except ValueError:
            return 1

    @staticmethod
    def _items_after_last_gid(items: list[NewsItem], last_gid: str) -> list[NewsItem]:
        new_items: list[NewsItem] = []
        found_last = False
        for item in items:
            if item.gid == last_gid:
                found_last = True
                break
            new_items.append(item)

        if not new_items:
            return []
        if not found_last:
            return new_items[:1]
        return new_items

    @staticmethod
    def _help_text() -> str:
        return "\n".join(
            [
                "CS 新闻插件使用说明：",
                "csnews ls - 查看 CS 新闻列表",
                "csnews ls 页码 - 查看指定页新闻列表",
                "csnews 序号 - 查看新闻正文",
                "csupdates ls - 查看最近十条 CS 更新列表",
                "csupdates 序号 - 查看更新正文",
                "csnews on - 在本群开启新闻自动推送",
                "csnews off - 在本群关闭新闻自动推送",
            ],
        )

    @staticmethod
    def _updates_help_text() -> str:
        return "\n".join(
            [
                "CS 更新查询使用说明：",
                "csupdates ls - 查看最近十条 CS 更新列表",
                "csupdates 序号 - 查看更新正文",
                "自动推送仍通过 csnews on/off 管理。",
            ],
        )

    async def terminate(self) -> None:
        if self._push_task:
            self._push_task.cancel()
            try:
                await self._push_task
            except asyncio.CancelledError:
                pass
        if self._session:
            await self._session.close()
        logger.info("csnews plugin terminated")
