# -*- coding: utf-8 -*-
"""将 pipeline 日志收成关键步骤约 20 字。"""
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "grok_auto" / "orchestrator" / "pipeline.py"
t = p.read_text(encoding="utf-8")

# run_mint_job 整段替换更稳
old = '''def run_mint_job(job: dict[str, Any], cfg: dict, log: LogFn) -> dict[str, Any]:
    """铸造一个账号的 CPA JSON（不热加载）。"""
    email = str(job.get("email") or "")
    password = str(job.get("password") or "")
    sso = str(job.get("sso") or "")
    if not cfg.get("cpa_export_enabled", True):
        _inc("mint_skip")
        log("铸造已关闭，本号跳过")
        return {"ok": False, "skipped": True, "reason": "disabled"}

    auth_dir = resolve_path(cfg.get("cpa_auth_dir"), "data/cpa_auths")
    proxy = get_proxy(cfg, for_cpa=True)
    pending_path = resolve_path(cfg.get("cpa_mint_pending_file"), "data/mint_pending.jsonl")
    metrics_path = resolve_path(cfg.get("metrics_file"), "data/run_metrics.jsonl")

    log("开始铸造本号认证")
    t0 = time.perf_counter()
    try:
        result = mint_and_export(
            email=email,
            password=password,
            auth_dir=auth_dir,
            proxy=proxy or None,
            headless=bool(cfg.get("cpa_headless", False)),
            base_url=str(cfg.get("cpa_base_url") or "https://cli-chat-proxy.grok.com/v1"),
            probe=bool(cfg.get("cpa_probe_after_write", True)),
            probe_chat=bool(cfg.get("cpa_probe_chat", False)),
            browser_timeout_sec=float(cfg.get("cpa_mint_timeout_sec", 300) or 300),
            force_standalone=bool(cfg.get("cpa_force_standalone", True)),
            cookies=_export_cookies_from_job(job) if cfg.get("cpa_mint_cookie_inject", True) else None,
            sso=sso or None,
            reuse_browser=bool(cfg.get("cpa_mint_browser_reuse", True)),
            recycle_every=int(cfg.get("cpa_mint_browser_recycle_every", 15) or 15),
            prefer_protocol=bool(cfg.get("cpa_prefer_protocol", True)),
            protocol_only=bool(cfg.get("cpa_protocol_only", False)),
            protocol_poll_timeout_sec=float(cfg.get("cpa_protocol_poll_timeout_sec", 90) or 90),
            log=log,
        )
        # probe 失败默认警告（文件已写出）
        err = str(result.get("error") or "")
        if (
            not result.get("ok")
            and result.get("path")
            and ("grok-4.5" in err or "未列出" in err)
            and not cfg.get("cpa_probe_required", False)
        ):
            result["ok"] = True
            result["probe_warning"] = result.pop("error", "")

        # 明确不热加载：即使配置误开也忽略（本项目默认策略）
        # 若用户将来要开，可读 cpa_copy_to_hotload —— 此处仍尊重 false 默认
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
                    log("已复制到热加载目录")
                except Exception as e:
                    log("复制到热加载目录失败")

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
        if result.get("ok"):
            _inc("mint_success")
            method = result.get("mint_method") or "?"
            log(f"本号铸造成功，方式:{method}")
            if cfg.get("cpa_mint_pending_enabled", True):
                pending.mark_done(pending_path, email)
        else:
            _inc("mint_fail")
            log("本号铸造失败")
            if cfg.get("cpa_mint_pending_enabled", True):
                pending.mark_failed(pending_path, email, str(result.get("error") or ""))
        return result
    except Exception as e:
        _inc("mint_fail")
        log("铸造过程发生异常")
        if cfg.get("cpa_mint_pending_enabled", True):
            pending.mark_failed(pending_path, email, str(e))
        return {"ok": False, "error": str(e), "email": email}
'''

new = '''def run_mint_job(job: dict[str, Any], cfg: dict, log: LogFn) -> dict[str, Any]:
    """铸造一个账号的 CPA JSON（不热加载）。"""
    from grok_auto.logging_short import file_name, wrap as wrap_log

    log = wrap_log(log)
    email = str(job.get("email") or "")
    password = str(job.get("password") or "")
    sso = str(job.get("sso") or "")
    if not cfg.get("cpa_export_enabled", True):
        _inc("mint_skip")
        log("铸造已关闭已跳过")
        return {"ok": False, "skipped": True, "reason": "disabled"}

    auth_dir = resolve_path(cfg.get("cpa_auth_dir"), "data/cpa_auths")
    proxy = get_proxy(cfg, for_cpa=True)
    pending_path = resolve_path(cfg.get("cpa_mint_pending_file"), "data/mint_pending.jsonl")
    metrics_path = resolve_path(cfg.get("metrics_file"), "data/run_metrics.jsonl")

    t0 = time.perf_counter()
    try:
        result = mint_and_export(
            email=email,
            password=password,
            auth_dir=auth_dir,
            proxy=proxy or None,
            headless=bool(cfg.get("cpa_headless", False)),
            base_url=str(cfg.get("cpa_base_url") or "https://cli-chat-proxy.grok.com/v1"),
            probe=bool(cfg.get("cpa_probe_after_write", True)),
            probe_chat=bool(cfg.get("cpa_probe_chat", False)),
            browser_timeout_sec=float(cfg.get("cpa_mint_timeout_sec", 300) or 300),
            force_standalone=bool(cfg.get("cpa_force_standalone", True)),
            cookies=_export_cookies_from_job(job) if cfg.get("cpa_mint_cookie_inject", True) else None,
            sso=sso or None,
            reuse_browser=bool(cfg.get("cpa_mint_browser_reuse", True)),
            recycle_every=int(cfg.get("cpa_mint_browser_recycle_every", 15) or 15),
            prefer_protocol=bool(cfg.get("cpa_prefer_protocol", True)),
            protocol_only=bool(cfg.get("cpa_protocol_only", False)),
            protocol_poll_timeout_sec=float(cfg.get("cpa_protocol_poll_timeout_sec", 90) or 90),
            log=log,
        )
        # probe 失败默认警告（文件已写出）
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
        if result.get("ok"):
            _inc("mint_success")
            name = file_name(result.get("path") or "")
            log(f"最终成功:{name or '已写出'}")
            if cfg.get("cpa_mint_pending_enabled", True):
                pending.mark_done(pending_path, email)
        else:
            _inc("mint_fail")
            log("最终失败:铸造未成功")
            if cfg.get("cpa_mint_pending_enabled", True):
                pending.mark_failed(pending_path, email, str(result.get("error") or ""))
        return result
    except Exception as e:
        _inc("mint_fail")
        log("最终失败:铸造异常")
        if cfg.get("cpa_mint_pending_enabled", True):
            pending.mark_failed(pending_path, email, str(e))
        return {"ok": False, "error": str(e), "email": email}
'''

if old not in t:
    raise SystemExit('run_mint_job block not found')
t = t.replace(old, new)

# register_one tail
old2 = '''    if not result.ok or not result.account:
        _inc("reg_fail")
        try:
            TabPool.release_tab()
            TabPool.get_tab()
        except Exception:
            pass
        return None

    acc = result.account
    ledger.append_account(accounts_file, acc)
    _inc("reg_success")

    job = {
        "email": acc.email,
        "password": acc.password,
        "sso": acc.sso,
        "cookies": acc.cookies,
    }
    if cfg.get("cpa_export_enabled", True) and cfg.get("cpa_mint_pending_enabled", True):
        try:
            pending.enqueue(pending_path, job)
        except Exception as e:
            log("待铸造任务落盘失败")

    # 注册浏览器回收，再 mint
    try:
        TabPool.prepare_for_next(recycle_every=recycle, log=log)
    except Exception:
        pass

    if not cfg.get("cpa_export_enabled", True):
        log("配置关闭，跳过铸造")
        return job

    if do_mint_inline:
        run_mint_job(job, cfg, log)
    elif mint_queue is not None:
        mint_queue.put(job)
        log("已提交铸造任务到队列")
    return job
'''
new2 = '''    if not result.ok or not result.account:
        _inc("reg_fail")
        log("最终失败:注册未成功")
        try:
            TabPool.release_tab()
            TabPool.get_tab()
        except Exception:
            pass
        return None

    acc = result.account
    ledger.append_account(accounts_file, acc)
    _inc("reg_success")

    job = {
        "email": acc.email,
        "password": acc.password,
        "sso": acc.sso,
        "cookies": acc.cookies,
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

    if not cfg.get("cpa_export_enabled", True):
        log("最终成功:仅注册完成")
        return job

    if do_mint_inline:
        run_mint_job(job, cfg, log)
    elif mint_queue is not None:
        mint_queue.put(job)
    return job
'''
if old2 not in t:
    raise SystemExit('register_one tail not found')
t = t.replace(old2, new2)

# startup/end quieter
t = t.replace(
    '''    out(short(f"开始批量注册{extra}个号，注册线程{threads}，铸造线程{mint_workers}", 50))
    out(short(f"邮箱通道{cfg.get('email_provider')}，写出CPA={cfg.get('cpa_export_enabled')}", 50))
    out(short("浏览器使用本机Chrome并按线程隔离配置", 50))''',
    '''    out(short(f"开始注册{extra}个号 线程{threads}", 28))''',
)
t = t.replace(
    '''    def make_log(wid: str) -> LogFn:
        def _log(msg: str) -> None:
            # 步骤日志：写清楚，最长 50 字
            log_q.put(f"[{time.strftime('%H:%M:%S')}] [{wid}] {short(msg, 50)}")

        return wrap_log(_log, 50)''',
    '''    def make_log(wid: str) -> LogFn:
        def _log(msg: str) -> None:
            # 关键步骤日志，约 20 字，最长 28
            log_q.put(f"[{time.strftime('%H:%M:%S')}] [{wid}] {short(msg, 28)}")

        return wrap_log(_log, 28)''',
)
t = t.replace('TabPool.init(_opts_factory, log=make_log("0"))', 'TabPool.init(_opts_factory, log=None)')
t = t.replace('            out(short(f"已恢复待铸造任务{nrec}条", 50))', '            out(short(f"恢复待铸造{nrec}条", 28))')
t = t.replace('        lg(f"注册线程R{wid}已就绪")\n', '')
t = t.replace('            lg(f"开始注册第{idx}/{extra}个账号")\n', '')
t = t.replace('                lg("注册线程发生异常")\n', '                lg("注册异常")\n')
t = t.replace('        make_log("0")("等待铸造队列清空中")\n', '')
t = t.replace('        make_log("0")("铸造队列已全部清空")\n', '')
t = t.replace(
    '''    out(short(
        f"本轮结束：注册成功{s['reg_success']}失败{s['reg_fail']}，"
        f"铸造成功{s['mint_success']}失败{s['mint_fail']}",
        50,
    ))''',
    '''    out(short(
        f"结束 注册{s['reg_success']}/{s['reg_fail']} 铸造{s['mint_success']}/{s['mint_fail']}",
        28,
    ))''',
)

# silence tab_pool logs by default calls already None in places
p.write_text(t, encoding="utf-8", newline="\n")
print("pipeline patched")
