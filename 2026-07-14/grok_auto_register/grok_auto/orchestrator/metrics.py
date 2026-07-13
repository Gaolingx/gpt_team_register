# -*- coding: utf-8 -*-
"""阶段指标 JSONL。"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

_lock = threading.Lock()


def emit(path: Path, record: dict[str, Any]) -> None:
    rec = dict(record)
    rec.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S"))
    line = json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _lock:
            with open(path, "a", encoding="utf-8", newline="\n") as f:
                f.write(line)
    except Exception:
        pass
