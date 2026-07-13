# -*- coding: utf-8 -*-
"""浏览器启动选项：尽量像本机手动 Chrome/Edge。

手动能过 CF、脚本不过时，优先修「自动化环境」：
1. 本机 chrome.exe / msedge.exe
2. 持久 user-data-dir（专用目录，不抢日常 Default）
3. 有头、少 flags
4. 地址/端口必须在设置路径之后重新 auto_port（DrissionPage 会清空 address）
"""

from __future__ import annotations

import os
import random
import sys
import threading
from pathlib import Path
from urllib.parse import urlparse

from grok_auto.config import ROOT, get_config, get_proxy

DEFAULT_PROFILE_DIR = ROOT / "data" / "browser_profiles" / "register"

# 多线程：端口分配锁，避免并发 auto_port 撞车
_port_lock = threading.Lock()
_used_ports: set[int] = set()


def _win_candidates(prefer: str) -> list[str]:
    local = os.environ.get("LOCALAPPDATA") or ""
    pf = os.environ.get("PROGRAMFILES") or r"C:\Program Files"
    pf86 = os.environ.get("PROGRAMFILES(X86)") or r"C:\Program Files (x86)"
    chrome: list[str] = []
    edge: list[str] = []
    for base in (local, pf, pf86):
        if not base:
            continue
        chrome.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
        chrome.append(os.path.join(base, "Chromium", "Application", "chrome.exe"))
        edge.append(os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"))
    prefer = (prefer or "auto").strip().lower()
    if prefer in ("edge", "msedge"):
        return edge + chrome
    if prefer in ("chrome", "google-chrome"):
        return chrome + edge
    return chrome + edge


def _unix_candidates(prefer: str) -> list[str]:
    chrome = [
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/snap/bin/chromium",
    ]
    edge = ["/usr/bin/microsoft-edge", "/usr/bin/microsoft-edge-stable"]
    prefer = (prefer or "auto").strip().lower()
    if prefer in ("edge", "msedge"):
        return edge + chrome
    return chrome + edge


def resolve_browser_path(cfg: dict | None = None) -> str:
    c = cfg or get_config()
    explicit = str(c.get("browser_path") or "").strip()
    if explicit and os.path.isfile(explicit):
        return explicit
    prefer = str(c.get("browser_prefer") or "auto").strip().lower()
    cands = _win_candidates(prefer) if sys.platform.startswith("win") else _unix_candidates(prefer)
    for p in cands:
        if p and os.path.isfile(p):
            return p
    return ""


def resolve_user_data_path(cfg: dict | None = None, profile_key: str | None = None) -> Path:
    """解析 profile 根目录；多线程时用 profile_key 分子目录，避免 Chrome 用户目录锁冲突。"""
    c = cfg or get_config()
    raw = str(c.get("browser_user_data_dir") or "").strip()
    if raw:
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = (ROOT / p).resolve()
    else:
        p = DEFAULT_PROFILE_DIR
    # 每线程独立 profile：register/w1、register/w2 …
    key = (profile_key or "").strip()
    if key:
        # 仅保留安全字符
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in key)[:40]
        p = p / (safe or "default")
    p.mkdir(parents=True, exist_ok=True)
    return p


def _alloc_debug_port() -> int:
    """线程安全分配本地调试端口。"""
    with _port_lock:
        for _ in range(200):
            port = random.randint(9222, 10999)
            if port in _used_ports:
                continue
            _used_ports.add(port)
            return port
        # 极端情况：清空再取
        _used_ports.clear()
        port = random.randint(9222, 10999)
        _used_ports.add(port)
        return port


def release_debug_port(port: int | None) -> None:
    """浏览器退出后释放端口占用记录。"""
    if not port:
        return
    with _port_lock:
        _used_ports.discard(int(port))


def _ensure_address(opts) -> int:
    """保证 ChromiumOptions.address 为 host:port；返回端口号。"""
    # 强制使用我们分配的端口，避免多线程 auto_port 竞态
    port = _alloc_debug_port()
    set_ok = False
    for meth_name in ("set_local_port", "set_address"):
        try:
            meth = getattr(opts, meth_name, None)
            if not callable(meth):
                continue
            if meth_name == "set_address":
                meth(f"127.0.0.1:{port}")
            else:
                meth(port)
            set_ok = True
            break
        except Exception:
            continue
    if not set_ok:
        try:
            opts.auto_port(True)
        except Exception:
            pass
    # 校验
    try:
        addr = str(getattr(opts, "address", "") or "")
        if ":" in addr:
            try:
                port = int(addr.rsplit(":", 1)[-1])
            except Exception:
                pass
    except Exception:
        pass
    return port


def create_browser_options(proxy: str | None = None, profile_key: str | None = None):
    """创建接近手动浏览器的 ChromiumOptions。

    profile_key: 多线程时传入 worker id，使每个线程独立 user-data-dir。
    未传时用当前线程 ident，保证并行安全。
    """
    from DrissionPage import ChromiumOptions

    cfg = get_config()
    opts = ChromiumOptions()

    # 未显式指定时，按线程隔离 profile（多 threads 必需）
    if profile_key is None:
        profile_key = f"t{threading.get_ident()}"

    # 窗口模式：仅有头。normal=前台；minimized=最小化；offscreen=屏外
    # 已移除 headless：无头极易被 CF/Turnstile 拦截
    window_mode = str(cfg.get("browser_window_mode") or "normal").strip().lower()
    if window_mode in ("bg", "后台", "background", "hidden"):
        window_mode = "offscreen"
    if window_mode in ("headless", "无头"):
        window_mode = "normal"
    try:
        opts.headless(False)
    except Exception:
        pass
    try:
        opts.set_timeouts(base=2)
    except Exception:
        pass

    # 1) 本机浏览器路径
    browser_path = resolve_browser_path(cfg)
    if browser_path:
        try:
            opts.set_browser_path(browser_path)
        except Exception:
            pass

    # 2) 每线程独立持久 profile（避免 SingletonLock / 多开抢同一目录）
    use_profile = bool(cfg.get("browser_use_persistent_profile", True))
    if use_profile:
        ud = resolve_user_data_path(cfg, profile_key=profile_key)
        try:
            opts.set_user_data_path(str(ud))
        except Exception:
            try:
                opts.set_paths(user_data_path=str(ud))
            except Exception:
                try:
                    opts.set_argument(f"--user-data-dir={ud}")
                except Exception:
                    pass

    # 3) 端口/地址 —— 必须在 path 设置之后，且每实例唯一
    _ensure_address(opts)

    # 4) 最小 flags（少即是多）；始终有头
    win_w = int(cfg.get("browser_window_width", 1280) or 1280)
    win_h = int(cfg.get("browser_window_height", 900) or 900)
    win_w = max(800, min(win_w, 1920))
    win_h = max(600, min(win_h, 1200))
    minimal_flags = [
        "--disable-blink-features=AutomationControlled",
        "--no-first-run",
        "--no-default-browser-check",
        f"--window-size={win_w},{win_h}",
        "--disable-infobars",
        # 后台/最小化时勿被系统节流卡死
        "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding",
        "--disable-backgrounding-occluded-windows",
    ]
    if window_mode in ("minimized", "min", "最小化"):
        minimal_flags.append("--start-minimized")
    elif window_mode in ("offscreen", "background", "hidden", "后台"):
        # 移出可见桌面，仍保留真实渲染
        ox = int(cfg.get("browser_window_x", -32000) or -32000)
        oy = int(cfg.get("browser_window_y", -32000) or -32000)
        minimal_flags.append(f"--window-position={ox},{oy}")
        if sys.platform.startswith("win"):
            minimal_flags.append("--start-minimized")
    # normal：前台可见，不加额外窗口参数
    if not sys.platform.startswith("win"):
        minimal_flags.extend(["--no-sandbox", "--disable-dev-shm-usage"])

    extra = cfg.get("browser_extra_args") or []
    if isinstance(extra, str) and extra.strip():
        extra = [extra.strip()]
    if isinstance(extra, list):
        for a in extra:
            s = str(a).strip()
            # 禁止通过 extra 偷偷打开无头
            if not s or "headless" in s.lower():
                continue
            if s not in minimal_flags:
                minimal_flags.append(s)

    for flag in minimal_flags:
        try:
            opts.set_argument(flag)
        except Exception:
            pass

    try:
        opts.set_pref("credentials_enable_service", False)
        opts.set_pref("profile.password_manager_enabled", False)
    except Exception:
        pass

    # 5) Turnstile 扩展
    if bool(cfg.get("browser_load_turnstile_patch", True)):
        ext = ROOT / "turnstilePatch"
        if ext.is_dir():
            try:
                opts.add_extension(str(ext))
            except Exception:
                pass

    # 6) 代理
    proxy_mode = str(cfg.get("browser_proxy_mode") or "config").strip().lower()
    if proxy_mode == "config":
        px = (proxy if proxy is not None else get_proxy(cfg, for_cpa=False)).strip()
        if px:
            try:
                u = urlparse(px if "://" in px else f"http://{px}")
                host = u.hostname or ""
                if host:
                    port = u.port or (443 if (u.scheme or "http") == "https" else 80)
                    scheme = u.scheme or "http"
                    opts.set_argument(f"--proxy-server={scheme}://{host}:{port}")
            except Exception:
                pass
    elif proxy_mode == "none":
        try:
            opts.set_argument("--no-proxy-server")
        except Exception:
            pass

    # 7) UA 默认不覆盖
    if bool(cfg.get("browser_force_user_agent", False)):
        ua = str(cfg.get("user_agent") or "").strip()
        if ua:
            try:
                opts.set_user_agent(ua)
            except Exception:
                pass

    # 再次钉死端口（防止中间步骤清空 address）
    _ensure_address(opts)
    return opts


def describe_browser_env(cfg: dict | None = None) -> str:
    c = cfg or get_config()
    path = resolve_browser_path(c) or "(未找到本机 Chrome/Edge)"
    ud = resolve_user_data_path(c, profile_key="w*") if c.get("browser_use_persistent_profile", True) else "(临时)"
    mode = c.get("browser_proxy_mode") or "config"
    return f"browser={path} profile_root={ud.parent if c.get('browser_use_persistent_profile', True) else ud} proxy_mode={mode}"
