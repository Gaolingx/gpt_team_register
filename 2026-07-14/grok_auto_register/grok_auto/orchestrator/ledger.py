# -*- coding: utf-8 -*-
"""账本读写。"""

from __future__ import annotations

import threading
from pathlib import Path

from grok_auto.session.models import AccountRecord

_lock = threading.Lock()


def append_account(path: Path, account: AccountRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = account.ledger_line() + "\n"
    with _lock:
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(line)


def count_accounts(path: Path) -> int:
    if not path.is_file():
        return 0
    n = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip() and not line.strip().startswith("#"):
            n += 1
    return n


def existing_cpa_emails(auth_dir: Path) -> set[str]:
    found: set[str] = set()
    if not auth_dir.is_dir():
        return found
    for p in auth_dir.glob("xai-*.json"):
        name = p.name[len("xai-") : -len(".json")]
        if name:
            found.add(name.lower())
        try:
            import json

            d = json.loads(p.read_text(encoding="utf-8"))
            em = str(d.get("email") or "").strip().lower()
            if em:
                found.add(em)
        except Exception:
            continue
    return found
