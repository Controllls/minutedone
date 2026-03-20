"""
============================================================
db.py
팀 라이브러리 에이전트 v2 - 로컬 SQLite DB
============================================================
대시보드 상태(이벤트, 태스크, 최근 회의)를 SQLite에 영속 저장합니다.
DB 파일: output/tiro.db
============================================================
"""

import sqlite3
import json
import os

DB_PATH = "output/tiro.db"


def _conn() -> sqlite3.Connection:
    os.makedirs("output", exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    """테이블 초기화 (앱 시작 시 1회 실행)"""
    with _conn() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS kv (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                task       TEXT,
                due_date   TEXT,
                end_date   TEXT,
                assignee   TEXT,
                context    TEXT,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        # 기존 DB에 end_date 컬럼이 없으면 추가 (마이그레이션)
        try:
            con.execute("ALTER TABLE events ADD COLUMN end_date TEXT")
        except Exception:
            pass  # 이미 존재하면 무시
        con.execute("""
            CREATE TABLE IF NOT EXISTS recent_meetings (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                preview    TEXT,
                time       TEXT,
                task_count INTEGER,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)


# ── KV 스토어 (taskViews 등 JSON 덩어리 저장) ──

def kv_set(key: str, value):
    with _conn() as con:
        con.execute(
            "INSERT INTO kv(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value, ensure_ascii=False))
        )


def kv_get(key: str, default=None):
    with _conn() as con:
        row = con.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    if row is None:
        return default
    return json.loads(row["value"])


# ── 이벤트 ──

def save_events(events: list[dict]):
    with _conn() as con:
        con.execute("DELETE FROM events")
        con.executemany(
            "INSERT INTO events(task, due_date, end_date, assignee, context) VALUES(?,?,?,?,?)",
            [(e.get("task",""), e.get("due_date",""), e.get("end_date") or None,
              e.get("assignee",""), e.get("context","")) for e in events]
        )


def load_events() -> list[dict]:
    with _conn() as con:
        rows = con.execute("SELECT task, due_date, end_date, assignee, context FROM events").fetchall()
    return [dict(r) for r in rows]


# ── 최근 회의 ──

def add_recent_meeting(preview: str, time: str, task_count: int):
    with _conn() as con:
        con.execute(
            "INSERT INTO recent_meetings(preview, time, task_count) VALUES(?,?,?)",
            (preview, time, task_count)
        )
        # 최대 10개 유지
        con.execute("""
            DELETE FROM recent_meetings WHERE id NOT IN (
                SELECT id FROM recent_meetings ORDER BY id DESC LIMIT 10
            )
        """)


def load_recent_meetings() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT preview, time, task_count FROM recent_meetings ORDER BY id DESC"
        ).fetchall()
    return [{"preview": r["preview"], "time": r["time"], "count": r["task_count"]} for r in rows]
