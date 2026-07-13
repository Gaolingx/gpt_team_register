#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""从 data/accounts.txt 补铸缺失的 CPA JSON。"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--accounts", default=str(ROOT / "data" / "accounts.txt"))
    ap.add_argument("--limit", type=int, default=0, help="0=全部缺失")
    ap.add_argument("--config", default="")
    args = ap.parse_args()

    from grok_auto.config import load_config, resolve_path
    from grok_auto.orchestrator.ledger import existing_cpa_emails
    from grok_auto.orchestrator.pipeline import run_mint_job

    cfg = load_config(args.config or None)
    auth_dir = resolve_path(cfg.get("cpa_auth_dir"), "data/cpa_auths")
    have = existing_cpa_emails(auth_dir)
    path = Path(args.accounts)
    if not path.is_file():
        print("失败: 账本不存在", flush=True)
        return 1

    jobs = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split("----")
        if len(parts) < 3:
            continue
        email, password, sso = parts[0].strip(), parts[1].strip(), parts[2].strip()
        if email.lower() in have:
            continue
        jobs.append({"email": email, "password": password, "sso": sso, "cookies": []})

    if args.limit > 0:
        jobs = jobs[: args.limit]
    print(f"开始: 补铸 {len(jobs)} 个", flush=True)
    ok = 0
    for j in jobs:
        r = run_mint_job(j, cfg, lambda m: print(m, flush=True))
        if r.get("ok"):
            ok += 1
        time.sleep(1)
    print(f"成功: 补铸完成 {ok}/{len(jobs)}", flush=True)
    return 0 if ok or not jobs else 1


if __name__ == "__main__":
    sys.exit(main())
