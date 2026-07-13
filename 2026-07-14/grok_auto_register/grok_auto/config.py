# -*- coding: utf-8 -*-
"""配置加载：UTF-8 无 BOM；忽略 // 与 # 注释键。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# 仓库根
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config.json"
EXAMPLE_CONFIG_PATH = ROOT / "config.example.json"

# 进程内配置
_config: dict[str, Any] = {}


def default_config() -> dict[str, Any]:
    """内置默认（Cloudflare 邮箱 + 写 CPA JSON + 不热加载）。"""
    return {
        "email_provider": "cloudflare",  # cloudflare | duckmail | yyds | tempmail_lol
        "defaultDomains": "",
        "cloudflare_api_base": "",
        "cloudflare_api_key": "",
        "cloudflare_auth_mode": "x-admin-auth",
        "cloudflare_path_domains": "/api/domains",
        "cloudflare_path_accounts": "/admin/new_address",
        "cloudflare_path_token": "/api/token",
        "cloudflare_path_messages": "/api/mails",
        # DuckMail：https://api.duckmail.sbs
        "duckmail_api_base": "https://api.duckmail.sbs",
        "duckmail_api_key": "",
        # YYDS：https://maliapi.215.im/v1
        "yyds_api_base": "https://maliapi.215.im/v1",
        "yyds_api_key": "",
        "yyds_jwt": "",
        "yyds_preferred_domains": "",
        "yyds_blocked_domains": "",
        "yyds_domain_selection": "random",  # random | first
        # TempMail.lol：https://api.tempmail.lol/v2 （免费可无 key）
        "tempmail_lol_api_base": "https://api.tempmail.lol/v2",
        "tempmail_lol_api_key": "",
        "tempmail_lol_domain": "",
        "tempmail_lol_prefix": "",
        "tempmail_lol_random_prefix": True,
        "tempmail_lol_community": None,
        "proxy": "http://127.0.0.1:7890",
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
        ),
        "register_threads": 1,
        "thread_start_interval": 1.5,
        "mail_timeout": 150,
        "mail_poll_interval": 0.3,
        "mail_retry_count": 3,
        "turnstile_stuck_timeout": 90,
        "browser_recycle_every": 25,
        # 浏览器：贴近手动 Chrome/Edge，降低 CF 自动化识别
        "browser_prefer": "auto",  # auto | chrome | edge
        "browser_path": "",  # 可填本机 chrome.exe / msedge.exe 绝对路径
        "browser_use_persistent_profile": True,
        "browser_user_data_dir": "data/browser_profiles/register",
        "browser_proxy_mode": "config",  # config | system | none（system=跟手动系统代理更像）
        "browser_load_turnstile_patch": True,
        "browser_force_user_agent": False,
        "browser_extra_args": [],
        # 注册浏览器窗口：normal=前台（默认）；offscreen=屏外+最小化；minimized=仅最小化（已移除无头）
        "browser_window_mode": "normal",
        "browser_window_width": 1280,
        "browser_window_height": 900,
        "browser_window_x": -32000,
        "browser_window_y": -32000,
        "accounts_file": "data/accounts.txt",
        # CPA：自动铸造 JSON，默认不热加载上号
        "cpa_export_enabled": True,
        "cpa_auth_dir": "data/cpa_auths",
        "cpa_copy_to_hotload": False,
        "cpa_hotload_dir": "",
        "cpa_base_url": "https://cli-chat-proxy.grok.com/v1",
        "cpa_proxy": "",
        "cpa_force_standalone": True,
        "cpa_mint_timeout_sec": 300,
        "cpa_mint_required": False,
        # 批量默认建议关探测；需要校验时再开或 CLI 不加 --no-probe
        "cpa_probe_after_write": False,
        "cpa_probe_required": False,
        "cpa_probe_chat": False,
        "cpa_prefer_protocol": True,
        "cpa_protocol_only": False,
        "cpa_protocol_poll_timeout_sec": 90,
        "cpa_mint_cookie_inject": True,
        "cpa_mint_browser_reuse": True,
        "cpa_mint_browser_recycle_every": 15,
        "cpa_mint_workers": -1,
        # 0=自动 2×mint_workers；>0 固定上限；配合 CLI --mint-queue-max
        "cpa_mint_queue_max": 0,
        "register_account_retries": 1,
        "cpa_mint_pending_enabled": True,
        "cpa_mint_pending_file": "data/mint_pending.jsonl",
        "cpa_mint_pending_max_attempts": 5,
        "metrics_file": "data/run_metrics.jsonl",
    }


def _strip_comment_keys(data: dict) -> dict[str, Any]:
    return {
        k: v
        for k, v in data.items()
        if not str(k).startswith("//") and not str(k).startswith("#")
    }


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """加载配置：默认值 ← example ← config.json ← 环境变量轻量覆盖。"""
    global _config
    cfg = default_config()
    for candidate in (EXAMPLE_CONFIG_PATH, Path(path) if path else DEFAULT_CONFIG_PATH):
        p = Path(candidate)
        if not p.is_file():
            continue
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                cfg.update(_strip_comment_keys(raw))
        except Exception:
            continue
    # 环境变量可覆盖代理
    for env_k, cfg_k in (
        ("GROK_PROXY", "proxy"),
        ("GROK_CPA_PROXY", "cpa_proxy"),
        ("CLOUDFLARE_API_BASE", "cloudflare_api_base"),
        ("CLOUDFLARE_API_KEY", "cloudflare_api_key"),
    ):
        v = (os.environ.get(env_k) or "").strip()
        if v:
            cfg[cfg_k] = v
    _config = cfg
    return cfg


def get_config() -> dict[str, Any]:
    if not _config:
        return load_config()
    return _config


def resolve_path(value: str | Path | None, default_rel: str) -> Path:
    """相对路径相对仓库根。"""
    raw = str(value or default_rel).strip() or default_rel
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = (ROOT / p).resolve()
    return p


def get_proxy(cfg: dict | None = None, *, for_cpa: bool = False) -> str:
    """代理优先级：cpa_proxy(若 for_cpa) > proxy > 环境变量。"""
    c = cfg or get_config()
    if for_cpa:
        p = (c.get("cpa_proxy") or c.get("proxy") or "").strip()
    else:
        p = (c.get("proxy") or "").strip()
    if p:
        return p
    return (
        os.environ.get("https_proxy")
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("http_proxy")
        or ""
    ).strip()
