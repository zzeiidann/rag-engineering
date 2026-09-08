"""Standards-aware discovery and extraction for public documentation websites."""

from __future__ import annotations

import hashlib
import re
import time
import xml.etree.ElementTree as ElementTree
from collections.abc import Iterable
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx

from app.auth.models import ResourceMetadata
from app.models import Document, SourceMetadata

SITEMAP_NAMESPACE = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
SKIP_TAGS = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form"}
BLOCK_TAGS = {"p", "li", "dd", "blockquote"}


def canonicalize_url(value: str) -> str:
    """Remove fragments and query variants without changing the path."""
    parsed = urlsplit(value)
    path = parsed.path or "/"
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, "", ""))


def stable_document_id(url: str) -> str:
    return "sunlife_" + hashlib.sha256(url.encode()).hexdigest()[:24]


def compact_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


@dataclass(frozen=True)
class CrawledPage:
    url: str
    canonical_url: str
    title: str
    description: str | None
    language: str | None
    text: str
    source_last_modified: str | None

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()

    def document(self, country: str, metadata: ResourceMetadata) -> Document:
        return Document(
            id=stable_document_id(self.canonical_url),
            title=self.title[:200],
            text=self.text,
            metadata=metadata,
            source_metadata=SourceMetadata(
                source_type="web",
                source_url=self.url,
                canonical_url=self.canonical_url,
                language=self.language,
                country=country,
                description=self.description,
                source_last_modified=self.source_last_modified,
                content_hash=self.content_hash,
            ),
        )


class MainContentParser(HTMLParser):
    """Extract readable page sections while excluding navigation and boilerplate."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.description: str | None = None
        self.canonical_url: str | None = None
        self.language: str | None = None
        self.noindex = False
        self._ignored_depth = 0
        self._in_title = False
        self._heading_level: int | None = None
        self._heading_parts: list[str] = []
        self._block_tag: str | None = None
        self._block_parts: list[str] = []
        self._table_row: list[str] = []
        self._table_rows: list[list[str]] = []
        self._in_cell = False
        self._cell_parts: list[str] = []
        self._path: list[str] = []
        self.sections: list[tuple[list[str], str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = {key.lower(): value or "" for key, value in attrs}
        tag = tag.lower()
        if tag == "html":
            self.language = attrs_map.get("lang") or self.language
        if tag in SKIP_TAGS:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            name = attrs_map.get("name", "").lower()
            property_name = attrs_map.get("property", "").lower()
            content = compact_text(attrs_map.get("content", ""))
            if name == "description" and content:
                self.description = content
            if name == "robots" and "noindex" in content.lower():
                self.noindex = True
            if property_name == "og:description" and content and not self.description:
                self.description = content
        elif tag == "link" and "canonical" in attrs_map.get("rel", "").lower():
            self.canonical_url = attrs_map.get("href") or self.canonical_url
        elif len(tag) == 2 and tag.startswith("h") and tag[1].isdigit():
            self._flush_block()
            self._heading_level = int(tag[1])
            self._heading_parts = []
        elif tag in BLOCK_TAGS and self._block_tag is None:
            self._block_tag, self._block_parts = tag, []
        elif tag == "tr":
            self._table_row = []
        elif tag in {"td", "th"}:
            self._in_cell, self._cell_parts = True, []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in SKIP_TAGS:
            self._ignored_depth = max(0, self._ignored_depth - 1)
            return
        if self._ignored_depth:
            return
        if tag == "title":
            self._in_title = False
        elif self._heading_level and tag == f"h{self._heading_level}":
            heading = compact_text(" ".join(self._heading_parts))
            if heading:
                self._path[self._heading_level - 1 :] = [heading]
            self._heading_level, self._heading_parts = None, []
        elif tag == self._block_tag:
            self._flush_block()
        elif tag in {"td", "th"} and self._in_cell:
            value = compact_text(" ".join(self._cell_parts))
            if value:
                self._table_row.append(value)
            self._in_cell, self._cell_parts = False, []
        elif tag == "tr" and self._table_row:
            self._table_rows.append(self._table_row)
            self._table_row = []
        elif tag == "table":
            for row in self._table_rows:
                self.sections.append((self._path.copy(), " | ".join(row)))
            self._table_rows = []

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        value = compact_text(data)
        if not value:
            return
        if self._in_title:
            self.title_parts.append(value)
        if self._heading_level:
            self._heading_parts.append(value)
        elif self._in_cell:
            self._cell_parts.append(value)
        elif self._block_tag:
            self._block_parts.append(value)

    def _flush_block(self) -> None:
        value = compact_text(" ".join(self._block_parts))
        if value:
            self.sections.append((self._path.copy(), value))
        self._block_tag, self._block_parts = None, []

    def page(self, fetched_url: str, source_last_modified: str | None) -> CrawledPage | None:
        self._flush_block()
        if self.noindex:
            return None
        groups: list[tuple[tuple[str, ...], list[str]]] = []
        for path, content in self.sections:
            key = tuple(path)
            if groups and groups[-1][0] == key:
                groups[-1][1].append(content)
            else:
                groups.append((key, [content]))
        markdown: list[str] = []
        for section_path, values in groups:
            for level, heading in enumerate(section_path, start=1):
                marker = "#" * min(level, 6)
                line = f"{marker} {heading}"
                if not markdown or markdown[-1] != line:
                    markdown.append(line)
            markdown.extend(values)
        text = "\n\n".join(markdown).strip()
        if len(text) < 120:
            return None
        title = compact_text(" ".join(self.title_parts)) or (groups[0][0][-1] if groups else "")
        if not title:
            title = urlsplit(fetched_url).path.strip("/") or "Sun Life page"
        canonical = canonicalize_url(urljoin(fetched_url, self.canonical_url or fetched_url))
        return CrawledPage(
            url=canonicalize_url(fetched_url),
            canonical_url=canonical,
            title=title,
            description=self.description,
            language=self.language,
            text=text,
            source_last_modified=source_last_modified,
        )


class WebsiteCrawler:
    """Crawl an explicit public URL scope from sitemap URLs, respecting robots.txt."""

    def __init__(
        self,
        seed_url: str,
        allowed_path_prefix: str,
        request_delay_seconds: float = 0.5,
        user_agent: str = "SunLifeKnowledgeRAG/0.1 (local portfolio project)",
    ) -> None:
        self.seed_url = canonicalize_url(seed_url)
        self.origin = urlunsplit((*urlsplit(self.seed_url)[:2], "", "", ""))
        self.allowed_path_prefix = allowed_path_prefix.rstrip("/") + "/"
        self.request_delay_seconds = request_delay_seconds
        self.user_agent = user_agent
        self.client = httpx.Client(
            headers={"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml"},
            follow_redirects=True,
            timeout=30,
        )
        self.robots = self._load_robots()

    def close(self) -> None:
        self.client.close()

    def _load_robots(self) -> RobotFileParser:
        robots_url = urljoin(self.origin + "/", "robots.txt")
        response = self.client.get(robots_url)
        response.raise_for_status()
        parser = RobotFileParser()
        parser.set_url(robots_url)
        parser.parse(response.text.splitlines())
        return parser

    def allowed(self, url: str) -> bool:
        parsed = urlsplit(url)
        origin = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
        return (
            parsed.scheme == "https"
            and origin == self.origin
            and not parsed.query
            and parsed.path.startswith(self.allowed_path_prefix)
            and self.robots.can_fetch(self.user_agent, url)
        )

    def sitemap_urls(self, sitemap_url: str, max_urls: int) -> list[tuple[str, str | None]]:
        discovered: list[tuple[str, str | None]] = []
        pending = [sitemap_url]
        seen_sitemaps: set[str] = set()
        while pending and len(discovered) < max_urls:
            current = canonicalize_url(pending.pop(0))
            if current in seen_sitemaps:
                continue
            seen_sitemaps.add(current)
            response = self.client.get(current)
            response.raise_for_status()
            root = ElementTree.fromstring(response.content)
            if root.tag.endswith("sitemapindex"):
                for loc in root.findall(".//sm:sitemap/sm:loc", SITEMAP_NAMESPACE):
                    if loc.text:
                        pending.append(loc.text.strip())
                continue
            for item in root.findall(".//sm:url", SITEMAP_NAMESPACE):
                loc_element = item.find("sm:loc", SITEMAP_NAMESPACE)
                lastmod = item.find("sm:lastmod", SITEMAP_NAMESPACE)
                if loc_element is None or not loc_element.text:
                    continue
                url = canonicalize_url(loc_element.text.strip())
                if self.allowed(url):
                    discovered.append(
                        (
                            url,
                            lastmod.text.strip() if lastmod is not None and lastmod.text else None,
                        )
                    )
                    if len(discovered) >= max_urls:
                        break
        return discovered

    def crawl(self, sitemap_url: str, max_pages: int) -> Iterable[CrawledPage]:
        seen_canonicals: set[str] = set()
        for url, lastmod in self.sitemap_urls(sitemap_url, max_pages):
            try:
                response = self.client.get(url)
            except httpx.HTTPError:
                time.sleep(self.request_delay_seconds)
                continue
            if response.status_code != 200 or "html" not in response.headers.get(
                "content-type", ""
            ):
                continue
            parser = MainContentParser()
            parser.feed(response.text)
            page = parser.page(str(response.url), lastmod)
            if (
                page
                and self.allowed(page.canonical_url)
                and page.canonical_url not in seen_canonicals
            ):
                seen_canonicals.add(page.canonical_url)
                yield page
            time.sleep(self.request_delay_seconds)
