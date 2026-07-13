# -*- coding: utf-8 -*-
"""高层编排：为单个已注册免费账号铸造 CPA xai-*.json。

默认静默；成功结果由 pipeline 统一输出一行日志。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .browser_confirm import mint_with_browser
from .probe import probe_mini_response, probe_models
from .protocol_mint import ProtocolMintError, extract_sso_from_cookies, mint_with_sso_protocol
from .proxyutil import resolve_proxy, set_runtime_proxy
from .schema import DEFAULT_BASE_URL, build_cpa_xai_auth
from .writer import write_cpa_xai_auth

LogFn = Callable[[str], None]


def _noop(_: str) -> None:
    return None


def mint_and_export(
    *,
    email: str,
    password: str,
    auth_dir: str | Path,
    page: Any | None = None,
    proxy: str | None = None,
    headless: bool = False,
    base_url: str = DEFAULT_BASE_URL,
    probe: bool = True,
    probe_chat: bool = False,
    browser_timeout_sec: float = 240.0,
    force_standalone: bool = True,
    cookies: Any | None = None,
    sso: str | None = None,
    reuse_browser: bool = True,
    recycle_every: int = 15,
    prefer_protocol: bool = True,
    protocol_only: bool = False,
    protocol_poll_timeout_sec: float = 90.0,
    log: LogFn | None = None,
    cancel: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """完整流水线：协议 Device Flow（优先）| 浏览器授权 → 写 CPA → 探测。

    prefer_protocol 且存在 sso 时先走纯 HTTP；失败且非 protocol_only 则回退浏览器。

    返回: ok, path, email, probe, model_ids?, error?, mint_method?
    """
    # 铸造内部全程静默
    quiet = _noop
    _ = log  # 保留参数兼容，不输出
    email = (email or "").strip()
    if not email or not password:
        if not email:
            return {"ok": False, "email": email, "error": "缺少邮箱"}
        if not (sso or extract_sso_from_cookies(cookies)):
            return {"ok": False, "email": email, "error": "缺少邮箱或密码"}

    resolved = resolve_proxy(proxy)
    set_runtime_proxy(resolved or None)

    sso_val = (sso or "").strip() or extract_sso_from_cookies(cookies)
    tokens: dict[str, Any] | None = None
    protocol_err: str | None = None

    if prefer_protocol and sso_val:
        try:
            tokens = mint_with_sso_protocol(
                sso_cookie=sso_val,
                email=email,
                proxy=resolved or None,
                poll_timeout_sec=protocol_poll_timeout_sec,
                log=quiet,
                cancel=cancel,
            )
        except ProtocolMintError as e:
            protocol_err = str(e)
            if protocol_only:
                return {
                    "ok": False,
                    "email": email,
                    "error": f"仅协议模式: {e}",
                    "mint_method": "protocol",
                }
        except Exception as e:  # noqa: BLE001
            protocol_err = str(e)
            if protocol_only:
                return {
                    "ok": False,
                    "email": email,
                    "error": f"仅协议模式: {e}",
                    "mint_method": "protocol",
                }
    elif prefer_protocol and not sso_val:
        if protocol_only:
            return {
                "ok": False,
                "email": email,
                "error": "仅协议模式但无登录凭证",
                "mint_method": "protocol",
            }

    if tokens is None:
        if not password:
            return {
                "ok": False,
                "email": email,
                "error": protocol_err or "协议失败且无密码可供浏览器回退",
                "protocol_error": protocol_err,
            }
        try:
            tokens = mint_with_browser(
                email=email,
                password=password,
                page=None if force_standalone else page,
                proxy=resolved or None,
                headless=False,  # 强制有头，忽略入参
                browser_timeout_sec=browser_timeout_sec,
                force_standalone=force_standalone,
                cookies=cookies,
                reuse_browser=reuse_browser,
                recycle_every=recycle_every,
                poll_log=quiet,
                cancel=cancel,
            )
            tokens["mint_method"] = "browser"
            if protocol_err:
                tokens["protocol_error"] = protocol_err
        except Exception as e:  # noqa: BLE001
            err = str(e)
            if protocol_err:
                err = f"{err}（协议: {protocol_err}）"
            return {
                "ok": False,
                "email": email,
                "error": err,
                "protocol_error": protocol_err,
            }

    payload = build_cpa_xai_auth(
        email=email,
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        id_token=tokens.get("id_token"),
        expires_in=tokens.get("expires_in"),
        base_url=base_url,
    )
    path = write_cpa_xai_auth(auth_dir, payload)

    result: dict[str, Any] = {
        "ok": True,
        "email": email,
        "path": str(path),
        "user_code": tokens.get("user_code"),
        "base_url": base_url,
        "proxy": resolved or "",
        "mint_method": tokens.get("mint_method") or "browser",
        "model_ids": [],
    }
    if protocol_err and result["mint_method"] != "protocol":
        result["protocol_error"] = protocol_err

    # 成功日志需要模型名：始终探测 models（失败不影响文件已写出）
    pr = probe_models(tokens["access_token"], base_url=base_url, proxy=resolved or None)
    result["probe_models"] = pr
    model_ids = [str(x) for x in (pr.get("model_ids") or []) if x]
    result["model_ids"] = model_ids
    if probe:
        if not pr.get("has_grok_45"):
            result["ok"] = False
            result["error"] = "令牌有效但未列出 grok-4.5"
        if probe_chat and pr.get("has_grok_45"):
            ch = probe_mini_response(
                tokens["access_token"], base_url=base_url, proxy=resolved or None
            )
            result["probe_chat"] = ch
            if not ch.get("ok"):
                result["ok"] = False
                result["error"] = f"对话探测失败: {ch.get('error') or ch.get('status')}"
    return result
