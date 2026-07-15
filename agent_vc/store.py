"""Persistence for reports, quota gating, and duplicate checks.

Uses Postgres when DATABASE_URL is configured. Falls back to local SQLite for
development and owner-preview testing.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


JsonDict = dict[str, Any]


def database_url() -> str:
    return os.getenv("DATABASE_URL", "").strip() or os.getenv("POSTGRES_URL", "").strip()


def storage_backend() -> str:
    return "postgres" if database_url() else "sqlite"


def db_path() -> Path:
    return Path(os.getenv("AGENT_VC_DB", "data/agent_vc.sqlite3"))


def is_postgres(conn: Any) -> bool:
    return conn.__class__.__module__.startswith("psycopg")


def sql(conn: Any, statement: str) -> str:
    if is_postgres(conn):
        return statement.replace("?", "%s")
    return statement


def connect() -> Any:
    dsn = database_url()
    if dsn:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ModuleNotFoundError as exc:
            raise RuntimeError("DATABASE_URL is set but psycopg is not installed") from exc

        kwargs: dict[str, Any] = {"row_factory": dict_row}
        sslmode = os.getenv("DATABASE_SSLMODE", "").strip()
        if sslmode:
            kwargs["sslmode"] = sslmode
        conn = psycopg.connect(dsn, **kwargs)
        _init_postgres(conn)
        conn.commit()
        return conn

    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    _init_sqlite(conn)
    conn.commit()
    return conn


def _init_sqlite(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            project_name TEXT NOT NULL,
            total_score INTEGER NOT NULL,
            recommendation TEXT NOT NULL,
            raw_eligible INTEGER NOT NULL,
            final_candidate INTEGER NOT NULL,
            batch_index INTEGER NOT NULL,
            report_json TEXT NOT NULL
        )
        """
    )
    _ensure_sqlite_columns(conn)


def _init_postgres(conn: Any) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS evaluations (
            id BIGSERIAL PRIMARY KEY,
            created_at TEXT NOT NULL DEFAULT (now()::text),
            project_name TEXT NOT NULL,
            total_score INTEGER NOT NULL,
            recommendation TEXT NOT NULL,
            raw_eligible INTEGER NOT NULL,
            final_candidate INTEGER NOT NULL,
            batch_index INTEGER NOT NULL,
            project_fingerprint TEXT,
            submitter_key TEXT,
            duplicate_today INTEGER NOT NULL DEFAULT 0,
            contact_hint TEXT,
            report_token TEXT,
            owner_preview INTEGER NOT NULL DEFAULT 0,
            project_json TEXT,
            answers_json TEXT,
            payer_wallet TEXT,
            source TEXT,
            report_url TEXT,
            report_json TEXT NOT NULL
        )
        """
    )
    _ensure_postgres_columns(conn)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_evaluations_report_token ON evaluations (report_token)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_evaluations_created_at ON evaluations (created_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_evaluations_fingerprint ON evaluations (project_fingerprint)"
    )


def _ensure_sqlite_columns(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(evaluations)").fetchall()}
    migrations = {
        "project_fingerprint": "ALTER TABLE evaluations ADD COLUMN project_fingerprint TEXT",
        "submitter_key": "ALTER TABLE evaluations ADD COLUMN submitter_key TEXT",
        "duplicate_today": "ALTER TABLE evaluations ADD COLUMN duplicate_today INTEGER NOT NULL DEFAULT 0",
        "contact_hint": "ALTER TABLE evaluations ADD COLUMN contact_hint TEXT",
        "report_token": "ALTER TABLE evaluations ADD COLUMN report_token TEXT",
        "owner_preview": "ALTER TABLE evaluations ADD COLUMN owner_preview INTEGER NOT NULL DEFAULT 0",
        "project_json": "ALTER TABLE evaluations ADD COLUMN project_json TEXT",
        "answers_json": "ALTER TABLE evaluations ADD COLUMN answers_json TEXT",
        "payer_wallet": "ALTER TABLE evaluations ADD COLUMN payer_wallet TEXT",
        "source": "ALTER TABLE evaluations ADD COLUMN source TEXT",
        "report_url": "ALTER TABLE evaluations ADD COLUMN report_url TEXT",
    }
    for column, statement in migrations.items():
        if column not in existing:
            conn.execute(statement)


def _ensure_postgres_columns(conn: Any) -> None:
    rows = conn.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'evaluations'
        """
    ).fetchall()
    existing = {row["column_name"] for row in rows}
    migrations = {
        "project_fingerprint": "ALTER TABLE evaluations ADD COLUMN project_fingerprint TEXT",
        "submitter_key": "ALTER TABLE evaluations ADD COLUMN submitter_key TEXT",
        "duplicate_today": "ALTER TABLE evaluations ADD COLUMN duplicate_today INTEGER NOT NULL DEFAULT 0",
        "contact_hint": "ALTER TABLE evaluations ADD COLUMN contact_hint TEXT",
        "report_token": "ALTER TABLE evaluations ADD COLUMN report_token TEXT",
        "owner_preview": "ALTER TABLE evaluations ADD COLUMN owner_preview INTEGER NOT NULL DEFAULT 0",
        "project_json": "ALTER TABLE evaluations ADD COLUMN project_json TEXT",
        "answers_json": "ALTER TABLE evaluations ADD COLUMN answers_json TEXT",
        "payer_wallet": "ALTER TABLE evaluations ADD COLUMN payer_wallet TEXT",
        "source": "ALTER TABLE evaluations ADD COLUMN source TEXT",
        "report_url": "ALTER TABLE evaluations ADD COLUMN report_url TEXT",
    }
    for column, statement in migrations.items():
        if column not in existing:
            conn.execute(statement)


def row_get(row: Any, key: str) -> Any:
    return row[key]


def quota_preview(conn: Any) -> dict[str, int]:
    window_size = int(os.getenv("INVESTMENT_WINDOW_SIZE", "20"))
    max_per_window = int(os.getenv("INVESTMENT_MAX_PER_WINDOW", "1"))
    total_before = row_get(conn.execute("SELECT COUNT(*) AS c FROM evaluations WHERE owner_preview = 0").fetchone(), "c")
    batch_index = total_before // window_size
    candidates_in_batch = conn.execute(
        sql(conn, """
        SELECT COUNT(*) AS c
        FROM evaluations
        WHERE batch_index = ?
        AND final_candidate = 1
        AND owner_preview = 0
        """),
        (batch_index,),
    ).fetchone()["c"]
    return {
        "window_size": window_size,
        "max_per_window": max_per_window,
        "total_before": total_before,
        "batch_index": batch_index,
        "candidates_in_batch": candidates_in_batch,
        "slots_remaining": max(0, max_per_window - candidates_in_batch),
    }


def duplicate_today(conn: Any, *, project_fingerprint: str, submitter_key: str = "") -> bool:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    if not project_fingerprint and not submitter_key:
        return False

    row = conn.execute(
        sql(conn, """
        SELECT COUNT(*) AS c
        FROM evaluations
        WHERE created_at LIKE ?
          AND owner_preview = 0
          AND (
            (? != '' AND project_fingerprint = ?)
            OR (? != '' AND submitter_key = ?)
          )
        """),
        (f"{today}%", project_fingerprint, project_fingerprint, submitter_key, submitter_key),
    ).fetchone()
    return bool(row and row["c"] > 0)


def save_evaluation(
    conn: Any,
    *,
    project_name: str,
    project: dict[str, Any] | None = None,
    answers: list[dict[str, Any]] | None = None,
    report: dict[str, Any],
    gate: dict[str, Any],
    project_fingerprint: str = "",
    submitter_key: str = "",
    duplicate: bool = False,
    contact_hint: str = "",
    report_token: str = "",
    report_url: str = "",
    payer_wallet: str = "",
    source: str = "",
    owner_preview: bool = False,
) -> int:
    insert_sql = """
        INSERT INTO evaluations (
            project_name,
            total_score,
            recommendation,
            raw_eligible,
            final_candidate,
            batch_index,
            project_fingerprint,
            submitter_key,
            duplicate_today,
            contact_hint,
            report_token,
            report_url,
            payer_wallet,
            source,
            owner_preview,
            project_json,
            answers_json,
            report_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    values = (
        project_name,
        int(report.get("total_score", 0)),
        str(report.get("recommendation", "watch")),
        1 if report.get("raw_eligible_for_investment") else 0,
        1 if gate.get("final_candidate") else 0,
        int(gate.get("batch_index", 0)),
        project_fingerprint,
        submitter_key,
        1 if duplicate else 0,
        contact_hint,
        report_token,
        report_url,
        payer_wallet,
        source,
        1 if owner_preview else 0,
        json.dumps(project or {}, ensure_ascii=False),
        json.dumps(answers or [], ensure_ascii=False),
        json.dumps(report, ensure_ascii=False),
    )
    if is_postgres(conn):
        cursor = conn.execute(sql(conn, f"{insert_sql} RETURNING id"), values)
        evaluation_id = int(cursor.fetchone()["id"])
    else:
        cursor = conn.execute(insert_sql, values)
        evaluation_id = int(cursor.lastrowid)
    conn.commit()
    return evaluation_id


def get_evaluation(conn: Any, evaluation_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        sql(conn, """
        SELECT id, created_at, project_name, total_score, recommendation,
               raw_eligible, final_candidate, batch_index, project_fingerprint,
               submitter_key, duplicate_today, contact_hint, report_token,
               report_url, payer_wallet, source, owner_preview,
               project_json, answers_json, report_json
        FROM evaluations
        WHERE id = ?
        """),
        (evaluation_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "project_name": row["project_name"],
        "total_score": row["total_score"],
        "recommendation": row["recommendation"],
        "raw_eligible": bool(row["raw_eligible"]),
        "final_candidate": bool(row["final_candidate"]),
        "batch_index": row["batch_index"],
        "project_fingerprint": row["project_fingerprint"],
        "submitter_key": row["submitter_key"],
        "duplicate_today": bool(row["duplicate_today"]),
        "contact_hint": row["contact_hint"],
        "report_token": row["report_token"],
        "report_url": row["report_url"],
        "payer_wallet": row["payer_wallet"],
        "source": row["source"],
        "owner_preview": bool(row["owner_preview"]),
        "project": json.loads(row["project_json"] or "{}"),
        "answers": json.loads(row["answers_json"] or "[]"),
        "report_url_kind": "legacy_id",
        "report": json.loads(row["report_json"]),
    }


def get_evaluation_by_token(conn: Any, report_token: str) -> dict[str, Any] | None:
    row = conn.execute(
        sql(conn, """
        SELECT id, created_at, project_name, total_score, recommendation,
               raw_eligible, final_candidate, batch_index, project_fingerprint,
               submitter_key, duplicate_today, contact_hint, report_token,
               report_url, payer_wallet, source, owner_preview,
               project_json, answers_json, report_json
        FROM evaluations
        WHERE report_token = ?
        """),
        (report_token,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "project_name": row["project_name"],
        "total_score": row["total_score"],
        "recommendation": row["recommendation"],
        "raw_eligible": bool(row["raw_eligible"]),
        "final_candidate": bool(row["final_candidate"]),
        "batch_index": row["batch_index"],
        "project_fingerprint": row["project_fingerprint"],
        "submitter_key": row["submitter_key"],
        "duplicate_today": bool(row["duplicate_today"]),
        "contact_hint": row["contact_hint"],
        "report_token": row["report_token"],
        "report_url": row["report_url"],
        "payer_wallet": row["payer_wallet"],
        "source": row["source"],
        "owner_preview": bool(row["owner_preview"]),
        "project": json.loads(row["project_json"] or "{}"),
        "answers": json.loads(row["answers_json"] or "[]"),
        "report_url_kind": "agent_token",
        "report": json.loads(row["report_json"]),
    }


def list_evaluations(conn: Any, *, limit: int = 100) -> list[dict[str, Any]]:
    capped_limit = max(1, min(int(limit), 500))
    rows = conn.execute(
        sql(conn, """
        SELECT id, created_at, project_name, total_score, recommendation,
               raw_eligible, final_candidate, batch_index, project_fingerprint,
               submitter_key, duplicate_today, contact_hint, report_token,
               report_url, payer_wallet, source, owner_preview,
               project_json, answers_json
        FROM evaluations
        ORDER BY id DESC
        LIMIT ?
        """),
        (capped_limit,),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "created_at": row["created_at"],
            "project_name": row["project_name"],
            "total_score": row["total_score"],
            "recommendation": row["recommendation"],
            "raw_eligible": bool(row["raw_eligible"]),
            "final_candidate": bool(row["final_candidate"]),
            "batch_index": row["batch_index"],
            "project_fingerprint": row["project_fingerprint"],
            "submitter_key": row["submitter_key"],
            "duplicate_today": bool(row["duplicate_today"]),
            "contact_hint": row["contact_hint"],
            "report_token": row["report_token"],
            "report_url": row["report_url"],
            "payer_wallet": row["payer_wallet"],
            "source": row["source"],
            "owner_preview": bool(row["owner_preview"]),
            "project": json.loads(row["project_json"] or "{}"),
            "answers": json.loads(row["answers_json"] or "[]"),
        }
        for row in rows
    ]
