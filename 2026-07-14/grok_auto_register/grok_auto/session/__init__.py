# -*- coding: utf-8 -*-
"""session：注册拿 SSO。"""

from .browser_register import RegisterResult, register_with_browser
from .models import AccountRecord

__all__ = ["AccountRecord", "RegisterResult", "register_with_browser"]
