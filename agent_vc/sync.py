"""Optional outbound sync for evaluation records."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


def sync_evaluation(payload: dict[str, Any]) -> dict[str, Any]:
    """Send an evaluation payload to a user-owned database API when configured.

    The app writes to its primary configured store first: Supabase/Postgres in
    production, SQLite only as a local fallback. This hook is intentionally
    best-effort so report generation does not fail if an external mirror is
    temporarily unavailable.
    """

    url = os.getenv("DB_SYNC_WEBHOOK_URL", "").strip()
    if not url:
        return {"enabled": False, "ok": False, "skipped": True}

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    secret = os.getenv("DB_SYNC_SECRET", "").strip()
    if secret:
        headers["Authorization"] = f"Bearer {secret}"

    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    timeout = float(os.getenv("DB_SYNC_TIMEOUT_SECONDS", "5"))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return {"enabled": True, "ok": 200 <= response.status < 300, "status": response.status}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"enabled": True, "ok": False, "error": str(exc)}
