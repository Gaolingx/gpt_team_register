# -*- coding: utf-8 -*-
"""mail：邮箱供给抽象。

支持：cloudflare / duckmail / yyds / tempmail_lol（由 email_provider 选择）。
"""

from .base import MailBox, MailProvider
from .factory import get_mail_provider

__all__ = ["MailBox", "MailProvider", "get_mail_provider"]
