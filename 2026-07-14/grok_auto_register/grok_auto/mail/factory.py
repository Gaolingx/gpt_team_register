# -*- coding: utf-8 -*-
"""按配置选择邮箱 Provider。"""

from __future__ import annotations

from grok_auto.config import get_config
from grok_auto.mail.cloudflare import CloudflareMailProvider


def get_mail_provider(cfg: dict | None = None):
    """返回邮箱 Provider。

    支持: cloudflare | duckmail | yyds | tempmail_lol
    """
    c = cfg or get_config()
    name = str(c.get("email_provider") or "cloudflare").strip().lower()
    if name in ("cloudflare", "cf", "temp_email"):
        return CloudflareMailProvider(c)
    if name in ("duckmail", "duck", "duck_mail"):
        from grok_auto.mail.duckmail import DuckMailProvider

        return DuckMailProvider(c)
    if name in ("yyds", "mali", "maliapi"):
        from grok_auto.mail.yyds import YydsMailProvider

        return YydsMailProvider(c)
    if name in (
        "tempmail_lol",
        "tempmail.lol",
        "tempmaillol",
        "tempmail-lol",
        "lol",
    ):
        from grok_auto.mail.tempmail_lol import TempMailLolProvider

        return TempMailLolProvider(c)
    raise RuntimeError(
        f"未知 email_provider={name}。"
        "支持: cloudflare | duckmail | yyds | tempmail_lol"
    )
