"""Работа с SQLite для агрегатора ссылок Telegram."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

DEFAULT_CHANNELS = (
    "machinelearning_ru",
    "vc_ai",
    "shir_man",
    "ai_jobs",
    "neural_ch",
    "open_ai_news",
)

DEFAULT_ALLOWED_DOMAINS = (
    "github.com",
    "huggingface.co",
    "arxiv.org",
    "modelscope.ai",
    "gitverse.ru",
)


def _database_path() -> Path:
    """Возвращает путь к БД из окружения или значение по умолчанию."""
    configured = os.getenv("DATABASE_PATH", "data/telegram_links.sqlite3")
    path = Path(configured)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _now() -> str:
    """Возвращает локальное время в формате, удобном для сортировки."""
    return datetime.now().strftime("%Y-%m-%d %H:%M")


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    """Открывает соединение SQLite с безопасным управлением транзакцией."""
    connection = sqlite3.connect(_database_path())
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db() -> None:
    """Создает таблицы и заполняет БД стартовым пулом каналов один раз."""
    with _connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel TEXT NOT NULL,
                link TEXT NOT NULL UNIQUE,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                post_count INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                added_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS allowed_domains (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                domain TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS collection_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL,
                new_links INTEGER NOT NULL DEFAULT 0,
                updated_links INTEGER NOT NULL DEFAULT 0,
                errors INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_links_first_seen ON links(first_seen);
            CREATE INDEX IF NOT EXISTS idx_links_last_seen ON links(last_seen);
            """
        )
        existing = connection.execute("SELECT COUNT(*) FROM channels").fetchone()[0]
        if existing == 0:
            connection.executemany(
                "INSERT INTO channels(name, added_at) VALUES (?, ?)",
                [(channel, _now()) for channel in DEFAULT_CHANNELS],
            )
        domain_count = connection.execute("SELECT COUNT(*) FROM allowed_domains").fetchone()[0]
        if domain_count == 0:
            connection.executemany(
                "INSERT INTO allowed_domains(domain) VALUES (?)",
                [(domain,) for domain in DEFAULT_ALLOWED_DOMAINS],
            )


def add_channel(name: str) -> bool:
    """Добавляет канал без символа @; возвращает False при дубликате."""
    normalized = name.strip().lstrip("@").lower()
    if not normalized or any(char.isspace() for char in normalized):
        raise ValueError("Имя канала должно быть непустым и не содержать пробелы")
    with _connect() as connection:
        cursor = connection.execute(
            "INSERT OR IGNORE INTO channels(name, added_at) VALUES (?, ?)",
            (normalized, _now()),
        )
        return cursor.rowcount == 1


def remove_channel(name: str) -> bool:
    """Удаляет канал из списка мониторинга, не удаляя историю ссылок."""
    with _connect() as connection:
        cursor = connection.execute("DELETE FROM channels WHERE name = ?", (name.strip().lstrip("@"),))
        return cursor.rowcount == 1


def get_all_channels() -> list[str]:
    """Возвращает каналы в алфавитном порядке."""
    with _connect() as connection:
        rows = connection.execute("SELECT name FROM channels ORDER BY name").fetchall()
    return [str(row["name"]) for row in rows]


def _normalize_domain(domain: str) -> str:
    """Нормализует домен из UI, URL или записи окружения."""
    normalized = domain.strip().lower()
    if "://" in normalized:
        normalized = normalized.split("://", 1)[1]
    normalized = normalized.split("/", 1)[0].split(":", 1)[0].strip(".")
    if not normalized or any(char.isspace() for char in normalized) or "." not in normalized:
        raise ValueError("Домен должен быть в формате example.com без пробелов")
    return normalized


def add_allowed_domain(domain: str) -> bool:
    """Добавляет домен в белый список; возвращает False для дубликата."""
    normalized = _normalize_domain(domain)
    with _connect() as connection:
        cursor = connection.execute(
            "INSERT OR IGNORE INTO allowed_domains(domain) VALUES (?)",
            (normalized,),
        )
        return cursor.rowcount == 1


def remove_allowed_domain(domain: str) -> bool:
    """Удаляет домен из белого списка, не затрагивая историю ссылок."""
    normalized = _normalize_domain(domain)
    with _connect() as connection:
        cursor = connection.execute("DELETE FROM allowed_domains WHERE domain = ?", (normalized,))
        return cursor.rowcount == 1


def get_allowed_domains() -> list[str]:
    """Возвращает белый список доменов в алфавитном порядке."""
    with _connect() as connection:
        rows = connection.execute("SELECT domain FROM allowed_domains ORDER BY domain").fetchall()
    return [str(row["domain"]) for row in rows]


def _is_domain_allowed(link: str, allowed_domains: tuple[str, ...]) -> bool:
    """Проверяет URL по домену или его поддомену для выдачи чистой истории."""
    hostname = (urlparse(link).hostname or "").lower().strip(".")
    return any(hostname == domain or hostname.endswith(f".{domain}") for domain in allowed_domains)


def add_link(channel: str, link: str, seen_at: str | None = None) -> bool:
    """Добавляет новую ссылку; False означает, что URL уже существует."""
    timestamp = seen_at or _now()
    with _connect() as connection:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO links(channel, link, first_seen, last_seen, post_count)
            VALUES (?, ?, ?, ?, 1)
            """,
            (channel, link, timestamp, timestamp),
        )
        return cursor.rowcount == 1


def update_link(channel: str, link: str, seen_at: str | None = None) -> bool:
    """Обновляет last_seen и счетчик появления существующей ссылки."""
    timestamp = seen_at or _now()
    with _connect() as connection:
        cursor = connection.execute(
            """
            UPDATE links
            SET channel = ?, last_seen = ?, post_count = post_count + 1
            WHERE link = ?
            """,
            (channel, timestamp, link),
        )
        return cursor.rowcount == 1


def get_all_links(allowed_only: bool = True) -> list[dict[str, object]]:
    """Возвращает историю от новых к старым; по умолчанию только белый список."""
    with _connect() as connection:
        rows = connection.execute(
            "SELECT channel, link, first_seen, last_seen, post_count FROM links ORDER BY first_seen DESC"
        ).fetchall()
    links = [dict(row) for row in rows]
    if not allowed_only:
        return links
    allowed_domains = tuple(get_allowed_domains())
    return [row for row in links if _is_domain_allowed(str(row["link"]), allowed_domains)]


def get_recent_links(limit: int = 50, allowed_only: bool = True) -> list[dict[str, object]]:
    """Возвращает последние URL; по умолчанию только из белого списка."""
    safe_limit = max(1, min(int(limit), 5000))
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT channel, link, first_seen, last_seen, post_count
            FROM links ORDER BY first_seen DESC
            """,
        ).fetchall()
    links = [dict(row) for row in rows]
    if not allowed_only:
        return links
    allowed_domains = tuple(get_allowed_domains())
    return [row for row in links if _is_domain_allowed(str(row["link"]), allowed_domains)][:safe_limit]


def get_new_links_since(date: str, allowed_only: bool = True) -> list[dict[str, object]]:
    """Возвращает новые ссылки; по умолчанию только из белого списка."""
    with _connect() as connection:
        rows = connection.execute(
            "SELECT channel, link, first_seen, last_seen, post_count FROM links WHERE first_seen >= ? ORDER BY first_seen DESC",
            (date,),
        ).fetchall()
    links = [dict(row) for row in rows]
    if not allowed_only:
        return links
    allowed_domains = tuple(get_allowed_domains())
    return [row for row in links if _is_domain_allowed(str(row["link"]), allowed_domains)]


def record_collection_run(started_at: str, finished_at: str, new_links: int, updated_links: int, errors: int) -> None:
    """Сохраняет сводку запуска для истории и диагностики."""
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO collection_runs(started_at, finished_at, new_links, updated_links, errors)
            VALUES (?, ?, ?, ?, ?)
            """,
            (started_at, finished_at, new_links, updated_links, errors),
        )


def get_last_run() -> dict[str, object] | None:
    """Возвращает последний запуск или None, если сбор еще не выполнялся."""
    with _connect() as connection:
        row = connection.execute("SELECT * FROM collection_runs ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None
