# -*- coding: utf-8 -*-
"""YYDS 临时邮箱 Provider（对齐 van7517/grok-register-mint 接口）。

默认 API：https://maliapi.215.im/v1
鉴权：yyds_jwt (Bearer) 优先，否则 yyds_api_key (X-API-Key)。
"""

from __future__ import annotations

import random
import re
import secrets
import string
import time
from typing import Any, Callable

from grok_auto.browser.waits import raise_if_cancelled, sleep_with_cancel
from grok_auto.config import get_config, get_proxy
from grok_auto.mail.base import MailBox
from grok_auto.mail.extract import extract_verification_code
from grok_auto.mail.httputil import make_session, split_list

DEFAULT_API_BASE = "https://maliapi.215.im/v1"


class YydsMailProvider:
    """YYDS Provider。"""

    name = "yyds"

    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or get_config()
        self.api_base = str(self.cfg.get("yyds_api_base") or DEFAULT_API_BASE).rstrip("/")
        self.api_key = str(self.cfg.get("yyds_api_key") or "").strip()
        self.jwt = str(self.cfg.get("yyds_jwt") or "").strip()
        self.proxy = get_proxy(self.cfg, for_cpa=False)
        if not self.api_key and not self.jwt:
            raise RuntimeError("YYDS 未配置 yyds_api_key 或 yyds_jwt")

    def _session(self):
        return make_session(self.proxy or None, self.cfg)

    def _headers(self, *, json_body: bool = False) -> dict[str, str]:
        h: dict[str, str] = {}
        if json_body:
            h["Content-Type"] = "application/json"
        if self.jwt:
            h["Authorization"] = f"Bearer {self.jwt}"
        elif self.api_key:
            h["X-API-Key"] = self.api_key
        return h

    def _get_domains(self) -> list[dict[str, Any]]:
        s = self._session()
        r = s.get(
            f"{self.api_base}/domains",
            headers=self._headers(),
            impersonate="chrome",
            timeout=30,
        )
        if r.status_code >= 400:
            raise RuntimeError(
                f"YYDS 获取域名失败 HTTP {r.status_code}: {(r.text or '')[:200]}"
            )
        data = r.json()
        if isinstance(data, dict) and data.get("success"):
            items = data.get("data") or []
            return [x for x in items if isinstance(x, dict)]
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        return []

    def _pick_domain(self) -> str:
        domains = self._get_domains()
        if not domains:
            raise RuntimeError("YYDS 未返回可用域名")
        blocked = {x.lower() for x in split_list(self.cfg.get("yyds_blocked_domains", ""))}
        verified = [
            d
            for d in domains
            if d.get("isVerified")
            and str(d.get("domain") or "").strip().lower() not in blocked
        ]
        preferred = [x.lower() for x in split_list(self.cfg.get("yyds_preferred_domains", ""))]
        if preferred:
            domain_map = {
                str(d.get("domain") or "").strip().lower(): d for d in verified
            }
            for name in preferred:
                if name in domain_map:
                    return str(domain_map[name].get("domain") or "").strip()
        private = [d for d in verified if not d.get("isPublic")]
        if private:
            random.shuffle(private)
            return str(private[0].get("domain") or "").strip()
        public = [d for d in verified if d.get("isPublic")]
        if public:
            if str(self.cfg.get("yyds_domain_selection") or "random").lower() == "random":
                random.shuffle(public)
            return str(public[0].get("domain") or "").strip()
        if verified:
            return str(verified[0].get("domain") or "").strip()
        raise RuntimeError(
            f"YYDS 无已验证域名可用，已排除: {', '.join(sorted(blocked)) or 'none'}"
        )

    def create(self) -> MailBox:
        """创建 YYDS 邮箱并返回读信 token。"""
        domain = self._pick_domain()
        if not domain:
            raise RuntimeError("YYDS 域名无效")
        username = "".join(
            secrets.choice(string.ascii_lowercase + string.digits) for _ in range(10)
        )
        s = self._session()
        payload: dict[str, Any] = {"address": username, "domain": domain}
        r = s.post(
            f"{self.api_base}/accounts",
            json=payload,
            headers=self._headers(json_body=True),
            impersonate="chrome",
            timeout=30,
        )
        if r.status_code >= 400:
            raise RuntimeError(
                f"YYDS 建号失败 HTTP {r.status_code}: {(r.text or '')[:200]}"
            )
        data = r.json() if r.text else {}
        result: dict[str, Any] = {}
        if isinstance(data, dict):
            if data.get("success") is False:
                raise RuntimeError(f"YYDS 建号失败: {data}")
            result = data.get("data") if isinstance(data.get("data"), dict) else data
        address = str(result.get("address") or f"{username}@{domain}").strip()
        token = str(result.get("token") or "").strip()
        if not token:
            # 再请求 /token
            r2 = s.post(
                f"{self.api_base}/token",
                json={"address": address},
                headers=self._headers(json_body=True),
                impersonate="chrome",
                timeout=30,
            )
            if r2.status_code >= 400:
                raise RuntimeError(
                    f"YYDS 取 token 失败 HTTP {r2.status_code}: {(r2.text or '')[:200]}"
                )
            d2 = r2.json() if r2.text else {}
            if isinstance(d2, dict):
                if d2.get("success") and isinstance(d2.get("data"), dict):
                    token = str(d2["data"].get("token") or "").strip()
                else:
                    token = str(d2.get("token") or "").strip()
        if not address or not token:
            raise RuntimeError("YYDS 未返回 address/token")
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
        """轮询 YYDS /messages 抽验证码。"""
        _ = log
        s = self._session()
        deadline = time.time() + max(10.0, float(timeout))
        interval = max(0.2, float(poll_interval or 0.3))
        next_resend = time.time() + 35
        seen: set[str] = set()
        # 读信用邮箱 token（Bearer）
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
                    params={"address": box.address},
                    headers=headers,
                    impersonate="chrome",
                    timeout=20,
                )
                if r.status_code >= 400:
                    sleep_with_cancel(interval, cancel)
                    continue
                data = r.json()
                messages: list = []
                if isinstance(data, dict):
                    if data.get("success") and isinstance(data.get("data"), dict):
                        messages = data["data"].get("messages") or []
                    else:
                        messages = data.get("messages") or data.get("data") or []
                if not isinstance(messages, list):
                    messages = []
            except Exception:
                sleep_with_cancel(interval, cancel)
                continue

            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                msg_id = str(msg.get("id") or "")
                if msg_id and msg_id in seen:
                    continue
                if msg_id:
                    seen.add(msg_id)

                to_addrs = []
                for t in msg.get("to") or []:
                    if isinstance(t, dict):
                        to_addrs.append(str(t.get("address") or "").lower())
                    else:
                        to_addrs.append(str(t).lower())
                if to_addrs and box.address.lower() not in to_addrs:
                    continue

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
                                if js.get("success") and isinstance(js.get("data"), dict):
                                    detail = js["data"]
                                else:
                                    detail = js
                    except Exception:
                        pass

                parts: list[str] = []
                subject = str(detail.get("subject") or msg.get("subject") or "")
                text_body = detail.get("text") or ""
                if isinstance(text_body, str) and text_body:
                    parts.append(text_body)
                for field in ("raw", "content", "intro", "body", "snippet"):
                    v = detail.get(field)
                    if isinstance(v, str) and v.strip():
                        parts.append(v)
                html_list = detail.get("html") or []
                if isinstance(html_list, str):
                    parts.append(re.sub(r"<[^>]+>", " ", html_list))
                elif isinstance(html_list, list):
                    for h in html_list:
                        if isinstance(h, str):
                            parts.append(re.sub(r"<[^>]+>", " ", h))
                code = extract_verification_code("\n".join(parts), subject)
                if code:
                    return code

            sleep_with_cancel(interval, cancel)
        raise TimeoutError("YYDS 等待验证码超时")
