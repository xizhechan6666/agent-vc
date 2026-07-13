"""SQLite persistence for reports and quota gating."""

from __future__ import annotations

import json
import os
import sqlite3
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
    conn.commit()
    return conn


def quota_preview(conn: sqlite3.Connection) -> dict[str, int]:
    window_size = int(os.getenv("INVESTMENT_WINDOW_SIZE", "20"))
    max_per_window = int(os.getenv("INVESTMENT_MAX_PER_WINDOW", "1"))
    total_before = conn.execute("SELECT COUNT(*) AS c FROM evaluations").fetchone()["c"]
    batch_index = total_before // window_size
    batch_start = batch_index * window_size
    candidates_in_batch = conn.execute(
        """
        SELECT COUNT(*) AS c
        FROM evaluations
        WHERE id > (
            SELECT COALESCE(MAX(id), 0)
            FROM evaluations
            WHERE id <= ?
        )
        AND batch_index = ?
        AND final_candidate = 1
        """,
        (batch_start, batch_index),
    ).fetchone()["c"]
    return {
        "window_size": window_size,
        "max_per_window": max_per_window,
        "total_before": total_before,
        "batch_index": batch_index,
        "candidates_in_batch": candidates_in_batch,
        "slots_remaining": max(0, max_per_window - candidates_in_batch),
    }


def save_evaluation(
    conn: sqlite3.Connection,
    *,
    project_name: str,
    report: dict[str, Any],
    gate: dict[str, Any],
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
            report_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            project_name,
            int(report.get("total_score", 0)),
            str(report.get("recommendation", "watch")),
            1 if report.get("raw_eligible_for_investment") else 0,
            1 if gate.get("final_candidate") else 0,
            int(gate.get("batch_index", 0)),
            json.dumps(report, ensure_ascii=False),
        ),
    )
    conn.commit()
    return int(cursor.lastrowid)


def get_evaluation(conn: sqlite3.Connection, evaluation_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, created_at, project_name, total_score, recommendation,
               raw_eligible, final_candidate, batch_index, report_json
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
        "report": json.loads(row["report_json"]),
    }
