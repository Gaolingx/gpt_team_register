# -*- coding: utf-8 -*-
"""事件驱动等待：替代固定 sleep。"""

from __future__ import annotations

import random
import time
from typing import Callable

# 性能开关（可由 CLI 写入）
PERF = {
    "fast": True,
    "sleep_scale": 0.15,
}


class Cancelled(Exception):
    """用户取消。"""


def raise_if_cancelled(cancel: Callable[[], bool] | None = None) -> None:
    if cancel and cancel():
        raise Cancelled("用户取消")


def sleep_with_cancel(seconds: float, cancel: Callable[[], bool] | None = None) -> None:
    deadline = time.time() + max(float(seconds), 0.0)
    while True:
        raise_if_cancelled(cancel)
        remaining = deadline - time.time()
        if remaining <= 0:
            return
        time.sleep(min(0.2, remaining))


def human_sleep(mean_seconds: float, cancel: Callable[[], bool] | None = None) -> None:
    """可缩放人类化延迟；热路径优先用 poll_wait/wait_until。"""
    scale = float(PERF.get("sleep_scale", 1.0) or 1.0)
    if PERF.get("fast"):
        scale = min(scale, 0.15)
    mean = max(0.0, float(mean_seconds) * scale)
    if mean <= 0.01:
        raise_if_cancelled(cancel)
        return
    try:
        delay = random.gauss(mean, mean * 0.3)
    except Exception:
        delay = mean
    delay = max(mean * 0.5, min(mean * 2.0, delay))
    sleep_with_cancel(delay, cancel)


def poll_wait(seconds: float = 0.2, cancel: Callable[[], bool] | None = None) -> None:
    sec = max(0.05, float(seconds or 0.2))
    if PERF.get("fast"):
        sec = min(sec, max(0.08, sec * 0.6))
    sleep_with_cancel(sec, cancel)


def wait_until(
    predicate: Callable[[], bool],
    *,
    timeout: float = 10.0,
    interval: float = 0.2,
    cancel: Callable[[], bool] | None = None,
) -> bool:
    """条件为真返回 True；超时返回 False。"""
    deadline = time.time() + max(0.1, float(timeout))
    while time.time() < deadline:
        raise_if_cancelled(cancel)
        try:
            if predicate():
                return True
        except Exception:
            pass
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        poll_wait(min(interval, remaining), cancel)
    return False
