# -*- coding: utf-8 -*-
"""邮箱 HTTP 公共工具：curl_cffi Session + 代理。"""

from __future__ import annotations

from typing import Any

from curl_cffi import requests as cf_requests

from grok_auto.config import get_proxy


def make_session(proxy: str | None = None, cfg: dict | None = None) -> Any:
    """创建带可选代理的 Session。"""
    s = cf_requests.Session()
    px = (proxy if proxy is not None else get_proxy(cfg, for_cpa=False) if cfg else "").strip()
    if px:
        s.proxies = {"http": px, "https": px}
    return s


def split_list(value: Any) -> list[str]:
    """逗号/空白分隔配置列表。"""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(x).strip() for x in value if str(x).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    import re

    return [x.strip() for x in re.split(r"[,，\s]+", text) if x.strip()]


def pick_messages_payload(data: Any) -> list:
    """从多种 API 响应结构中抽出邮件列表。"""
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    # hydra / 标准 / 嵌套
    for k in ("hydra:member", "results", "data", "messages", "mails"):
        v = data.get(k)
        if isinstance(v, list):
            return v
        if isinstance(v, dict):
            for kk in ("messages", "mails", "results", "items"):
                if isinstance(v.get(kk), list):
                    return v[kk]
    return []
