"""Streamlit-интерфейс управления агрегатором ссылок Telegram."""

from __future__ import annotations

import asyncio
import io
from datetime import datetime

import pandas as pd
import streamlit as st

from collector import persist_results
from database import (
    add_channel,
    add_allowed_domain,
    get_all_channels,
    get_allowed_domains,
    get_all_links,
    get_last_run,
    get_new_links_since,
    get_recent_links,
    init_db,
    record_collection_run,
    remove_allowed_domain,
    remove_channel,
)
from parser import collect_channels

TEXT = {
    "ru": {
        "page_title": "Агрегатор ссылок Telegram",
        "language": "Язык интерфейса",
        "channels": "Каналы",
        "channel_name": "Имя канала без @",
        "add_channel": "Добавить канал",
        "channel_added": "Канал добавлен",
        "channel_exists": "Такой канал уже есть",
        "remove_channel": "Удалить @{channel}",
        "domains": "Белый список доменов",
        "domain_name": "Домен без протокола",
        "add_domain": "Добавить домен",
        "domain_added": "Домен добавлен",
        "domain_exists": "Такой домен уже есть",
        "remove_domain": "Удалить {domain}",
        "title": "🔗 Агрегатор ссылок Telegram",
        "caption": "Публичные AI-каналы → чистая история полезных ссылок",
        "collector": "Состояние коллектора",
        "total_links": "Всего ссылок в истории",
        "new_links": "Новых ссылок за последний сбор",
        "collect": "🚀 Собрать ссылки сейчас",
        "collecting": "Собираю ссылки из публичных каналов...",
        "complete": "Сбор завершен",
        "failed": "Сбор завершился с ошибкой",
        "summary": "Новых: {new} · Обновлено: {updated} · Ошибок: {errors}",
        "collect_error": "Не удалось выполнить сбор: {error}",
        "recent": "Последние 50 ссылок",
        "download_all": "📥 Скачать всю историю (CSV)",
        "download_new": "📥 Скачать только новые (CSV)",
        "channel_column": "Канал",
        "link_column": "Ссылка",
        "first_seen_column": "Первое обнаружение",
    },
    "en": {
        "page_title": "Telegram Link Aggregator",
        "language": "Interface language",
        "channels": "Channels",
        "channel_name": "Channel name without @",
        "add_channel": "Add channel",
        "channel_added": "Channel added",
        "channel_exists": "This channel already exists",
        "remove_channel": "Remove @{channel}",
        "domains": "Domain allowlist",
        "domain_name": "Domain without protocol",
        "add_domain": "Add domain",
        "domain_added": "Domain added",
        "domain_exists": "This domain already exists",
        "remove_domain": "Remove {domain}",
        "title": "🔗 Telegram Link Aggregator",
        "caption": "Public AI channels → clean history of useful links",
        "collector": "Collector status",
        "total_links": "Total links in history",
        "new_links": "New links in the last collection",
        "collect": "🚀 Collect links now",
        "collecting": "Collecting links from public channels...",
        "complete": "Collection completed",
        "failed": "Collection finished with an error",
        "summary": "New: {new} · Updated: {updated} · Errors: {errors}",
        "collect_error": "Collection failed: {error}",
        "recent": "Latest 50 links",
        "download_all": "📥 Download all history (CSV)",
        "download_new": "📥 Download new links only (CSV)",
        "channel_column": "Channel",
        "link_column": "Link",
        "first_seen_column": "First seen",
    },
}

st.set_page_config(page_title=TEXT["ru"]["page_title"], page_icon="🔗", layout="wide")

if "language" not in st.session_state:
    st.session_state["language"] = "ru"
init_db()


def _timestamp() -> str:
    """Возвращает время запуска в формате SQLite."""
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _csv_bytes(rows: list[dict[str, object]]) -> bytes:
    """Формирует UTF-8 CSV с BOM для корректного открытия в Excel."""
    frame = pd.DataFrame(rows)
    buffer = io.StringIO()
    frame.to_csv(buffer, index=False)
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")


def _run_collection() -> dict[str, int | str]:
    """Запускает асинхронный сбор в текущем Streamlit-потоке."""
    started_at = _timestamp()
    results = asyncio.run(collect_channels(get_all_channels(), get_allowed_domains()))
    summary = persist_results(results, started_at)
    finished_at = _timestamp()
    record_collection_run(started_at, finished_at, summary["new"], summary["updated"], summary["errors"])
    return {**summary, "started_at": started_at, "finished_at": finished_at}


with st.sidebar:
    current_language = str(st.session_state["language"])
    language = st.selectbox(
        TEXT[current_language]["language"],
        options=("ru", "en"),
        format_func=lambda value: "Русский" if value == "ru" else "English",
        key="language",
    )
    text = TEXT[language]
    st.header(text["channels"])
    channel_input = st.text_input(text["channel_name"], placeholder="ai_agents")
    if st.button(text["add_channel"], width="stretch"):
        try:
            if add_channel(channel_input):
                st.success(text["channel_added"])
                st.rerun()
            else:
                st.warning(text["channel_exists"])
        except ValueError as exc:
            st.error(str(exc))
    st.divider()
    for channel in get_all_channels():
        left, right = st.columns([4, 1])
        left.write(f"@{channel}")
        if right.button("🗑️", key=f"remove_{channel}", help=text["remove_channel"].format(channel=channel)):
            remove_channel(channel)
            st.rerun()
    st.divider()
    st.header(text["domains"])
    domain_input = st.text_input(text["domain_name"], placeholder="habr.com")
    if st.button(text["add_domain"], width="stretch"):
        try:
            if add_allowed_domain(domain_input):
                st.success(text["domain_added"])
                st.rerun()
            else:
                st.warning(text["domain_exists"])
        except ValueError as exc:
            st.error(str(exc))
    for domain in get_allowed_domains():
        left, right = st.columns([4, 1])
        left.write(domain)
        if right.button("🗑️", key=f"remove_domain_{domain}", help=text["remove_domain"].format(domain=domain)):
            remove_allowed_domain(domain)
            st.rerun()

st.title(text["title"])
st.caption(text["caption"])
st.subheader(text["collector"])
all_links = get_all_links()
last_run = get_last_run()
new_last_run = int(last_run["new_links"]) if last_run else 0
metric_left, metric_right = st.columns(2)
metric_left.metric(text["total_links"], len(all_links))
metric_right.metric(text["new_links"], new_last_run)

if st.button(text["collect"], type="primary", width="stretch"):
    with st.status(text["collecting"], expanded=True) as status:
        try:
            summary = _run_collection()
            st.session_state["last_collection_started"] = summary["started_at"]
            status.update(label=text["complete"], state="complete")
            st.success(text["summary"].format(**summary))
            st.rerun()
        except Exception as exc:
            status.update(label=text["failed"], state="error")
            st.error(text["collect_error"].format(error=exc))

st.subheader(text["recent"])
recent = get_recent_links(50)
recent_frame = pd.DataFrame(recent, columns=["channel", "link", "first_seen", "last_seen", "post_count"])
recent_frame = recent_frame.rename(
    columns={
        "channel": text["channel_column"],
        "link": text["link_column"],
        "first_seen": text["first_seen_column"],
    }
)
st.dataframe(
    recent_frame[[text["channel_column"], text["link_column"], text["first_seen_column"]]],
    width="stretch",
    hide_index=True,
)

st.download_button(text["download_all"], data=_csv_bytes(all_links), file_name="telegram_links_history.csv", mime="text/csv")
since = st.session_state.get("last_collection_started")
new_rows = get_new_links_since(str(since)) if since else []
st.download_button(text["download_new"], data=_csv_bytes(new_rows), file_name="telegram_links_new.csv", mime="text/csv", disabled=not bool(new_rows))
