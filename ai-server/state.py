"""
state.py — tracks which image files have been embedded, for both pipelines.

Schema
------
person_crops          — crop files fed into the person re-ID / clustering pipeline
    image_path   TEXT PRIMARY KEY
    status       TEXT    — 'embedded' | 'retry'
    retry_count  INTEGER
    processed_at TEXT    — ISO-8601 timestamp

search_embeddings     — full CCTV frames fed into the semantic search pipeline
    image_path   TEXT PRIMARY KEY
    status       TEXT    — 'embedded' | 'retry'
    retry_count  INTEGER
    processed_at TEXT    — ISO-8601 timestamp

The two tables are intentionally identical in structure — they track the same
kind of state for two independent embedding pipelines. Keeping them separate
means a file can be embedded in one pipeline but still pending in the other,
and retry queues never mix.
"""

import sqlite3
import threading
import os
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

DB_PATH = os.environ.get("STATE_DB_PATH", "/var/cctv/state.db")

# One connection per thread — SQLite connections are not thread-safe
_local = threading.local()


def _conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn"):
        _local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _local.conn.execute("PRAGMA journal_mode=WAL")    # safe concurrent writes
        _local.conn.execute("PRAGMA synchronous=NORMAL")  # fast enough, crash-safe
        _local.conn.executescript("""
            CREATE TABLE IF NOT EXISTS person_crops (
                image_path   TEXT PRIMARY KEY,
                status       TEXT    NOT NULL DEFAULT 'embedded',
                retry_count  INTEGER NOT NULL DEFAULT 0,
                processed_at TEXT    NOT NULL
            );
            CREATE TABLE IF NOT EXISTS search_embeddings (
                image_path   TEXT PRIMARY KEY,
                status       TEXT    NOT NULL DEFAULT 'embedded',
                retry_count  INTEGER NOT NULL DEFAULT 0,
                processed_at TEXT    NOT NULL
            );
        """)
        _local.conn.commit()
    return _local.conn


# ── Shared helpers (not public) ───────────────────────────────────────────────

def _already_embedded(table: str, image_path: str) -> bool:
    row = _conn().execute(
        f"SELECT 1 FROM {table} WHERE image_path = ? AND status = 'embedded'",
        (image_path,)
    ).fetchone()
    return row is not None


def _mark_embedded(table: str, image_path: str) -> None:
    _conn().execute(f"""
        INSERT INTO {table} (image_path, status, retry_count, processed_at)
        VALUES (?, 'embedded', 0, ?)
        ON CONFLICT(image_path) DO UPDATE SET
            status       = 'embedded',
            processed_at = excluded.processed_at
    """, (image_path, datetime.now().isoformat()))
    _conn().commit()


def _mark_for_retry(table: str, image_path: str) -> None:
    _conn().execute(f"""
        INSERT INTO {table} (image_path, status, retry_count, processed_at)
        VALUES (?, 'retry', 1, ?)
        ON CONFLICT(image_path) DO UPDATE SET
            status       = 'retry',
            retry_count  = retry_count + 1,
            processed_at = excluded.processed_at
    """, (image_path, datetime.now().isoformat()))
    _conn().commit()


def _get_retry_queue(table: str) -> list[str]:
    rows = _conn().execute(
        f"SELECT image_path FROM {table} WHERE status = 'retry'"
    ).fetchall()
    return [r[0] for r in rows]


def _clear_retry(table: str, image_path: str) -> None:
    _conn().execute(
        f"DELETE FROM {table} WHERE image_path = ? AND status = 'retry'",
        (image_path,)
    )
    _conn().commit()


# ── Person crops API ──────────────────────────────────────────────────────────

def already_embedded(image_path: str) -> bool:
    return _already_embedded("person_crops", image_path)

def mark_embedded(image_path: str) -> None:
    _mark_embedded("person_crops", image_path)

def mark_for_retry(image_path: str) -> None:
    _mark_for_retry("person_crops", image_path)

def get_retry_queue() -> list[str]:
    return _get_retry_queue("person_crops")

def clear_retry(image_path: str) -> None:
    _clear_retry("person_crops", image_path)


# ── Search embeddings API ─────────────────────────────────────────────────────

def search_already_embedded(image_path: str) -> bool:
    return _already_embedded("search_embeddings", image_path)

def search_mark_embedded(image_path: str) -> None:
    _mark_embedded("search_embeddings", image_path)

def search_mark_for_retry(image_path: str) -> None:
    _mark_for_retry("search_embeddings", image_path)

def search_get_retry_queue() -> list[str]:
    return _get_retry_queue("search_embeddings")

def search_clear_retry(image_path: str) -> None:
    _clear_retry("search_embeddings", image_path)