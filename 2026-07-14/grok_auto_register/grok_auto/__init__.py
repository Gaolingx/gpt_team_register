# -*- coding: utf-8 -*-
"""grok_auto_register：Grok 免费账号注册 + CPA OIDC 铸造。

架构：
  mail      邮箱供给（Cloudflare 等）
  browser   Chromium / TabPool / 条件等待
  session   注册拿 SSO（浏览器 FSM，协议预留）
  credential SSO → OIDC → cpa_auths/xai-*.json
  orchestrator 队列 / 指标 / CLI
"""

__version__ = "2.0.0"
