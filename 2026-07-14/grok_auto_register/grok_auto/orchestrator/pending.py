# -*- coding: utf-8 -*-
"""mint pending 落盘。"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

_lock = threading.Lock()


def _read(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            o = json.loads(s)
            if isinstance(o, dict) and o.get("email"):
                out.append(o)
        except json.JSONDecodeError:
            continue
    return out


def _write(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in rows)
    fd, tmp = tempfile.mkstemp(prefix=".pending-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def enqueue(path: Path, job: dict[str, Any]) -> None:
    email = str(job.get("email") or "").strip().lower()
    if not email:
        return
    rec = {
        "email": email,
        "email_raw": str(job.get("email") or email),
        "password": str(job.get("password") or ""),
        "sso": str(job.get("sso") or ""),
        "status": "pending",
        "updated_at": int(time.time()),
        "attempts": int(job.get("attempts") or 0),
    }
    with _lock:
        rows = [r for r in _read(path) if str(r.get("email") or "").lower() != email]
        rows.append(rec)
        _write(path, rows)


def mark_done(path: Path, email: str) -> None:
    key = email.strip().lower()
    with _lock:
        rows = [r for r in _read(path) if str(r.get("email") or "").lower() != key]
        _write(path, rows)


def mark_failed(path: Path, email: str, error: str) -> None:
    key = email.strip().lower()
    with _lock:
        rows = _read(path)
        out = []
        for r in rows:
            if str(r.get("email") or "").lower() != key:
                out.append(r)
                continue
            r = dict(r)
            r["status"] = "failed"
            r["last_error"] = error[:400]
            r["attempts"] = int(r.get("attempts") or 0) + 1
            r["updated_at"] = int(time.time())
            out.append(r)
        _write(path, out)


def list_recoverable(path: Path, max_attempts: int = 5) -> list[dict[str, Any]]:
    with _lock:
        rows = _read(path)
    out = []
    for r in rows:
        st = str(r.get("status") or "pending")
        if int(r.get("attempts") or 0) >= max_attempts:
            continue
        if st in ("pending", "failed"):
            out.append(r)
    return out
