# -*- coding: utf-8 -*-
"""注册 + 铸造流水线。

架构：
  注册线程 R  →  写账本 + 入 mint 队列（有界背压）
  铸造线程 M  →  协议优先 / 浏览器回退 → 写 xai-*.json

峰值浏览器约 R + M；注册浏览器在入队前完成会话清理/回收。
"""

from __future__ import annotations

import queue
import threading
import time
from pathlib import Path
from typing import Any, Callable

from grok_auto.browser.options import create_browser_options
from grok_auto.browser.tab_pool import TabPool
from grok_auto.config import get_proxy, resolve_path
from grok_auto.credential import mint_and_export
from grok_auto.orchestrator import ledger, metrics, pending
from grok_auto.session.browser_register import register_with_browser

LogFn = Callable[[str], None]

_stats_lock = threading.Lock()
_stats = {
    "reg_success": 0,
    "reg_fail": 0,
    "reg_retry": 0,
    "mint_success": 0,
    "mint_fail": 0,
    "mint_skip": 0,
}

# mint 队列结束哨兵
_MINT_STOP = object()


def _inc(k: str, n: int = 1) -> None:
    with _stats_lock:
        _stats[k] = _stats.get(k, 0) + n


def snapshot_stats() -> dict[str, int]:
    with _stats_lock:
        return dict(_stats)


def reset_stats() -> None:
    """批量开始前清零统计。"""
    with _stats_lock:
        for k in list(_stats.keys()):
            _stats[k] = 0


def resolve_mint_workers(
    *,
    cli_value: int,
    threads: int,
    config: dict,
    inline_mint: bool = False,
) -> int:
    """解析铸造并发。

    优先级：inline > CLI(>=0) > config cpa_mint_workers > auto。
    auto(-1)：导出开启时 min(threads, 4)，否则 0。
    0：注册线程内联铸造。
    """
    if inline_mint:
        return 0
    if cli_value >= 0:
        return max(0, min(int(cli_value), 10))
    try:
        cfg_v = int(config.get("cpa_mint_workers", -1))
    except Exception:
        cfg_v = -1
    if cfg_v >= 0:
        return max(0, min(cfg_v, 10))
    if config.get("cpa_export_enabled", True):
        return max(1, min(int(threads), 4))
    return 0


def resolve_mint_queue_max(
    config: dict,
    mint_workers: int,
    cli_value: int | None = None,
) -> int:
    """解析 mint 队列背压上限；0 表示不限制。"""
    if cli_value is not None and cli_value >= 0:
        return int(cli_value)
    try:
        v = int(config.get("cpa_mint_queue_max", 0) or 0)
    except Exception:
        v = 0
    if v > 0:
        return v
    # 默认背压：2 × mint workers
    return max(0, mint_workers * 2) if mint_workers > 0 else 0


def _export_cookies_from_job(job: dict) -> list:
    c = job.get("cookies")
    return c if isinstance(c, list) else []


def _enrich_sso_cookies(cookies: list | None, sso: str) -> list:
    """浏览器回退铸造用：把 SSO 克隆到多域名，避免域不全。"""
    base: list = list(cookies) if isinstance(cookies, list) else []
    sso_val = (sso or "").strip()
    if not sso_val:
        # 从已有 cookie 提取
        for c in base:
            if not isinstance(c, dict):
                continue
            if str(c.get("name") or "") in ("sso", "sso-rw") and c.get("value"):
                sso_val = str(c.get("value")).strip()
                break
    if not sso_val:
        return base
    seen = {
        (str(c.get("name")), str(c.get("domain")), str(c.get("path") or "/"))
        for c in base
        if isinstance(c, dict)
    }
    for name in ("sso", "sso-rw"):
        for dom in (".x.ai", "accounts.x.ai", ".accounts.x.ai", "auth.x.ai", ".auth.x.ai"):
            key = (name, dom, "/")
            if key in seen:
                continue
            base.append(
                {
                    "name": name,
                    "value": sso_val,
                    "domain": dom,
                    "path": "/",
                    "secure": True,
                    "httpOnly": True,
                }
            )
            seen.add(key)
    return base


def _append_mint_fail(auth_dir: Path, email: str, error: str) -> None:
    """铸造失败落盘，便于事后回填。"""
    try:
        auth_dir.mkdir(parents=True, exist_ok=True)
        fail_path = auth_dir / "cpa_auth_failed.txt"
        line = f"{email}----{(error or 'unknown')[:200]}----{int(time.time())}\n"
        with open(fail_path, "a", encoding="utf-8", newline="\n") as f:
            f.write(line)
    except Exception:
        pass


def _format_models(model_ids: list | None) -> str:
    """模型列表展示：优先 grok-4.5，其余逗号拼接。"""
    ids = [str(x).strip() for x in (model_ids or []) if str(x).strip()]
    if not ids:
        return "未知"
    # 去重保序
    seen: set[str] = set()
    ordered: list[str] = []
    for mid in ids:
        if mid in seen:
            continue
        seen.add(mid)
        ordered.append(mid)
    # grok-4.5 置前
    ordered.sort(key=lambda x: (0 if x == "grok-4.5" else 1, x))
    return "、".join(ordered)


def _emit_mint_success(
    path: str,
    model_ids: list | None,
    emit: LogFn | None,
    *,
    thread_id: str | int | None = None,
) -> None:
    """唯一对外日志：铸造成功一行。

    格式：[时间] [线程xxx] grok注册成功，获取模型xxx，铸造成功且文件为：文件名称.json
    """
    models = _format_models(model_ids)
    tid = str(thread_id or "").strip() or "主"
    # 只展示文件名，不暴露完整路径
    name = Path(str(path or "")).name or str(path or "")
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] [线程{tid}] grok注册成功，获取模型{models}，铸造成功且文件为：{name}"
    if emit is not None:
        emit(line)
    else:
        print(line, flush=True)


def run_mint_job(
    job: dict[str, Any],
    cfg: dict,
    log: LogFn | None = None,
    *,
    thread_id: str | int | None = None,
) -> dict[str, Any]:
    """铸造一个账号的 CPA JSON（不热加载）。

    仅在铸造成功且写出文件时输出一行日志；其余静默。
    log 仅用于成功行输出（不做截断包装）。
    """
    quiet: LogFn = lambda _m: None
    email = str(job.get("email") or "")
    password = str(job.get("password") or "")
    sso = str(job.get("sso") or "")
    # 线程标识：显式参数 > job 内字段 > 默认
    tid = thread_id if thread_id is not None else job.get("thread_id")
    if not cfg.get("cpa_export_enabled", True):
        _inc("mint_skip")
        return {"ok": False, "skipped": True, "reason": "disabled"}

    auth_dir = resolve_path(cfg.get("cpa_auth_dir"), "data/cpa_auths")
    proxy = get_proxy(cfg, for_cpa=True)
    pending_path = resolve_path(cfg.get("cpa_mint_pending_file"), "data/mint_pending.jsonl")
    metrics_path = resolve_path(cfg.get("metrics_file"), "data/run_metrics.jsonl")

    # 浏览器回退时注入多域 SSO cookie
    raw_cookies = _export_cookies_from_job(job) if cfg.get("cpa_mint_cookie_inject", True) else None
    cookies = _enrich_sso_cookies(raw_cookies, sso) if raw_cookies is not None or sso else None

    t0 = time.perf_counter()
    try:
        result = mint_and_export(
            email=email,
            password=password,
            auth_dir=auth_dir,
            proxy=proxy or None,
            headless=False,
            base_url=str(cfg.get("cpa_base_url") or "https://cli-chat-proxy.grok.com/v1"),
            # 成功行需要模型名：内部始终探测 models；此处 probe 仅控制是否因缺模型判失败
            probe=bool(cfg.get("cpa_probe_after_write", False)),
            probe_chat=bool(cfg.get("cpa_probe_chat", False)),
            browser_timeout_sec=float(cfg.get("cpa_mint_timeout_sec", 300) or 300),
            force_standalone=bool(cfg.get("cpa_force_standalone", True)),
            cookies=cookies,
            sso=sso or None,
            reuse_browser=bool(cfg.get("cpa_mint_browser_reuse", True)),
            recycle_every=int(cfg.get("cpa_mint_browser_recycle_every", 15) or 15),
            prefer_protocol=bool(cfg.get("cpa_prefer_protocol", True)),
            protocol_only=bool(cfg.get("cpa_protocol_only", False)),
            protocol_poll_timeout_sec=float(cfg.get("cpa_protocol_poll_timeout_sec", 90) or 90),
            log=quiet,
        )
        # 文件已写出时，缺模型默认仍视为成功（除非强制 probe_required）
        err = str(result.get("error") or "")
        if (
            not result.get("ok")
            and result.get("path")
            and ("grok-4.5" in err or "未列出" in err)
            and not cfg.get("cpa_probe_required", False)
        ):
            result["ok"] = True
            result["probe_warning"] = result.pop("error", "")

        if result.get("ok") and result.get("path") and cfg.get("cpa_copy_to_hotload", False):
            hot = str(cfg.get("cpa_hotload_dir") or "").strip()
            if hot:
                try:
                    import shutil
                    import os

                    src = Path(result["path"])
                    dst_dir = resolve_path(hot, hot)
                    dst_dir.mkdir(parents=True, exist_ok=True)
                    dst = dst_dir / src.name
                    shutil.copy2(src, dst)
                    os.chmod(dst, 0o600)
                except Exception:
                    pass

        ms = (time.perf_counter() - t0) * 1000
        metrics.emit(
            metrics_path,
            {
                "kind": "mint",
                "ok": bool(result.get("ok")),
                "email": email,
                "total_ms": round(ms, 1),
                "mint_method": result.get("mint_method"),
                "error": str(result.get("error") or "")[:300],
                "path": result.get("path") or "",
            },
        )
        if result.get("ok") and result.get("path"):
            _inc("mint_success")
            _emit_mint_success(
                str(result.get("path")),
                result.get("model_ids") if isinstance(result.get("model_ids"), list) else [],
                log,
                thread_id=tid,
            )
            if cfg.get("cpa_mint_pending_enabled", True):
                pending.mark_done(pending_path, email)
        else:
            _inc("mint_fail")
            _append_mint_fail(auth_dir, email, str(result.get("error") or ""))
            if cfg.get("cpa_mint_pending_enabled", True):
                pending.mark_failed(pending_path, email, str(result.get("error") or ""))
        return result
    except Exception as e:
        _inc("mint_fail")
        _append_mint_fail(auth_dir, email, str(e))
        if cfg.get("cpa_mint_pending_enabled", True):
            pending.mark_failed(pending_path, email, str(e))
        return {"ok": False, "error": str(e), "email": email}


def _enqueue_mint(
    job: dict[str, Any],
    *,
    mint_queue: queue.Queue | None,
    do_mint_inline: bool,
    cfg: dict,
    log: LogFn | None,
    thread_id: str | int | None = None,
) -> None:
    """内联铸造或带背压入队（静默）。"""
    if not cfg.get("cpa_export_enabled", True):
        return
    if thread_id is not None and not job.get("thread_id"):
        job["thread_id"] = thread_id
    if do_mint_inline:
        run_mint_job(job, cfg, log, thread_id=job.get("thread_id") or thread_id)
        return
    if mint_queue is None:
        return

    qmax = int(getattr(mint_queue, "_reg_qmax", 0) or 0)
    while qmax > 0 and mint_queue.qsize() >= qmax:
        time.sleep(1.0)
    mint_queue.put(job)


def register_one(
    *,
    cfg: dict,
    accounts_file: Path,
    log: LogFn | None = None,
    do_mint_inline: bool = False,
    mint_queue: queue.Queue | None = None,
    account_retries: int = 1,
    thread_id: str | int | None = None,
) -> dict | None:
    """注册一号；成功写账本并提交铸造。

    过程静默；仅铸造成功时由 run_mint_job 输出一行。
    account_retries：整号失败后再试次数（默认 1 = 最多 2 次尝试）。
    """
    quiet: LogFn = lambda _m: None
    metrics_path = resolve_path(cfg.get("metrics_file"), "data/run_metrics.jsonl")
    pending_path = resolve_path(cfg.get("cpa_mint_pending_file"), "data/mint_pending.jsonl")
    recycle = int(cfg.get("browser_recycle_every", 25) or 25)
    max_attempts = max(1, int(account_retries) + 1)

    for attempt in range(1, max_attempts + 1):
        # 确保浏览器
        if TabPool.get_browser() is None:
            try:
                TabPool.get_tab()
            except Exception:
                break

        if attempt > 1:
            _inc("reg_retry")
            try:
                TabPool.prepare_for_next(recycle_every=1, force=True, log=None)
            except Exception:
                try:
                    TabPool.release_tab()
                except Exception:
                    pass

        # 注册过程完全静默
        result = register_with_browser(cfg=cfg, log=quiet)
        metrics.emit(
            metrics_path,
            {
                "kind": "register",
                "ok": result.ok,
                "email": (result.account.email if result.account else ""),
                "stage": result.stage,
                "error": result.error[:300],
                "attempt": attempt,
                "stages_ms": {k: round(v, 1) for k, v in (result.stages_ms or {}).items()},
            },
        )
        if result.ok and result.account:
            acc = result.account
            ledger.append_account(accounts_file, acc)
            _inc("reg_success")

            job = {
                "email": acc.email,
                "password": acc.password,
                "sso": acc.sso,
                "cookies": acc.cookies,
                "thread_id": thread_id or "主",
            }
            if cfg.get("cpa_export_enabled", True) and cfg.get("cpa_mint_pending_enabled", True):
                try:
                    pending.enqueue(pending_path, job)
                except Exception:
                    pass

            # 注册浏览器回收，再 mint（静默）
            try:
                TabPool.prepare_for_next(recycle_every=recycle, log=None)
            except Exception:
                pass

            _enqueue_mint(
                job,
                mint_queue=mint_queue,
                do_mint_inline=do_mint_inline,
                cfg=cfg,
                log=log,
                thread_id=thread_id or job.get("thread_id"),
            )
            return job

        try:
            TabPool.release_tab()
        except Exception:
            pass
        if attempt < max_attempts:
            time.sleep(0.5)
            continue
        break

    _inc("reg_fail")
    try:
        TabPool.release_tab()
        TabPool.get_tab()
    except Exception:
        pass
    return None


def run_batch(
    *,
    extra: int = 0,
    count: int | None = None,
    threads: int = 1,
    mint_workers: int = -1,
    mint_queue_max: int = -1,
    accounts_file: str | Path | None = None,
    config_path: str | None = None,
    account_retries: int | None = None,
    disable_probe: bool = False,
    log_print: Callable[[str], None] | None = None,
) -> int:
    """批量注册入口。

    - extra>0：在已有账本上再注册 N 个
    - count 不为 None：目标总数（含已有）；0 表示不限量（谨慎）
    - 二者都未给时默认 extra=1
    """
    from grok_auto.config import load_config

    cfg = load_config(config_path)
    if disable_probe:
        cfg["cpa_probe_after_write"] = False
        cfg["cpa_probe_chat"] = False
    if account_retries is None:
        try:
            account_retries = int(cfg.get("register_account_retries", 1) or 1)
        except Exception:
            account_retries = 1
    account_retries = max(0, int(account_retries))
    # 仅用于成功行输出；过程静默
    out = log_print or (lambda m: print(m, flush=True))
    reset_stats()

    acc_path = resolve_path(
        accounts_file if accounts_file is not None else cfg.get("accounts_file"),
        "data/accounts.txt",
    )
    done = ledger.count_accounts(acc_path)
    threads = max(1, min(int(threads), 8))

    # 解析本批要新注册的数量
    forever = False
    if extra and extra > 0:
        remaining = int(extra)
        target_total = done + remaining
    elif count is not None:
        if int(count) == 0:
            forever = True
            remaining = threads * 5  # 初始灌入
            target_total = 0
        else:
            remaining = max(0, int(count) - done)
            target_total = int(count)
    else:
        remaining = 1
        target_total = done + 1

    mw = resolve_mint_workers(
        cli_value=int(mint_workers),
        threads=threads,
        config=cfg,
        inline_mint=False,
    )
    do_inline = mw == 0
    qmax = resolve_mint_queue_max(
        cfg,
        mw,
        cli_value=(None if mint_queue_max < 0 else mint_queue_max),
    )

    if not forever and remaining <= 0:
        return 0

    # 日志队列：只转发铸造成功完整行，不做截断
    log_q: queue.Queue = queue.Queue()

    def _writer():
        while True:
            m = log_q.get()
            if m is None:
                break
            out(m)

    def make_success_log(_wid: str = "") -> LogFn:
        """成功行专用：原样输出，不截断、不加 worker 前缀。"""

        def _log(msg: str) -> None:
            log_q.put(str(msg))

        return _log

    wt = threading.Thread(target=_writer, daemon=True)
    wt.start()

    def _opts_factory(profile_key: str | None = None):
        return create_browser_options(profile_key=profile_key)

    TabPool.init(_opts_factory, log=None)

    mint_q: queue.Queue | None = queue.Queue() if not do_inline else None
    if mint_q is not None:
        mint_q._reg_qmax = qmax  # type: ignore[attr-defined]
    mint_threads: list[threading.Thread] = []
    success_log = make_success_log()

    def mint_worker(wid: str):
        while True:
            job = mint_q.get()  # type: ignore
            try:
                if job is _MINT_STOP:
                    break
                if isinstance(job, dict):
                    # 优先显示注册线程（R1）；无则用铸造线程（M1）
                    run_mint_job(
                        job,
                        cfg,
                        success_log,
                        thread_id=job.get("thread_id") or wid,
                    )
            finally:
                mint_q.task_done()  # type: ignore
        try:
            from grok_auto.credential.browser_confirm import shutdown_mint_browsers

            shutdown_mint_browsers()
        except Exception:
            pass

    if mint_q is not None and mw > 0:
        for i in range(1, mw + 1):
            t = threading.Thread(target=mint_worker, args=(f"M{i}",), daemon=True, name=f"mint-{i}")
            t.start()
            mint_threads.append(t)

    # 恢复 pending（静默）
    if cfg.get("cpa_export_enabled", True) and cfg.get("cpa_mint_pending_enabled", True):
        ppath = resolve_path(cfg.get("cpa_mint_pending_file"), "data/mint_pending.jsonl")
        auth_dir = resolve_path(cfg.get("cpa_auth_dir"), "data/cpa_auths")
        existing = ledger.existing_cpa_emails(auth_dir)
        recs = pending.list_recoverable(ppath, int(cfg.get("cpa_mint_pending_max_attempts", 5) or 5))
        for row in recs:
            email = str(row.get("email_raw") or row.get("email") or "")
            if email.lower() in existing:
                pending.mark_done(ppath, email)
                continue
            job = {
                "email": email,
                "password": row.get("password") or "",
                "sso": row.get("sso") or "",
                "cookies": [],
                "thread_id": "恢复",
            }
            if do_inline:
                run_mint_job(job, cfg, success_log, thread_id="恢复")
            elif mint_q is not None:
                _enqueue_mint(
                    job,
                    mint_queue=mint_q,
                    do_mint_inline=False,
                    cfg=cfg,
                    log=success_log,
                    thread_id="恢复",
                )

    task_q: queue.Queue = queue.Queue()
    next_idx_lock = threading.Lock()
    next_idx = [1]

    if forever:
        for i in range(1, remaining + 1):
            task_q.put(i)
        next_idx[0] = remaining + 1
    else:
        for i in range(1, remaining + 1):
            task_q.put(i)

    def reg_worker(wid: int, start_delay: float = 0.0):
        reg_tid = f"R{wid}"
        if start_delay > 0:
            time.sleep(start_delay)
        TabPool.set_worker_id(reg_tid)
        while True:
            try:
                _idx = task_q.get_nowait()
            except queue.Empty:
                if not forever:
                    break
                # 不限量：每次追加 5 个任务
                with next_idx_lock:
                    base = next_idx[0]
                    next_idx[0] = base + 5
                for i in range(base, base + 5):
                    task_q.put(i)
                continue
            try:
                register_one(
                    cfg=cfg,
                    accounts_file=acc_path,
                    log=success_log,
                    do_mint_inline=do_inline,
                    mint_queue=mint_q,
                    account_retries=account_retries,
                    thread_id=reg_tid,
                )
            except Exception:
                try:
                    TabPool.release_tab()
                except Exception:
                    pass
            finally:
                try:
                    task_q.task_done()
                except Exception:
                    pass
        try:
            TabPool.release_tab()
        except Exception:
            pass

    reg_threads = []
    try:
        stagger = float(cfg.get("thread_start_interval", 1.5) or 1.5)
    except Exception:
        stagger = 1.5
    stagger = max(0.0, min(stagger, 10.0))
    for i in range(1, threads + 1):
        t = threading.Thread(
            target=reg_worker,
            args=(i, stagger * (i - 1)),
            daemon=True,
            name=f"reg-{i}",
        )
        t.start()
        reg_threads.append(t)

    try:
        for t in reg_threads:
            t.join()
    except KeyboardInterrupt:
        pass

    if mint_q is not None:
        mint_q.join()
        for _ in mint_threads:
            mint_q.put(_MINT_STOP)
        for t in mint_threads:
            t.join(timeout=600)

    try:
        TabPool.shutdown()
    except Exception:
        pass
    try:
        from grok_auto.credential.browser_confirm import shutdown_mint_browsers

        shutdown_mint_browsers()
    except Exception:
        pass

    log_q.put(None)
    wt.join(timeout=2)

    s = snapshot_stats()
    # 无控制台汇总；仅靠成功行与退出码
    return 0 if s["reg_success"] > 0 or s["mint_success"] > 0 or (not forever and remaining <= 0) else 1
