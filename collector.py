"""CLI-сборщик для запуска вручную или через Cron."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path

from database import add_link, get_all_channels, get_allowed_domains, init_db, record_collection_run, update_link
from parser import ChannelResult, collect_channels

LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.FileHandler(LOG_DIR / "collector.log", encoding="utf-8"), logging.StreamHandler()],
)
LOGGER = logging.getLogger(__name__)


def _timestamp() -> str:
    """Возвращает timestamp запуска в едином формате."""
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def persist_results(results: list[ChannelResult], seen_at: str) -> dict[str, int]:
    """Сохраняет результат парсинга с дедупликацией по URL."""
    new_count = 0
    updated_count = 0
    error_count = 0
    for result in results:
        if result.error:
            error_count += 1
            LOGGER.warning("Канал %s пропущен: %s", result.channel, result.error)
        for link in result.links:
            if add_link(result.channel, link, seen_at):
                new_count += 1
            else:
                update_link(result.channel, link, seen_at)
                updated_count += 1
    return {"new": new_count, "updated": updated_count, "errors": error_count}


async def run_collection() -> dict[str, int | str]:
    """Читает каналы из БД, собирает ссылки и пишет сводку запуска."""
    init_db()
    started_at = _timestamp()
    channels = get_all_channels()
    allowed_domains = get_allowed_domains()
    results = await collect_channels(channels, allowed_domains)
    summary = persist_results(results, started_at)
    finished_at = _timestamp()
    record_collection_run(started_at, finished_at, summary["new"], summary["updated"], summary["errors"])
    LOGGER.info("Сбор завершен: новых=%s, обновлено=%s, ошибок=%s", summary["new"], summary["updated"], summary["errors"])
    return {**summary, "started_at": started_at, "finished_at": finished_at}


def main() -> None:
    """Точка входа для `python collector.py`."""
    asyncio.run(run_collection())


if __name__ == "__main__":
    main()
