# -*- coding: utf-8 -*-
"""DuckMail 临时邮箱 Provider（对齐 van7517/grok-register-mint 接口）。

默认 API：https://api.duckmail.sbs
流程：拉域名 → 建账号 → 取 token → 轮询 messages 抽验证码。
"""

from __future__ import annotations

import re
import secrets
import string
import time
from typing import Any, Callable

from grok_auto.browser.waits import raise_if_cancelled, sleep_with_cancel
from grok_auto.config import get_config, get_proxy
from grok_auto.mail.base import MailBox
from grok_auto.mail.extract import extract_verification_code
from grok_auto.mail.httputil import make_session, pick_messages_payload

DEFAULT_API_BASE = "https://api.duckmail.sbs"


def _auth_headers(api_key: str, *, json_body: bool = False) -> dict[str, str]:
    h: dict[str, str] = {}
    if json_body:
        h["Content-Type"] = "application/json"
    key = (api_key or "").strip()
    if key:
        h["Authorization"] = f"Bearer {key}"
    return h


class DuckMailProvider:
    """DuckMail Provider。"""

    name = "duckmail"

    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or get_config()
        self.api_base = str(
            self.cfg.get("duckmail_api_base") or DEFAULT_API_BASE
        ).rstrip("/")
        self.api_key = str(self.cfg.get("duckmail_api_key") or "").strip()
        self.proxy = get_proxy(self.cfg, for_cpa=False)

    def _session(self):
        return make_session(self.proxy or None, self.cfg)

    def _get_domains(self) -> list[dict[str, Any]]:
        s = self._session()
        r = s.get(
            f"{self.api_base}/domains",
            headers=_auth_headers(self.api_key),
            impersonate="chrome",
            timeout=30,
        )
        if r.status_code >= 400:
            raise RuntimeError(
                f"DuckMail 获取域名失败 HTTP {r.status_code}: {(r.text or '')[:200]}"
            )
        data = r.json()
        members = data.get("hydra:member") if isinstance(data, dict) else None
        if isinstance(members, list):
            return [x for x in members if isinstance(x, dict)]
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        return []

    def _pick_domain(self) -> str:
        domains = self._get_domains()
        if not domains:
            raise RuntimeError("DuckMail 未返回可用域名")
        private = [d for d in domains if d.get("ownerId")]
        verified_private = [d for d in private if d.get("isVerified")]
        if verified_private:
            return str(verified_private[0].get("domain") or "").strip()
        public = [d for d in domains if d.get("isVerified")]
        if public:
            return str(public[0].get("domain") or "").strip()
        # 兜底：任意带 domain 字段
        for d in domains:
            dom = str(d.get("domain") or "").strip()
            if dom:
                return dom
        raise RuntimeError("DuckMail 无已验证域名可用")

    def create(self) -> MailBox:
        """创建 DuckMail 邮箱并返回读信 token。"""
        domain = self._pick_domain()
        if not domain:
            raise RuntimeError("DuckMail 域名无效")
        username = "".join(
            secrets.choice(string.ascii_lowercase + string.digits) for _ in range(10)
        )
        address = f"{username}@{domain}"
        password = secrets.token_urlsafe(12)

        s = self._session()
        # 1) 建号
        r = s.post(
            f"{self.api_base}/accounts",
            json={"address": address, "password": password, "expiresIn": 0},
            headers=_auth_headers(self.api_key, json_body=True),
            impersonate="chrome",
            timeout=30,
        )
        if r.status_code >= 400:
            raise RuntimeError(
                f"DuckMail 建号失败 HTTP {r.status_code}: {(r.text or '')[:200]}"
            )
        # 2) 取 token
        r2 = s.post(
            f"{self.api_base}/token",
            json={"address": address, "password": password},
            headers={"Content-Type": "application/json"},
            impersonate="chrome",
            timeout=30,
        )
        if r2.status_code >= 400:
            raise RuntimeError(
                f"DuckMail 取 token 失败 HTTP {r2.status_code}: {(r2.text or '')[:200]}"
            )
        data = r2.json() if r2.text else {}
        token = ""
        if isinstance(data, dict):
            token = str(data.get("token") or "").strip()
            if not token and isinstance(data.get("data"), dict):
                token = str(data["data"].get("token") or "").strip()
        if not token:
            raise RuntimeError("DuckMail 未返回 token")
        return MailBox(address=address, token=token, provider=self.name)

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
        """轮询 /messages 直到抽出验证码。"""
        _ = log
        s = self._session()
        deadline = time.time() + max(10.0, float(timeout))
        interval = max(0.2, float(poll_interval or 0.3))
        next_resend = time.time() + 35
        seen: set[str] = set()
        headers = {"Authorization": f"Bearer {box.token}"}

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
                    f"{self.api_base}/messages",
                    headers=headers,
                    impersonate="chrome",
                    timeout=20,
                )
                if r.status_code >= 400:
                    sleep_with_cancel(interval, cancel)
                    continue
                messages = pick_messages_payload(r.json())
            except Exception:
                sleep_with_cancel(interval, cancel)
                continue

            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                msg_id = str(msg.get("id") or msg.get("msgid") or "")
                if msg_id and msg_id in seen:
                    continue
                if msg_id:
                    seen.add(msg_id)

                recipients = []
                for t in msg.get("to") or []:
                    if isinstance(t, dict):
                        recipients.append(str(t.get("address") or "").lower())
                    else:
                        recipients.append(str(t).lower())
                if recipients and box.address.lower() not in recipients:
                    continue

                # 列表可能无正文，拉详情
                detail = msg
                if msg_id:
                    try:
                        dr = s.get(
                            f"{self.api_base}/messages/{msg_id}",
                            headers=headers,
                            impersonate="chrome",
                            timeout=20,
                        )
                        if dr.status_code < 400:
                            js = dr.json()
                            if isinstance(js, dict):
                                detail = js
                    except Exception:
                        pass

                parts: list[str] = []
                subject = str(detail.get("subject") or msg.get("subject") or "")
                for field in ("text", "raw", "content", "intro", "body", "snippet"):
                    v = detail.get(field)
                    if isinstance(v, str) and v.strip():
                        parts.append(v)
                html = detail.get("html")
                if isinstance(html, str):
                    parts.append(re.sub(r"<[^>]+>", " ", html))
                elif isinstance(html, list):
                    for h in html:
                        if isinstance(h, str):
                            parts.append(re.sub(r"<[^>]+>", " ", h))
                code = extract_verification_code("\n".join(parts), subject)
                if code:
                    return code

            sleep_with_cancel(interval, cancel)
        raise TimeoutError("DuckMail 等待验证码超时")
