#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Grok 自动注册 CLI（重写版）。

用法:
  uv run python register_cli.py --extra 1
  uv run python register_cli.py --count 100 --threads 2 --mint-workers 2
  uv run python register_cli.py --extra 5 --threads 2 --mint-queue-max 4
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 保证仓库根在 path
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Grok 自动注册 + CPA JSON 铸造")
    parser.add_argument(
        "--count",
        type=int,
        default=None,
        help="账号总数目标（含已有账本行；0=不限量）",
    )
    parser.add_argument(
        "--extra",
        type=int,
        default=0,
        help="在已有账本上再注册 N 个（优先于 --count 的「差量」语义）",
    )
    parser.add_argument("--threads", type=int, default=1, help="注册线程 1-8")
    parser.add_argument(
        "--mint-workers",
        type=int,
        default=-1,
        help="铸造并发：-1=自动；0=内联；1-10=固定",
    )
    parser.add_argument(
        "--mint-queue-max",
        type=int,
        default=-1,
        help="铸造队列背压：-1=自动(约2×workers)；0=不限制",
    )
    parser.add_argument(
        "--accounts-file",
        default="",
        help="账本路径，默认读配置 accounts_file",
    )
    parser.add_argument(
        "--account-retries",
        type=int,
        default=1,
        help="整号失败后再试次数（默认 1=最多 2 次）",
    )
    parser.add_argument("--config", default="", help="配置文件路径，默认 ./config.json")
    parser.add_argument("--no-fast", action="store_true", help="关闭快速等待缩放")
    parser.add_argument(
        "--no-probe",
        action="store_true",
        help="铸造后不探测模型（批量加速）",
    )
    args = parser.parse_args()

    from grok_auto.browser import waits
    from grok_auto.orchestrator.pipeline import run_batch

    waits.PERF["fast"] = not args.no_fast
    waits.PERF["sleep_scale"] = 1.0 if args.no_fast else 0.15

    extra = max(0, int(args.extra or 0))
    count = args.count
    # 兼容：两者都没给时默认 extra=1
    if extra <= 0 and count is None:
        extra = 1

    return run_batch(
        extra=extra,
        count=count,
        threads=max(1, min(int(args.threads), 8)),
        mint_workers=int(args.mint_workers),
        mint_queue_max=int(args.mint_queue_max),
        accounts_file=(args.accounts_file or None),
        config_path=args.config or None,
        account_retries=max(0, int(args.account_retries)),
        disable_probe=bool(args.no_probe),
    )


if __name__ == "__main__":
    sys.exit(main())
