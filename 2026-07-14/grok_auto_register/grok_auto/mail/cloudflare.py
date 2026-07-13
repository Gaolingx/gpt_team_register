# -*- coding: utf-8 -*-
"""Cloudflare temp email（cloudflare_temp_email 风格 API）。"""

from __future__ import annotations

import re
import threading
import time
from typing import Any, Callable

from curl_cffi import requests as cf_requests

from grok_auto.browser.waits import raise_if_cancelled, sleep_with_cancel
from grok_auto.config import get_config, get_proxy
from grok_auto.mail.base import MailBox
from grok_auto.mail.extract import extract_verification_code


def _headers(cfg: dict, *, json_body: bool = False, jwt: str = "") -> dict[str, str]:
    h: dict[str, str] = {}
    if json_body:
        h["Content-Type"] = "application/json"
    key = str(cfg.get("cloudflare_api_key") or "").strip()
    mode = str(cfg.get("cloudflare_auth_mode") or "bearer").strip().lower()
    if jwt:
        h["Authorization"] = f"Bearer {jwt}"
    elif key:
        if mode in ("x-api-key",):
            h["X-API-Key"] = key
        elif mode in ("x-admin-auth", "admin", "x-admin-token"):
            # 仅小写头：同时带 X-Admin-Auth 会导致部分部署 401
            h["x-admin-auth"] = key
        elif mode not in ("none", "query-key"):
            h["Authorization"] = f"Bearer {key}"
    return h


def _session(proxy: str) -> Any:
    s = cf_requests.Session()
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
    return s


class CloudflareMailProvider:
    """Cloudflare 临时邮 Provider。"""

    name = "cloudflare"

    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or get_config()
        self.api_base = str(self.cfg.get("cloudflare_api_base") or "").rstrip("/")
        if not self.api_base:
            raise RuntimeError("cloudflare_api_base 未配置")
        self.proxy = get_proxy(self.cfg, for_cpa=False)

    def create(self) -> MailBox:
        """创建临时邮箱 → address + jwt。

        当前部署已关闭匿名 /api/new_address，需管理员接口：
          POST /admin/new_address  body={name, domain}  header=x-admin-auth
        仍保留公开接口作为次选（若管理员重开匿名建号）。
        """
        import secrets
        import string

        domains = [
            x.strip()
            for x in re.split(r"[,，\s]+", str(self.cfg.get("defaultDomains") or ""))
            if x.strip()
        ]
        if not domains:
            # 尝试从 open_api/settings 读默认域
            try:
                s0 = _session(self.proxy or "")
                sr = s0.get(
                    f"{self.api_base}/open_api/settings",
                    impersonate="chrome",
                    timeout=15,
                )
                if sr.status_code < 400:
                    js = sr.json()
                    for d in js.get("defaultDomains") or js.get("domains") or []:
                        if isinstance(d, str) and d.strip():
                            domains.append(d.strip())
            except Exception:
                pass
        if not domains:
            raise RuntimeError("未配置 defaultDomains，且无法从 open_api/settings 获取域名")

        # 域名轮换 + 线程熵，降低并发撞名
        domain = domains[(int(time.time() * 1000) + threading.get_ident()) % len(domains)]
        name = "u" + "".join(
            secrets.choice(string.ascii_lowercase + string.digits) for _ in range(12)
        )
        admin_payload = {"name": name, "domain": domain}
        public_payload: dict[str, Any] = {"domain": domain}

        admin_path = str(self.cfg.get("cloudflare_path_accounts") or "/admin/new_address")
        if not admin_path.startswith("/"):
            admin_path = "/" + admin_path
        url_admin = f"{self.api_base}{admin_path}"
        url_public = f"{self.api_base}/api/new_address"

        attempts: list[tuple[str, dict[str, Any], dict[str, str], str | None]] = [
            # (url, payload, headers, proxy)
            (url_admin, admin_payload, _headers(self.cfg, json_body=True), self.proxy or None),
            (url_admin, admin_payload, _headers(self.cfg, json_body=True), None),
            (url_public, public_payload, {"Content-Type": "application/json"}, self.proxy or None),
            (url_public, public_payload, {"Content-Type": "application/json"}, None),
            (url_public, {}, {"Content-Type": "application/json"}, self.proxy or None),
        ]
        last_err: Exception | None = None
        for url, payload, headers, proxy in attempts:
            try:
                s = _session(proxy or "")
                r = s.post(
                    url,
                    json=payload,
                    headers=headers,
                    impersonate="chrome",
                    timeout=30,
                )
                if r.status_code >= 400:
                    last_err = RuntimeError(
                        f"HTTP {r.status_code} {url} body={(r.text or '')[:200]}"
                    )
                    continue
                data = r.json()
                address = str(data.get("address") or "").strip()
                jwt = str(data.get("jwt") or "").strip()
                if not address or not jwt:
                    last_err = RuntimeError(f"缺少 address/jwt: {data}")
                    continue
                return MailBox(address=address, token=jwt, provider=self.name)
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                continue
        raise RuntimeError(f"Cloudflare 建号失败: {last_err}")

    def wait_code(
        self,
        box: MailBox,
        *,
        timeout: float = 150,
        poll_interval: float = 0.3,
        cancel: Callable[[], bool] | None = None,
        resend: Callable[[], None] | None = None,
        log: Callable[[str], None] | None = None,
    ) -> str:
        """轮询 /api/mails；列表有码立即返回，否则再拉 detail。"""
        s = _session(self.proxy)
        path = str(self.cfg.get("cloudflare_path_messages") or "/api/mails")
        if not path.startswith("/"):
            path = "/" + path
        deadline = time.time() + max(10.0, float(timeout))
        interval = max(0.15, float(poll_interval or 0.3))
        next_resend = time.time() + 35
        seen_attempts: dict[str, int] = {}
        log = log or (lambda _m: None)

        while time.time() < deadline:
            raise_if_cancelled(cancel)
            if resend and time.time() >= next_resend:
                try:
                    resend()
                except Exception:
                    pass
                next_resend = time.time() + 35
            try:
                r = s.get(
                    f"{self.api_base}{path}",
                    params={"limit": 20, "offset": 0},
                    headers=_headers(self.cfg, jwt=box.token),
                    impersonate="chrome",
                    timeout=20,
                )
                r.raise_for_status()
                data = r.json()
            except Exception:
                sleep_with_cancel(interval, cancel)
                continue

            messages = []
            if isinstance(data, dict):
                for k in ("results", "data", "messages", "mails"):
                    v = data.get(k)
                    if isinstance(v, list):
                        messages = v
                        break
                    if isinstance(v, dict) and isinstance(v.get("messages"), list):
                        messages = v["messages"]
                        break
            elif isinstance(data, list):
                messages = data

            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                msg_id = str(msg.get("id") or msg.get("msgid") or msg.get("emailId") or "")
                if msg_id:
                    n = int(seen_attempts.get(msg_id, 0))
                    if n >= 6:
                        continue
                    seen_attempts[msg_id] = n + 1

                # 地址匹配（宽松）
                recipients = []
                for t in msg.get("to") or []:
                    if isinstance(t, dict):
                        recipients.append(str(t.get("address") or "").lower())
                    else:
                        recipients.append(str(t).lower())
                msg_addr = str(msg.get("address") or "").lower()
                email_l = box.address.lower()
                if recipients and email_l not in recipients:
                    continue
                if msg_addr and msg_addr != email_l and not recipients:
                    continue

                parts: list[str] = []
                subject = str(msg.get("subject") or "")
                for field in ("text", "raw", "content", "intro", "body", "snippet"):
                    v = msg.get(field)
                    if isinstance(v, str) and v.strip():
                        parts.append(v)
                html = msg.get("html")
                if isinstance(html, str):
                    parts.append(re.sub(r"<[^>]+>", " ", html))
                elif isinstance(html, list):
                    for h in html:
                        if isinstance(h, str):
                            parts.append(re.sub(r"<[^>]+>", " ", h))
                combined = "\n".join(parts)
                code = extract_verification_code(combined, subject)
                if code:
                    pass
                    return code

                # 列表无码再拉 detail
                if not msg_id:
                    continue
                try:
                    dr = s.get(
                        f"{self.api_base}{path}/{msg_id}",
                        headers=_headers(self.cfg, jwt=box.token),
                        impersonate="chrome",
                        timeout=20,
                    )
                    if dr.status_code < 400:
                        detail = dr.json()
                        if isinstance(detail, dict):
                            if not subject:
                                subject = str(detail.get("subject") or "")
                            for field in ("text", "raw", "content", "intro", "body", "snippet"):
                                v = detail.get(field)
                                if isinstance(v, str) and v.strip():
                                    combined += "\n" + v
                            html2 = detail.get("html")
                            if isinstance(html2, str):
                                combined += "\n" + re.sub(r"<[^>]+>", " ", html2)
                            elif isinstance(html2, list):
                                for h in html2:
                                    if isinstance(h, str):
                                        combined += "\n" + re.sub(r"<[^>]+>", " ", h)
                            code = extract_verification_code(combined, subject)
                            if code:
                                pass
                                return code
                except Exception as exc:
                    pass

            sleep_with_cancel(interval, cancel)
        raise TimeoutError("等待验证码超时")
