"""Асинхронный публичный парсер веб-версии Telegram-каналов."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

LOGGER = logging.getLogger(__name__)
DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=12, connect=4, sock_read=10)
MAX_CONCURRENCY = 3
MAX_ATTEMPTS = 2

_SELECTORS_PATH = Path(__file__).resolve().parent / "selectors.json"
with _SELECTORS_PATH.open("r", encoding="utf-8") as _selectors_file:
    SELECTORS = json.load(_selectors_file)

USER_AGENTS = [
    f"Mozilla/5.0 ({platform}; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version}.0.0.0 Safari/537.36"
    for platform in ("Windows NT 10.0", "Windows NT 11.0", "Macintosh; Intel Mac OS X 10_15_7", "X11; Linux x86_64")
    for version in (118, 119, 120, 121, 122, 123, 124, 125, 126, 127, 128, 129, 130)
]


@dataclass
class ChannelResult:
    """Результат загрузки одного канала."""

    channel: str
    links: set[str] = field(default_factory=set)
    status: int | None = None
    error: str | None = None


def _delay_range() -> tuple[float, float]:
    """Читает диапазон задержки из окружения."""
    minimum = float(os.getenv("MIN_DELAY", "2"))
    maximum = float(os.getenv("MAX_DELAY", "7"))
    return min(minimum, maximum), max(minimum, maximum)


def _proxy() -> str | None:
    """Выбирает прокси из переменной PROXY_POOL через запятую."""
    values = [item.strip() for item in os.getenv("PROXY_POOL", "").split(",") if item.strip()]
    return random.choice(values) if values else None


def _normalize_link(href: str, base_url: str) -> str | None:
    """Оставляет только абсолютные HTTP(S)-ссылки и отбрасывает ссылки Telegram."""
    absolute = urljoin(base_url, href.strip())
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    excluded_hosts = tuple(str(host).lower() for host in SELECTORS.get("excluded_hosts", ("t.me",)))
    if any(parsed.netloc.lower().endswith(host) for host in excluded_hosts):
        return None
    return absolute


def is_allowed(link: str, allowed_domains: Iterable[str]) -> bool:
    """Проверяет URL по белому списку доменов и их поддоменов."""
    parsed = urlparse(link)
    hostname = (parsed.hostname or "").lower().strip(".")
    if parsed.scheme not in {"http", "https"} or not hostname:
        return False
    for domain in allowed_domains:
        normalized = str(domain).strip().lower().strip(".")
        if normalized and (hostname == normalized or hostname.endswith(f".{normalized}")):
            return True
    return False


def parse_links_from_html(html: str, base_url: str) -> set[str]:
    """Извлекает и дедуплицирует внешние URL из HTML страницы канала."""
    soup = BeautifulSoup(html, "html.parser")
    links: set[str] = set()
    for anchor in soup.select(str(SELECTORS.get("link_selector", "a[href]"))):
        normalized = _normalize_link(str(anchor.get("href", "")), base_url)
        if normalized:
            links.add(normalized)
    return links


async def fetch_channel(
    session: aiohttp.ClientSession,
    channel: str,
    semaphore: asyncio.Semaphore,
    allowed_domains: Iterable[str],
) -> ChannelResult:
    """Загружает канал с повторами и понятным результатом для ошибок HTTP."""
    url = f"https://t.me/s/{channel.lstrip('@')}"
    result = ChannelResult(channel=channel)
    async with semaphore:
        minimum, maximum = _delay_range()
        await asyncio.sleep(random.uniform(minimum, maximum))
        for attempt in range(1, MAX_ATTEMPTS + 1):
            headers = {"User-Agent": random.choice(USER_AGENTS), "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8"}
            try:
                async with session.get(url, headers=headers, proxy=_proxy()) as response:
                    result.status = response.status
                    if response.status == 404:
                        result.error = "канал не найден (404)"
                        LOGGER.warning("Канал %s вернул 404", channel)
                        return result
                    if response.status in {403, 429, 503}:
                        result.error = f"ограничение доступа ({response.status})"
                        LOGGER.warning("Канал %s: HTTP %s, попытка %s/%s", channel, response.status, attempt, MAX_ATTEMPTS)
                        if attempt < MAX_ATTEMPTS:
                            await asyncio.sleep(min(30, 2**attempt + random.random()))
                            continue
                        return result
                    if response.status != 200:
                        result.error = f"HTTP {response.status}"
                        return result
                    html = await response.text(errors="replace")
                    if "captcha" in html.lower() or "robot check" in html.lower():
                        result.error = "обнаружена captcha"
                        LOGGER.error("Для канала %s обнаружена captcha", channel)
                        return result
                    extracted = parse_links_from_html(html, url)
                    result.links = {link for link in extracted if is_allowed(link, allowed_domains)}
                    return result
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                result.error = str(exc)
                if isinstance(exc, aiohttp.ClientConnectorError):
                    result.error = "t.me недоступен из текущей сети"
                    LOGGER.error("Канал %s: t.me недоступен из текущей сети: %s", channel, exc)
                    return result
                if isinstance(exc, asyncio.TimeoutError):
                    result.error = "таймаут подключения к t.me"
                    LOGGER.error("Канал %s: таймаут подключения к t.me", channel)
                    return result
                LOGGER.warning("Ошибка канала %s на попытке %s/%s: %s", channel, attempt, MAX_ATTEMPTS, exc)
                if attempt < MAX_ATTEMPTS:
                    await asyncio.sleep(min(30, 2**attempt + random.random()))
        return result


async def collect_channels(channels: Iterable[str], allowed_domains: Iterable[str]) -> list[ChannelResult]:
    """Параллельно собирает ссылки для списка каналов с ограничением до трех запросов."""
    normalized = [channel.strip().lstrip("@") for channel in channels if channel.strip()]
    normalized_domains = tuple(allowed_domains)
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    async with aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT) as session:
        return await asyncio.gather(
            *(fetch_channel(session, channel, semaphore, normalized_domains) for channel in normalized)
        )
