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
        # 기존 DB 마이그레이션 — 누락 컬럼 추가
        for col_ddl in [
            "ALTER TABLE events ADD COLUMN end_date TEXT",
            "ALTER TABLE events ADD COLUMN task_level TEXT",
            "ALTER TABLE events ADD COLUMN parent_task TEXT",
            "ALTER TABLE events ADD COLUMN source_quote TEXT",
            "ALTER TABLE events ADD COLUMN reason TEXT",
            "ALTER TABLE events ADD COLUMN checklist TEXT",
        ]:
            try:
                con.execute(col_ddl)
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
        con.execute("""
            CREATE TABLE IF NOT EXISTS contacts (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                name             TEXT NOT NULL,
                nicknames        TEXT,
                organization     TEXT,
                team             TEXT,
                role             TEXT,
                responsibilities TEXT,
                note             TEXT,
                created_at       TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                client      TEXT,
                status      TEXT DEFAULT '진행중',
                description TEXT,
                created_at  TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS project_members (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
                member_role TEXT,
                UNIQUE(project_id, contact_id)
            )
        """)
        # ── 에이전트 실행 이력 ──
        con.execute("""
            CREATE TABLE IF NOT EXISTS agent_runs (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id   TEXT NOT NULL,
                agent_name   TEXT,
                task_name    TEXT,
                input_hash   TEXT,
                output_summary TEXT,
                status       TEXT DEFAULT 'done',
                duration_sec REAL,
                created_at   TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS agent_decisions (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                agent_name TEXT,
                decision   TEXT,
                reason     TEXT,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                doc_type   TEXT,
                title      TEXT,
                content    TEXT,
                project_id INTEGER,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                channel    TEXT,
                recipient  TEXT,
                content    TEXT,
                status     TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS agent_memory (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name   TEXT NOT NULL,
                memory_type  TEXT NOT NULL,
                key          TEXT NOT NULL,
                value        TEXT,
                confidence   REAL DEFAULT 0.5,
                hit_count    INTEGER DEFAULT 1,
                created_at   TEXT DEFAULT (datetime('now','localtime')),
                updated_at   TEXT DEFAULT (datetime('now','localtime')),
                UNIQUE(agent_name, key)
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
            """INSERT INTO events(task, due_date, end_date, assignee, context, task_level, parent_task, source_quote, reason, checklist)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            [(e.get("task",""), e.get("due_date",""), e.get("end_date") or None,
              e.get("assignee",""), e.get("context",""),
              e.get("task_level") or None, e.get("parent_task") or None,
              e.get("source_quote") or None, e.get("reason") or None,
              json.dumps(e.get("checklist") or [], ensure_ascii=False)) for e in events]
        )


def load_events() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT task, due_date, end_date, assignee, context, task_level, parent_task, source_quote, reason, checklist FROM events"
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["checklist"] = json.loads(d["checklist"]) if d["checklist"] else []
        except Exception:
            d["checklist"] = []
        result.append(d)
    return result


# ── 인물 DB ──

def get_contacts() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT id, name, nicknames, organization, team, role, responsibilities, note FROM contacts ORDER BY organization, name"
        ).fetchall()
    return [dict(r) for r in rows]


def upsert_contact(data: dict) -> int:
    cid = data.get("id")
    fields = ("name", "nicknames", "organization", "team", "role", "responsibilities", "note")
    vals = tuple(data.get(f, "") or "" for f in fields)
    with _conn() as con:
        if cid:
            con.execute(
                f"UPDATE contacts SET {', '.join(f+'=?' for f in fields)} WHERE id=?",
                vals + (cid,)
            )
            return cid
        else:
            cur = con.execute(
                f"INSERT INTO contacts({', '.join(fields)}) VALUES({', '.join('?' for _ in fields)})",
                vals
            )
            return cur.lastrowid


def delete_contact(cid: int):
    with _conn() as con:
        con.execute("DELETE FROM contacts WHERE id=?", (cid,))


def build_contacts_prompt(contacts: list[dict] = None) -> str:
    """LLM 프롬프트 주입용 인물 정보 섹션을 생성합니다."""
    if contacts is None:
        contacts = get_contacts()
    if not contacts:
        return ""
    lines = []
    for c in contacts:
        parts = [c["name"]]
        if c.get("organization"):
            parts.append(c["organization"])
        if c.get("team"):
            parts.append(c["team"])
        if c.get("role"):
            parts.append(c["role"])
        desc = " / ".join(parts)
        if c.get("responsibilities"):
            desc += f" · {c['responsibilities']}"
        if c.get("nicknames"):
            desc += f" (호칭: {c['nicknames']})"
        if c.get("note"):
            desc += f" ※ {c['note']}"
        lines.append(f"- {desc}")
    return "\n## 참여자 / 관계자 정보\n" + "\n".join(lines) + "\n"


def build_whisper_names(contacts: list[dict] = None) -> str:
    """Whisper STT 프롬프트에 주입할 이름 목록을 생성합니다."""
    if contacts is None:
        contacts = get_contacts()
    names = []
    for c in contacts:
        names.append(c["name"])
        if c.get("nicknames"):
            names.extend([n.strip() for n in c["nicknames"].split(",")])
    return ", ".join(dict.fromkeys(names))  # 중복 제거


# ── 프로젝트 ──

def get_projects(status: str = None) -> list[dict]:
    with _conn() as con:
        q = "SELECT id, name, client, status, description FROM projects"
        rows = con.execute(q + (" WHERE status=?" if status else " ORDER BY id DESC"),
                           (status,) if status else ()).fetchall()
    return [dict(r) for r in rows]


def upsert_project(data: dict) -> int:
    pid = data.get("id")
    fields = ("name", "client", "status", "description")
    vals = tuple(data.get(f, "") or "" for f in fields)
    with _conn() as con:
        if pid:
            con.execute(f"UPDATE projects SET {', '.join(f+'=?' for f in fields)} WHERE id=?", vals + (pid,))
            return pid
        else:
            cur = con.execute(
                f"INSERT INTO projects({', '.join(fields)}) VALUES({', '.join('?'*len(fields))})", vals)
            return cur.lastrowid


def delete_project(pid: int):
    with _conn() as con:
        con.execute("DELETE FROM projects WHERE id=?", (pid,))


def get_project_members(pid: int) -> list[dict]:
    with _conn() as con:
        rows = con.execute("""
            SELECT pm.id, pm.contact_id, pm.member_role,
                   c.name, c.nicknames, c.organization, c.team, c.role, c.responsibilities, c.note
            FROM project_members pm JOIN contacts c ON pm.contact_id = c.id
            WHERE pm.project_id=?
            ORDER BY pm.member_role, c.organization, c.name
        """, (pid,)).fetchall()
    return [dict(r) for r in rows]


def set_project_members(pid: int, members: list[dict]):
    """members: [{"contact_id": int, "member_role": str}, ...]"""
    with _conn() as con:
        con.execute("DELETE FROM project_members WHERE project_id=?", (pid,))
        con.executemany(
            "INSERT OR IGNORE INTO project_members(project_id, contact_id, member_role) VALUES(?,?,?)",
            [(pid, m["contact_id"], m.get("member_role", "")) for m in members]
        )


def build_project_context(pid: int) -> str:
    """프로젝트 담당자 정보를 LLM 프롬프트용 문자열로 반환합니다."""
    with _conn() as con:
        proj = con.execute("SELECT name, client, description FROM projects WHERE id=?", (pid,)).fetchone()
    if not proj:
        return ""
    members = get_project_members(pid)
    lines = [f"## 프로젝트 정보", f"- 프로젝트명: {proj['name']}"]
    if proj["client"]:
        lines.append(f"- 클라이언트: {proj['client']}")
    if proj["description"]:
        lines.append(f"- 설명: {proj['description']}")

    if members:
        lines.append("\n## 프로젝트 담당자")
        by_role = {}
        for m in members:
            r = m["member_role"] or "기타"
            by_role.setdefault(r, []).append(m)
        for role, mlist in by_role.items():
            lines.append(f"### {role}")
            for m in mlist:
                desc = m["name"]
                if m["organization"]:
                    desc += f" ({m['organization']}"
                    if m["team"]: desc += f" {m['team']}"
                    if m["role"]: desc += f" {m['role']}"
                    desc += ")"
                if m["nicknames"]:
                    desc += f" — 호칭: {m['nicknames']}"
                if m["note"]:
                    desc += f" ⚠ {m['note']}"
                lines.append(f"- {desc}")

    lines.append("\n이 프로젝트 관련 회의이므로 위 담당자 정보를 기반으로 발화자와 assignee를 정확히 식별할 것.")
    return "\n".join(lines) + "\n"


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


# ── 에이전트 실행 이력 ──

def log_agent_run(session_id: str, agent_name: str, task_name: str,
                  output_summary: str, status: str = "done",
                  duration_sec: float = None) -> int:
    with _conn() as con:
        cur = con.execute(
            """INSERT INTO agent_runs
               (session_id, agent_name, task_name, output_summary, status, duration_sec)
               VALUES (?,?,?,?,?,?)""",
            (session_id, agent_name, task_name, output_summary, status, duration_sec)
        )
        return cur.lastrowid


def log_agent_decision(session_id: str, agent_name: str, decision: str, reason: str):
    with _conn() as con:
        con.execute(
            "INSERT INTO agent_decisions(session_id, agent_name, decision, reason) VALUES (?,?,?,?)",
            (session_id, agent_name, decision, reason)
        )


def get_agent_runs(limit: int = 50) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            """SELECT session_id, agent_name, task_name, output_summary,
                      status, duration_sec, created_at
               FROM agent_runs ORDER BY id DESC LIMIT ?""", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_session_runs(session_id: str) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM agent_runs WHERE session_id=? ORDER BY id", (session_id,)
        ).fetchall()
        decisions = con.execute(
            "SELECT * FROM agent_decisions WHERE session_id=? ORDER BY id", (session_id,)
        ).fetchall()
    return {"runs": [dict(r) for r in rows], "decisions": [dict(d) for d in decisions]}


# ── 문서 (rabbit) ──

def save_document(session_id: str, doc_type: str, title: str,
                  content: str, project_id: int = None) -> int:
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO documents(session_id, doc_type, title, content, project_id) VALUES (?,?,?,?,?)",
            (session_id, doc_type, title, content, project_id)
        )
        return cur.lastrowid


def get_documents(project_id: int = None) -> list[dict]:
    with _conn() as con:
        if project_id:
            rows = con.execute(
                "SELECT id, session_id, doc_type, title, content, project_id, created_at FROM documents WHERE project_id=? ORDER BY id DESC",
                (project_id,)
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT id, session_id, doc_type, title, content, project_id, created_at FROM documents ORDER BY id DESC LIMIT 50"
            ).fetchall()
    return [dict(r) for r in rows]


# ── 메시지 전송 이력 (retriever) ──

def log_message(session_id: str, channel: str, recipient: str,
                content: str, status: str = "sent") -> int:
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO messages(session_id, channel, recipient, content, status) VALUES (?,?,?,?,?)",
            (session_id, channel, recipient, content, status)
        )
        return cur.lastrowid


def get_messages(limit: int = 50) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT id, session_id, channel, recipient, content, status, created_at FROM messages ORDER BY id DESC LIMIT ?",
            (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── 에이전트 메모리 (패턴 학습) ──

def upsert_agent_memory(agent_name: str, memory_type: str, key: str,
                        value: str, confidence: float = 0.5):
    with _conn() as con:
        existing = con.execute(
            "SELECT id, hit_count FROM agent_memory WHERE agent_name=? AND key=?",
            (agent_name, key)
        ).fetchone()
        if existing:
            con.execute(
                """UPDATE agent_memory
                   SET value=?, confidence=?, hit_count=hit_count+1,
                       updated_at=datetime('now','localtime')
                   WHERE id=?""",
                (value, confidence, existing["id"])
            )
        else:
            con.execute(
                """INSERT INTO agent_memory(agent_name, memory_type, key, value, confidence)
                   VALUES (?,?,?,?,?)""",
                (agent_name, memory_type, key, value, confidence)
            )


def get_agent_memory(agent_name: str) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            """SELECT memory_type, key, value, confidence, hit_count, updated_at
               FROM agent_memory WHERE agent_name=? ORDER BY hit_count DESC""",
            (agent_name,)
        ).fetchall()
    return [dict(r) for r in rows]


def build_agent_memory_prompt(agent_name: str) -> str:
    """에이전트 메모리를 프롬프트 주입용 텍스트로 변환합니다."""
    memories = get_agent_memory(agent_name)
    if not memories:
        return ""
    lines = [f"## {agent_name} 학습된 패턴 (신뢰도 순)"]
    for m in memories:
        conf_label = "높음" if m["confidence"] >= 0.8 else "보통" if m["confidence"] >= 0.5 else "낮음"
        lines.append(f"- [{m['memory_type']}] {m['key']}: {m['value']} (신뢰도: {conf_label}, 적용 {m['hit_count']}회)")
    return "\n".join(lines) + "\n"
