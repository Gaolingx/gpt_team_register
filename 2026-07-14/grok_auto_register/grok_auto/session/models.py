# -*- coding: utf-8 -*-
"""账号记录模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AccountRecord:
    """注册成功产物。"""

    email: str
    password: str
    sso: str
    given_name: str = ""
    family_name: str = ""
    cookies: list[dict[str, Any]] = field(default_factory=list)
    reg_method: str = "browser"

    def ledger_line(self) -> str:
        return f"{self.email}----{self.password}----{self.sso}"
