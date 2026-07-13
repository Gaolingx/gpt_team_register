# -*- coding: utf-8 -*-
"""步骤日志：约 20 字，最长 28 字。"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

LogFn = Callable[[str], None]

DEFAULT_LIMIT = 28


def short(msg: str, limit: int = DEFAULT_LIMIT) -> str:
    """截断到 limit 个字符。"""
    s = str(msg or "").replace("\n", " ").strip()
    if len(s) <= limit:
        return s
    return s[: max(0, limit - 1)] + "…"


def wrap(log: LogFn | None, limit: int = DEFAULT_LIMIT) -> LogFn:
    """包装 log，自动截断。"""
    if log is None:
        return lambda _m: None

    def _log(msg: str) -> None:
        log(short(msg, limit))

    return _log


def file_name(path: str | Path) -> str:
    """只取文件名，避免日志过长。"""
    return Path(path).name
