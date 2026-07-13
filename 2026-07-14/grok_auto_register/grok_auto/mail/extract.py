# -*- coding: utf-8 -*-
"""从邮件主题/正文提取 xAI 验证码。"""

from __future__ import annotations

import re


def extract_verification_code(text: str, subject: str = "") -> str | None:
    """优先匹配 XXX-XXX 形式的 xAI 码。"""
    if subject:
        m = re.search(r"^([A-Z0-9]{3}-[A-Z0-9]{3})\s+xAI", subject, re.I)
        if m:
            return m.group(1)
        m = re.search(r"\b([A-Z0-9]{3}-[A-Z0-9]{3})\b", subject, re.I)
        if m:
            return m.group(1)
    m = re.search(r"\b([A-Z0-9]{3}-[A-Z0-9]{3})\b", text or "", re.I)
    if m:
        return m.group(1)
    for pat in (
        r"verification\s+code[:\s]+(\d{4,8})",
        r"your\s+code[:\s]+(\d{4,8})",
        r"confirm(?:ation)?\s+code[:\s]+(\d{4,8})",
    ):
        m = re.search(pat, text or "", re.I)
        if m:
            return m.group(1)
    return None
