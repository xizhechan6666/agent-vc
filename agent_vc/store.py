"""SQLite persistence for reports, quota gating, and duplicate checks."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def db_path() -> Path:
    return Path(os.getenv("AGENT_VC_DB", "data/agent_vc.sqlite3"))


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
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
    _ensure_columns(conn)
    conn.commit()
    return conn


def _ensure_columns(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(evaluations)").fetchall()}
    migrations = {
        "project_fingerprint": "ALTER TABLE evaluations ADD COLUMN project_fingerprint TEXT",
        "submitter_key": "ALTER TABLE evaluations ADD COLUMN submitter_key TEXT",
        "duplicate_today": "ALTER TABLE evaluations ADD COLUMN duplicate_today INTEGER NOT NULL DEFAULT 0",
        "contact_hint": "ALTER TABLE evaluations ADD COLUMN contact_hint TEXT",
        "report_token": "ALTER TABLE evaluations ADD COLUMN report_token TEXT",
        "owner_preview": "ALTER TABLE evaluations ADD COLUMN owner_preview INTEGER NOT NULL DEFAULT 0",
    }
    for column, statement in migrations.items():
        if column not in existing:
            conn.execute(statement)


def quota_preview(conn: sqlite3.Connection) -> dict[str, int]:
    window_size = int(os.getenv("INVESTMENT_WINDOW_SIZE", "20"))
    max_per_window = int(os.getenv("INVESTMENT_MAX_PER_WINDOW", "1"))
    total_before = conn.execute("SELECT COUNT(*) AS c FROM evaluations WHERE owner_preview = 0").fetchone()["c"]
    batch_index = total_before // window_size
    candidates_in_batch = conn.execute(
        """
        SELECT COUNT(*) AS c
        FROM evaluations
        WHERE batch_index = ?
        AND final_candidate = 1
        AND owner_preview = 0
        """,
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


def duplicate_today(conn: sqlite3.Connection, *, project_fingerprint: str, submitter_key: str = "") -> bool:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    if not project_fingerprint and not submitter_key:
        return False

    row = conn.execute(
        """
        SELECT COUNT(*) AS c
        FROM evaluations
        WHERE date(created_at) = ?
          AND owner_preview = 0
          AND (
            (? != '' AND project_fingerprint = ?)
            OR (? != '' AND submitter_key = ?)
          )
        """,
        (today, project_fingerprint, project_fingerprint, submitter_key, submitter_key),
    ).fetchone()
    return bool(row and row["c"] > 0)


def save_evaluation(
    conn: sqlite3.Connection,
    *,
    project_name: str,
    report: dict[str, Any],
    gate: dict[str, Any],
    project_fingerprint: str = "",
    submitter_key: str = "",
    duplicate: bool = False,
    contact_hint: str = "",
    report_token: str = "",
    owner_preview: bool = False,
) -> int:
    cursor = conn.execute(
        """
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
            owner_preview,
            report_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
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
            1 if owner_preview else 0,
            json.dumps(report, ensure_ascii=False),
        ),
    )
    conn.commit()
    return int(cursor.lastrowid)


def get_evaluation(conn: sqlite3.Connection, evaluation_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, created_at, project_name, total_score, recommendation,
               raw_eligible, final_candidate, batch_index, project_fingerprint,
               submitter_key, duplicate_today, contact_hint, report_token,
               owner_preview, report_json
        FROM evaluations
        WHERE id = ?
        """,
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
        "owner_preview": bool(row["owner_preview"]),
        "report_url_kind": "legacy_id",
        "report": json.loads(row["report_json"]),
    }


def get_evaluation_by_token(conn: sqlite3.Connection, report_token: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, created_at, project_name, total_score, recommendation,
               raw_eligible, final_candidate, batch_index, project_fingerprint,
               submitter_key, duplicate_today, contact_hint, report_token,
               owner_preview, report_json
        FROM evaluations
        WHERE report_token = ?
        """,
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
        "owner_preview": bool(row["owner_preview"]),
        "report_url_kind": "agent_token",
        "report": json.loads(row["report_json"]),
    }
