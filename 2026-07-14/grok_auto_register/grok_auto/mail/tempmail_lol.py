# -*- coding: utf-8 -*-
"""TempMail.lol 临时邮箱 Provider。

官方文档: https://tempmail.lol/en/api
基址: https://api.tempmail.lol/v2

- POST /inbox/create  → {address, token}
- GET  /inbox?token=  → {emails: [...], expired: bool}

免费无需 API Key；Plus/Ultra 可选 Bearer。
免费收件箱约 1 小时过期。
"""

from __future__ import annotations

import re
import secrets
import string
import time
from typing import Any, Callable
from urllib.parse import quote

from grok_auto.browser.waits import raise_if_cancelled, sleep_with_cancel
from grok_auto.config import get_config, get_proxy
from grok_auto.mail.base import MailBox
from grok_auto.mail.extract import extract_verification_code
from grok_auto.mail.httputil import make_session

DEFAULT_API_BASE = "https://api.tempmail.lol/v2"


class TempMailLolProvider:
    """TempMail.lol Provider。"""

    name = "tempmail_lol"

    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or get_config()
        self.api_base = str(
            self.cfg.get("tempmail_lol_api_base") or DEFAULT_API_BASE
        ).rstrip("/")
        self.api_key = str(self.cfg.get("tempmail_lol_api_key") or "").strip()
        self.proxy = get_proxy(self.cfg, for_cpa=False)

    def _session(self):
        return make_session(self.proxy or None, self.cfg)

    def _headers(self, *, json_body: bool = False) -> dict[str, str]:
        h: dict[str, str] = {
            "User-Agent": "grok_auto_register/tempmail_lol",
            "Accept": "application/json",
        }
        if json_body:
            h["Content-Type"] = "application/json"
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def create(self) -> MailBox:
        """创建收件箱：POST /inbox/create → address + token。"""
        body: dict[str, Any] = {}
        domain = str(self.cfg.get("tempmail_lol_domain") or "").strip()
        prefix = str(self.cfg.get("tempmail_lol_prefix") or "").strip()
        # 未指定 prefix 时生成随机前缀，降低碰撞
        if not prefix and bool(self.cfg.get("tempmail_lol_random_prefix", True)):
            prefix = "u" + "".join(
                secrets.choice(string.ascii_lowercase + string.digits) for _ in range(10)
            )
        if domain:
            body["domain"] = domain
        if prefix:
            body["prefix"] = prefix
        # community: 文档/SDK 支持；默认不强制
        community = self.cfg.get("tempmail_lol_community", None)
        if community is not None:
            body["community"] = bool(community)

        s = self._session()
        r = s.post(
            f"{self.api_base}/inbox/create",
            json=body if body else {},
            headers=self._headers(json_body=True),
            impersonate="chrome",
            timeout=30,
        )
        if r.status_code == 402:
            raise RuntimeError("TempMail.lol 账户额度/时长不足 (HTTP 402)")
        if r.status_code == 403 and self.api_key:
            raise RuntimeError("TempMail.lol API Key 无效 (HTTP 403)")
        if r.status_code >= 400:
            raise RuntimeError(
                f"TempMail.lol 建箱失败 HTTP {r.status_code}: {(r.text or '')[:200]}"
            )
        data = r.json() if r.text else {}
        if not isinstance(data, dict):
            raise RuntimeError(f"TempMail.lol 建箱响应异常: {data!r}")
        address = str(data.get("address") or "").strip()
        token = str(data.get("token") or "").strip()
        if not address or not token:
            raise RuntimeError(f"TempMail.lol 未返回 address/token: {data}")
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
        """轮询 GET /inbox?token= 直到抽出验证码。"""
        _ = log
        s = self._session()
        deadline = time.time() + max(10.0, float(timeout))
        interval = max(0.2, float(poll_interval or 0.3))
        next_resend = time.time() + 35
        seen_keys: set[str] = set()
        token_q = quote(box.token, safe="")

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
                    f"{self.api_base}/inbox?token={token_q}",
                    headers=self._headers(),
                    impersonate="chrome",
                    timeout=20,
                )
                if r.status_code >= 400:
                    sleep_with_cancel(interval, cancel)
                    continue
                data = r.json() if r.text else {}
            except Exception:
                sleep_with_cancel(interval, cancel)
                continue

            if not isinstance(data, dict):
                sleep_with_cancel(interval, cancel)
                continue
            if data.get("expired") is True:
                raise TimeoutError("TempMail.lol 收件箱已过期，请缩短等待或换邮重试")

            emails = data.get("emails") or []
            if not isinstance(emails, list):
                emails = []

            for msg in emails:
                if not isinstance(msg, dict):
                    continue
                # 去重键：日期+主题+发件人
                key = "|".join(
                    [
                        str(msg.get("date") or ""),
                        str(msg.get("subject") or ""),
                        str(msg.get("from") or msg.get("sender") or ""),
                    ]
                )
                if key in seen_keys:
                    continue
                seen_keys.add(key)

                subject = str(msg.get("subject") or "")
                parts: list[str] = []
                body = msg.get("body") or msg.get("text") or ""
                if isinstance(body, str) and body.strip():
                    parts.append(body)
                html = msg.get("html")
                if isinstance(html, str) and html.strip():
                    parts.append(re.sub(r"<[^>]+>", " ", html))
                # 兼容其它字段名
                for field in ("raw", "content", "intro", "snippet"):
                    v = msg.get(field)
                    if isinstance(v, str) and v.strip():
                        parts.append(v)
                code = extract_verification_code("\n".join(parts), subject)
                if code:
                    return code

            sleep_with_cancel(interval, cancel)
        raise TimeoutError("TempMail.lol 等待验证码超时")
