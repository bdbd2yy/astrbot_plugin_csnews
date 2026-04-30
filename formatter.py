from __future__ import annotations

import html
import re
import time

from astrbot.api.message_components import BaseMessageComponent, Image, Plain

from .config import CsNewsSettings
from .models import NewsItem


class NewsFormatter:
    refs_marker = "\n\nrefs: "

    def __init__(self, settings: CsNewsSettings) -> None:
        self.settings = settings

    def render_list(
        self,
        *,
        page: int,
        items: list[NewsItem],
        title: str,
        command_name: str,
        empty_text: str,
    ) -> str:
        if not items:
            return empty_text

        max_page = max((len(items) - 1) // self.settings.list_page_size + 1, 1)
        page = min(max(page, 1), max_page)
        start = (page - 1) * self.settings.list_page_size
        end = min(start + self.settings.list_page_size, len(items))

        lines = [f"{title}（第 {page}/{max_page} 页，共 {len(items)} 条）"]
        for offset, item in enumerate(items[start:end], start=start + 1):
            lines.append(
                f"{offset}. {self.format_date(item.date)} "
                f"{self.safe_text(item.title or 'Untitled')} - {self.category(item)}"
            )

        lines.append(f"发送 {command_name} 序号 查看正文，例如：{command_name} 1")
        if page < max_page:
            lines.append(f"发送 {command_name} ls {page + 1} 查看下一页")
        return "\n".join(lines)

    def render_message(self, item: NewsItem) -> str:
        content = self.clean_contents(item.contents)
        if not content:
            content = "暂无正文内容，请打开 Counter-Strike 官网链接查看。"
        if len(content) > self.settings.detail_max_chars:
            content = (
                content[: self.settings.detail_max_chars].rstrip()
                + "\n\n（内容过长，已截断，请打开 Counter-Strike 官网链接查看完整内容）"
            )

        title = self.safe_text(item.title or "Untitled")
        url = item.url or self.settings.updates_url
        return (
            f"{self.format_detail_date(item.date)} | {self.category(item)}"
            f"\n\n= {title}\n\n{content}\n\nrefs: {url}"
        )

    def render_components(self, item: NewsItem) -> list[BaseMessageComponent]:
        text = self.render_message(item)
        image_urls = self.extract_image_urls(item.contents)
        if not image_urls:
            return [Plain(text)]

        if self.refs_marker not in text:
            return [Plain(text), *(Image(file=url, url=url) for url in image_urls)]

        body_text, refs = text.rsplit(self.refs_marker, maxsplit=1)
        return [
            Plain(body_text),
            *(Image(file=url, url=url) for url in image_urls),
            Plain(f"{self.refs_marker}{refs}"),
        ]

    def category(self, item: NewsItem) -> str:
        feedlabel = self.safe_text(item.feedlabel)
        if "patchnotes" in item.lowercase_tags:
            return "补丁说明"
        if item.event_type == self.settings.update_event_type:
            return "更新公告"
        if item.event_type == self.settings.news_event_type:
            return "新闻"
        if feedlabel:
            return self._translate_category(feedlabel)
        if item.feedname.lower() == "counter-strike_official":
            return "官方公告"
        if item.feed_type == 0:
            return "外部文章"
        return "官方新闻"

    def clean_contents(self, raw: str) -> str:
        text = self.normalize_markup(raw)
        replacements: tuple[tuple[str, str, int], ...] = (
            (r"\[Pasted\s+~\d+\s+lines?\]", "", re.IGNORECASE),
            (r"\[img[^\]]*\].*?\[/img\]", "\n", re.IGNORECASE | re.DOTALL),
            (r"\[video[^\]]*\].*?\[/video\]", "\n", re.IGNORECASE | re.DOTALL),
            (r"<br\s*/?>", "\n", re.IGNORECASE),
            (r"</p\s*>", "\n", re.IGNORECASE),
            (r"<[^>]+>", "", 0),
            (r"\[\*\]", "\n- ", 0),
            (r"\[/\*\]", "", 0),
            (r"\[url=([^\]]+)\](.*?)\[/url\]", r"\2 (\1)", re.IGNORECASE | re.DOTALL),
            (r"\[url\](.*?)\[/url\]", r"\1", re.IGNORECASE | re.DOTALL),
            (
                r"\[/?(?:p|h\d|b|i|u|strike|list|olist|quote|code|table|tr|td|th|img|video|previewyoutube|hr)[^\]]*\]",
                "\n",
                re.IGNORECASE,
            ),
            (r"(?m)^\s*\[\s*([^\[\]\n]+?)\s*\]\s*$", r"[\1]", 0),
            (r"\[/?[a-zA-Z0-9_=:/. ,#-]+\]", "", 0),
        )
        for pattern, replacement, flags in replacements:
            text = re.sub(pattern, replacement, text, flags=flags)

        text = html.unescape(text)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"(?m)^-\s*\n\s*(?=\S)", "- ", text)
        text = "\n".join(line.strip() for line in text.splitlines())
        text = re.sub(r"\n{3,}", "\n\n", text)
        return self._format_patch_note_text(text.strip())

    def normalize_markup(self, raw: str) -> str:
        return html.unescape(
            raw.replace("\\[", "[").replace("\\]", "]").replace("\\/", "/")
        )

    def extract_image_urls(self, raw: str) -> list[str]:
        text = self.normalize_markup(raw)
        urls = [
            match.group(1)
            for match in re.finditer(
                r"\[img[^\]]*\](.*?)\[/img\]",
                text,
                flags=re.IGNORECASE | re.DOTALL,
            )
        ]

        quoted_url = r'"([^"]+)"|\'([^\']+)\'|([^\s\]]+)'
        urls.extend(
            self._first_group(match)
            for match in re.finditer(
                rf"\[(?:img|video)[^\]]*(?:src|poster)=(?:{quoted_url})",
                text,
                flags=re.IGNORECASE,
            )
        )
        urls.extend(
            self._first_group(match)
            for match in re.finditer(
                rf"<img\b[^>]*\bsrc=(?:{quoted_url})",
                text,
                flags=re.IGNORECASE,
            )
        )

        normalized_urls: list[str] = []
        seen: set[str] = set()
        for url in urls:
            normalized_url = self._normalize_image_url(url)
            if normalized_url and normalized_url not in seen:
                normalized_urls.append(normalized_url)
                seen.add(normalized_url)
        return normalized_urls

    @staticmethod
    def format_detail_date(timestamp: int) -> str:
        if timestamp <= 0:
            return "未知时间"
        return time.strftime("%y.%m.%d", time.localtime(timestamp))

    @staticmethod
    def format_date(timestamp: int) -> str:
        if timestamp <= 0:
            return "未知时间"
        return time.strftime("%y/%m/%d", time.localtime(timestamp))

    @staticmethod
    def safe_text(value: str) -> str:
        return re.sub(r"\s+", " ", html.unescape(value)).strip()

    @staticmethod
    def _first_group(match: re.Match[str]) -> str:
        return next(group for group in match.groups() if group)

    @staticmethod
    def _translate_category(category: str) -> str:
        category_map = {
            "Community Announcements": "社区公告",
            "Counter-Strike Official": "官方公告",
            "External Article": "外部文章",
            "Patch Notes": "补丁说明",
        }
        return category_map.get(category, category)

    def _format_patch_note_text(self, text: str) -> str:
        formatted_lines: list[str] = []
        previous_kind = ""
        next_plain_heading_is_subsection = False

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            kind = self._patch_note_line_kind(line)
            if kind == "section":
                if formatted_lines:
                    formatted_lines.append("")
                section_line = self._format_patch_note_section(line)
                formatted_lines.append(section_line)
                previous_kind = kind
                next_plain_heading_is_subsection = section_line == "[地图]"
                continue

            if kind == "bullet":
                formatted_lines.append(line)
                previous_kind = kind
                continue

            if next_plain_heading_is_subsection:
                if formatted_lines:
                    formatted_lines.append("")
                formatted_lines.append(line)
                previous_kind = "subsection"
                next_plain_heading_is_subsection = False
                continue

            if previous_kind not in {"section", "subsection"} and formatted_lines:
                formatted_lines.append("")
            formatted_lines.append(line)
            previous_kind = "text"

        return "\n".join(formatted_lines).strip()

    def _patch_note_line_kind(self, line: str) -> str:
        if line.startswith("- "):
            return "bullet"
        if re.fullmatch(r"\[[^\[\]]+\]", line):
            return "section"
        if line in self.settings.patch_note_section_titles:
            return "section"
        return "text"

    @staticmethod
    def _format_patch_note_section(line: str) -> str:
        return f"[{line.strip('[]')}]"

    def _normalize_image_url(self, url: str) -> str:
        normalized = html.unescape(url).strip().strip("'\"").replace("\\/", "/")
        if normalized.startswith("{STEAM_CLAN_IMAGE}"):
            normalized = normalized.replace(
                "{STEAM_CLAN_IMAGE}",
                self.settings.steam_clan_image_base,
                1,
            )
        if normalized.startswith("//"):
            normalized = f"https:{normalized}"
        if normalized.startswith(("http://", "https://")):
            return normalized
        return ""
