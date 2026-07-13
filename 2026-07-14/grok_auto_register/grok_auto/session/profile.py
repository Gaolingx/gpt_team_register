# -*- coding: utf-8 -*-
"""注册资料生成。"""

from __future__ import annotations

import random
import secrets
import string


def _name(n: int = 6) -> str:
    return "".join(random.choices(string.ascii_lowercase, k=n)).capitalize()


def build_profile() -> tuple[str, str, str]:
    """返回 (名, 姓, 密码)。"""
    given = _name(random.randint(4, 7))
    family = _name(random.randint(5, 8))
    # 密码：满足常见复杂度
    pwd = (
        secrets.token_urlsafe(10)
        + random.choice("!@#$%")
        + str(random.randint(10, 99))
    )
    return given, family, pwd
