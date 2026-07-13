# -*- coding: utf-8 -*-
"""邮箱 Provider 接口。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol


@dataclass
class MailBox:
    """一次注册使用的邮箱句柄。"""

    address: str
    token: str  # Cloudflare jwt / 其它 provider 句柄
    provider: str = ""


class MailProvider(Protocol):
    """邮箱供给：建号 + 收验证码。"""

    name: str

    def create(self) -> MailBox:
        """创建临时邮箱。"""
        ...

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
        """阻塞直到拿到验证码。"""
        ...
