# -*- coding: utf-8 -*-
"""浏览器注册 FSM：开页 → 邮箱 → 验证码 → 资料 → SSO。

设计：
- 步骤完整，不砍业务
- 条件等待，少盲等
- 邮箱走 MailProvider 抽象
"""

from __future__ import annotations

import secrets
import string
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from grok_auto.browser.tab_pool import TabPool
from grok_auto.browser.turnstile import (
    ensure_turnstile_ok,
    turnstile_present,
    turnstile_token_len,
)
from grok_auto.browser.waits import Cancelled, poll_wait, raise_if_cancelled, wait_until
from grok_auto.config import get_config
from grok_auto.mail.base import MailBox, MailProvider
from grok_auto.mail.factory import get_mail_provider
from grok_auto.session.models import AccountRecord
from grok_auto.session.profile import build_profile

LogFn = Callable[[str], None]
CancelFn = Callable[[], bool]

SIGNUP_URL = "https://accounts.x.ai/sign-up?redirect=grok-com"


@dataclass
class RegisterResult:
    ok: bool
    account: AccountRecord | None = None
    error: str = ""
    stage: str = ""
    stages_ms: dict[str, float] = field(default_factory=dict)


def _noop_log(_: str) -> None:
    return None


def _page():
    return TabPool.get_tab()


def _export_cookies(page) -> list[dict]:
    try:
        cks = page.cookies(all_domains=True, all_info=True)
        if isinstance(cks, list):
            return [c for c in cks if isinstance(c, dict)]
    except Exception:
        pass
    return []


def _js_email_ready(page) -> bool:
    try:
        return bool(
            page.run_js(
                r"""
function isVisible(node) {
  if (!node) return false;
  const style = window.getComputedStyle(node);
  if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
  const rect = node.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0;
}
const input = Array.from(document.querySelectorAll(
  'input[data-testid="email"], input[name="email"], input[type="email"], input[autocomplete="email"]'
)).find((n) => isVisible(n) && !n.disabled);
return !!input;
"""
            )
        )
    except Exception:
        return False


def _click_email_signup(page, cancel: CancelFn | None, log: LogFn) -> None:
    deadline = time.time() + 12
    while time.time() < deadline:
        raise_if_cancelled(cancel)
        clicked = page.run_js(
            r"""
const candidates = Array.from(document.querySelectorAll('button, a, [role="button"]'));
const target = candidates.find((node) => {
  const text = (node.innerText || node.textContent || '').replace(/\s+/g, '');
  const lower = text.toLowerCase();
  return text.includes('使用邮箱注册') || lower.includes('signupwithemail')
    || lower.includes('continuewithemail')
    || (lower.includes('email') && (lower.includes('sign') || lower.includes('continue')));
});
if (!target) return false;
target.click();
return true;
"""
        )
        if clicked:
            wait_until(lambda: _js_email_ready(page), timeout=4, interval=0.15, cancel=cancel)
            return
        poll_wait(0.35, cancel)
    raise RuntimeError("未找到「使用邮箱注册」按钮")


def _fill_email(page, email: str, cancel: CancelFn | None) -> None:
    deadline = time.time() + 20
    while time.time() < deadline:
        raise_if_cancelled(cancel)
        filled = page.run_js(
            """
const email = arguments[0];
function isVisible(node) {
  if (!node) return false;
  const style = window.getComputedStyle(node);
  if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
  const rect = node.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0;
}
const input = Array.from(document.querySelectorAll(
  'input[data-testid="email"], input[name="email"], input[type="email"], input[autocomplete="email"]'
)).find((n) => isVisible(n) && !n.disabled && !n.readOnly);
if (!input) return 'not-ready';
input.focus(); input.click();
const valueSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
const tracker = input._valueTracker;
if (tracker) tracker.setValue('');
if (valueSetter) valueSetter.call(input, email); else input.value = email;
input.dispatchEvent(new Event('focus', { bubbles: true }));
input.dispatchEvent(new InputEvent('input', { bubbles: true, data: email, inputType: 'insertText' }));
input.dispatchEvent(new Event('change', { bubbles: true }));
input.dispatchEvent(new Event('blur', { bubbles: true }));
if ((input.value || '').trim() === email) return 'filled';
return 'fail';
""",
            email,
        )
        if filled == "not-ready":
            poll_wait(0.2, cancel)
            continue
        if filled != "filled":
            poll_wait(0.2, cancel)
            continue
        poll_wait(0.12, cancel)
        clicked = page.run_js(
            r"""
function isVisible(node) {
  if (!node) return false;
  const style = window.getComputedStyle(node);
  if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
  const rect = node.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0;
}
const buttons = Array.from(document.querySelectorAll('button[type="submit"], button'))
  .filter((n) => isVisible(n) && !n.disabled);
const btn = buttons.find((node) => {
  const t = (node.innerText || node.textContent || '').replace(/\s+/g, '').toLowerCase();
  return t.includes('注册') || t.includes('继续') || t.includes('下一步')
    || t.includes('sign') || t.includes('continue') || t.includes('next');
});
if (!btn) return false;
btn.click();
return true;
"""
        )
        if clicked:
            return
        poll_wait(0.2, cancel)
    raise RuntimeError("填写邮箱或点击注册失败")


def _fill_code(page, code: str, cancel: CancelFn | None) -> None:
    clean = str(code).replace("-", "").strip()
    # 页面展示可能带连字符，两种都试
    variants = [str(code).strip(), clean]
    deadline = time.time() + 60
    while time.time() < deadline:
        raise_if_cancelled(cancel)
        for variant in variants:
            filled = page.run_js(
                """
const code = String(arguments[0] || '').trim();
function isVisible(node) {
  if (!node) return false;
  const style = window.getComputedStyle(node);
  if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
  const rect = node.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0;
}
function setInputValue(input, value) {
  const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
  const tracker = input._valueTracker;
  if (tracker) tracker.setValue('');
  if (nativeSetter) nativeSetter.call(input, value); else input.value = value;
  input.dispatchEvent(new InputEvent('input', { bubbles: true, data: value, inputType: 'insertText' }));
  input.dispatchEvent(new Event('change', { bubbles: true }));
}
const aggregate = Array.from(document.querySelectorAll(
  'input[data-input-otp="true"], input[name="code"], input[autocomplete="one-time-code"], input[inputmode="numeric"]'
)).find((n) => isVisible(n) && !n.disabled && Number(n.maxLength || 6) > 1);
if (aggregate) {
  aggregate.focus(); setInputValue(aggregate, code);
  return (aggregate.value || '').trim() ? 'filled-aggregate' : 'fail';
}
const boxes = Array.from(document.querySelectorAll('input')).filter((n) => {
  if (!isVisible(n) || n.disabled) return false;
  return Number(n.maxLength || 0) === 1;
});
if (boxes.length >= code.length) {
  for (let i = 0; i < code.length; i++) {
    boxes[i].focus(); setInputValue(boxes[i], code[i] || '');
  }
  return 'filled-boxes';
}
return 'not-ready';
""",
                variant,
            )
            if filled and str(filled).startswith("filled"):
                page.run_js(
                    r"""
function isVisible(node) {
  if (!node) return false;
  const style = window.getComputedStyle(node);
  if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
  const rect = node.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0;
}
const buttons = Array.from(document.querySelectorAll('button[type="submit"], button'))
  .filter((n) => isVisible(n) && !n.disabled);
const btn = buttons.find((node) => {
  const t = (node.innerText || node.textContent || '').replace(/\s+/g, '').toLowerCase();
  return t.includes('确认') || t.includes('继续') || t.includes('下一步')
    || t.includes('confirm') || t.includes('continue') || t.includes('next');
});
if (btn) { btn.click(); return true; }
return false;
"""
                )
                wait_until(
                    lambda: bool(
                        page.run_js(
                            r"""
const given = document.querySelector(
  'input[data-testid="givenName"], input[name="givenName"], input[autocomplete="given-name"]'
);
const codeBox = document.querySelector(
  'input[data-input-otp="true"], input[autocomplete="one-time-code"], input[name="code"]'
);
function vis(n){ if(!n) return false; const s=getComputedStyle(n); const r=n.getBoundingClientRect();
  return s.display!=='none'&&s.visibility!=='hidden'&&r.width>0; }
return !!(vis(given) || !vis(codeBox));
"""
                        )
                    ),
                    timeout=3.0,
                    interval=0.15,
                    cancel=cancel,
                )
                return
        poll_wait(0.2, cancel)
    raise RuntimeError("验证码填写/提交失败")


def _fill_profile(page, given: str, family: str, password: str, cancel: CancelFn | None, log: LogFn, cfg: dict) -> None:
    wait_until(
        lambda: bool(
            page.run_js(
                r"""
return !!(document.querySelector(
  'input[data-testid="givenName"], input[name="givenName"], input[autocomplete="given-name"]'
) || document.querySelector('iframe[src*="turnstile"], input[name="cf-turnstile-response"]'));
"""
            )
        ),
        timeout=1.2,
        interval=0.15,
        cancel=cancel,
    )
    try:
        cf_hard = float(cfg.get("turnstile_stuck_timeout", 90) or 90)
    except Exception:
        cf_hard = 90.0
    cf_hard = max(30.0, min(cf_hard, 150.0))
    deadline = time.time() + float(cfg.get("profile_timeout", 240) or 240)
    form_done = False
    last_cf_try = 0.0

    while time.time() < deadline:
        raise_if_cancelled(cancel)
        if not form_done:
            filled = page.run_js(
                """
const givenName = arguments[0], familyName = arguments[1], password = arguments[2];
function isVisible(node) {
  if (!node) return false;
  const style = window.getComputedStyle(node);
  if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
  const rect = node.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0;
}
function pick(sel) {
  return Array.from(document.querySelectorAll(sel)).find((n) => isVisible(n) && !n.disabled) || null;
}
function setVal(input, value) {
  if (!input) return false;
  input.focus();
  const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
  const tracker = input._valueTracker;
  if (tracker) tracker.setValue('');
  if (nativeSetter) nativeSetter.call(input, value); else input.value = value;
  input.dispatchEvent(new InputEvent('input', { bubbles: true, data: value, inputType: 'insertText' }));
  input.dispatchEvent(new Event('change', { bubbles: true }));
  return String(input.value||'').trim() === String(value||'').trim();
}
const g = pick('input[data-testid="givenName"], input[name="givenName"], input[autocomplete="given-name"]');
const f = pick('input[data-testid="familyName"], input[name="familyName"], input[autocomplete="family-name"]');
const p = pick('input[data-testid="password"], input[name="password"], input[type="password"]');
if (!g || !f || !p) return 'not-ready';
if (!setVal(g, givenName) || !setVal(f, familyName) || !setVal(p, password)) return 'fill-failed';
return 'filled';
""",
                given,
                family,
                password,
            )
            if filled == "not-ready":
                poll_wait(0.2, cancel)
                continue
            if filled == "fill-failed":
                poll_wait(0.2, cancel)
                continue
            if filled == "filled":
                form_done = True

        # 资料填好后：集中做一次（或少数几次）真人验证，禁止狂点
        if turnstile_token_len(page) < 80:
            now = time.time()
            if last_cf_try <= 0 or (now - last_cf_try >= 8.0 and turnstile_present(page)):
                remaining = max(15.0, min(cf_hard, deadline - now))
                try:
                    ensure_turnstile_ok(
                        page,
                        timeout=remaining,
                        cancel=cancel,
                        log=_noop_log,
                        min_len=80,
                    )
                except Exception:
                    pass
                last_cf_try = time.time()
            if turnstile_token_len(page) < 80:
                # 仍无 token：继续等扩展/页面自己出结果，不再每圈 reset
                if time.time() - last_cf_try > cf_hard:
                    raise RuntimeError("人机验证等待超时")
                poll_wait(0.6, cancel)
                continue

        state = page.run_js(
            r"""
function isVisible(node) {
  if (!node) return false;
  const style = window.getComputedStyle(node);
  if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
  const rect = node.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0;
}
const cfInput = document.querySelector('input[name="cf-turnstile-response"], textarea[name="cf-turnstile-response"]');
const cfPresent = !!cfInput || !!document.querySelector('iframe[src*="turnstile"], div.cf-turnstile, iframe[src*="challenges.cloudflare.com"]');
if (cfPresent) {
  const token = String((cfInput && cfInput.value) || '').trim();
  if (token.length < 80) return 'wait-cloudflare:' + token.length;
}
const buttons = Array.from(document.querySelectorAll('button[type="submit"], button'))
  .filter((n) => isVisible(n) && !n.disabled);
const btn = buttons.find((node) => {
  const t = (node.innerText || node.textContent || '').replace(/\s+/g, '').toLowerCase();
  return t.includes('完成注册') || t.includes('创建账户') || t.includes('sign up') || t.includes('createaccount') || t.includes('注册');
});
if (!btn) return 'no-submit';
btn.focus();
// 真实点击优先，by_js 在部分站点无效
try { btn.click(); } catch (e) { btn.dispatchEvent(new MouseEvent('click', {bubbles:true})); }
return 'submitted';
"""
        )
        if isinstance(state, str) and state.startswith("wait-cloudflare"):
            poll_wait(0.5, cancel)
            continue
        if state == "submitted":
            return
        if state == "no-submit":
            poll_wait(0.3, cancel)
            continue
        poll_wait(0.2, cancel)
    raise RuntimeError("注册资料填写失败")


def _wait_sso(page, cancel: CancelFn | None, log: LogFn, timeout: float = 180) -> str:
    deadline = time.time() + timeout
    last_submit = 0.0
    last_cf = 0.0
    while time.time() < deadline:
        raise_if_cancelled(cancel)
        now = time.time()
        # 最终页若仍有 CF，主动解（静默）
        if turnstile_present(page) and turnstile_token_len(page) < 80 and now - last_cf >= 3.0:
            try:
                ensure_turnstile_ok(
                    page,
                    timeout=min(25.0, max(5.0, deadline - now)),
                    cancel=cancel,
                    log=_noop_log,
                )
            except Exception:
                pass
            last_cf = time.time()
        if now - last_submit >= 1.2:
            try:
                page.run_js(
                    r"""
function isVisible(node) {
  if (!node) return false;
  const style = window.getComputedStyle(node);
  if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
  const rect = node.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0;
}
const titleHit = !!Array.from(document.querySelectorAll('h1,h2,div,span')).find((el) => {
  return (el.textContent || '').replace(/\s+/g, '').includes('完成注册');
});
if (!titleHit) return 'skip';
const cfInput = document.querySelector('input[name="cf-turnstile-response"]');
if (cfInput && String(cfInput.value||'').trim().length < 80) return 'wait-cf';
const buttons = Array.from(document.querySelectorAll('button[type="submit"], button'))
  .filter((n) => isVisible(n) && !n.disabled);
const btn = buttons.find((node) => {
  const t = (node.innerText || node.textContent || '').replace(/\s+/g, '').toLowerCase();
  return t.includes('完成注册') || t.includes('创建账户') || t.includes('sign up');
});
if (btn) { btn.click(); return 'clicked'; }
return 'no-btn';
"""
                )
            except Exception:
                pass
            last_submit = now
        try:
            cookies = page.cookies(all_domains=True, all_info=True) or []
            for item in cookies:
                if not isinstance(item, dict):
                    continue
                if str(item.get("name") or "") == "sso" and item.get("value"):
                    return str(item.get("value")).strip()
        except Exception:
            pass
        poll_wait(0.35, cancel)
    raise TimeoutError("等待登录凭证SSO超时")


def _is_disconnect_error(exc: BaseException) -> bool:
    msg = str(exc)
    return (
        "连接已断开" in msg
        or "disconnected" in msg.lower()
        or "PageDisconnected" in type(exc).__name__
        or "connection" in msg.lower() and "closed" in msg.lower()
    )


def _ensure_page(log: LogFn):
    """获取页面；断连则回收重建。"""
    try:
        page = _page()
        # 轻量探活
        try:
            _ = page.url
        except Exception:
            raise RuntimeError("page dead")
        return page
    except Exception:
        try:
            TabPool.release_tab()
        except Exception:
            pass
        return TabPool.get_tab()


def _mail_stage_retryable(exc: BaseException) -> bool:
    """邮箱/验证码阶段是否值得换邮重试。

    仅匹配收信/建邮相关失败；人机、资料、SSO 超时不换邮。
    """
    msg = str(exc)
    low = msg.lower()
    # 明确排除非邮箱阶段
    hard_exclude = (
        "人机",
        "turnstile",
        "cloudflare",
        "资料",
        "sso",
        "profile",
        "密码",
        "password",
    )
    if any(k in msg or k in low for k in hard_exclude):
        return False
    # 强匹配：验证码/邮件语义
    strong = (
        "验证码",
        "未收到",
        "邮件",
        "邮箱",
        "创建邮箱",
        "mail",
        "inbox",
        "verification code",
        "otp",
    )
    if any(k in msg or k in low for k in strong):
        return True
    # 弱匹配：仅当 stage 语义像收码超时（异常信息自带 code/mail）
    if ("timeout" in low or "超时" in msg) and any(
        k in low or k in msg for k in ("code", "mail", "验证", "收信", "poll")
    ):
        return True
    return False


def _open_signup_and_email_button(page, cancel: CancelFn | None, log: LogFn) -> None:
    """打开注册页并点到邮箱注册入口。"""
    page.get(SIGNUP_URL)
    try:
        page.wait.doc_loaded()
    except Exception:
        pass
    wait_until(
        lambda: bool(
            page.run_js(
                r"""
const candidates = Array.from(document.querySelectorAll('button, a, [role="button"]'));
return !!candidates.find((node) => {
  const text = (node.innerText || node.textContent || '').replace(/\s+/g, '');
  const lower = text.toLowerCase();
  return text.includes('使用邮箱') || lower.includes('email');
});
"""
            )
        ),
        timeout=5,
        interval=0.2,
        cancel=cancel,
    )
    _click_email_signup(page, cancel, log)


def register_with_browser(
    *,
    mail: MailProvider | None = None,
    cfg: dict | None = None,
    log: LogFn | None = None,
    cancel: CancelFn | None = None,
) -> RegisterResult:
    """执行一次完整浏览器注册，返回 SSO 账号。

    邮箱阶段支持换邮重试：验证码超时/收信失败时新建邮箱重走开页→填邮→收码。
    """
    cfg = cfg or get_config()
    # 注册过程完全静默；成功日志由铸造阶段统一输出
    quiet = _noop_log
    _ = log
    mail = mail or get_mail_provider(cfg)
    stages: dict[str, float] = {}
    stage = "init"
    t_all = time.perf_counter()
    try:
        mail_retry = max(1, int(cfg.get("mail_retry_count", 3) or 3))
    except Exception:
        mail_retry = 3

    def _mark(name: str, t0: float) -> None:
        stages[name] = (time.perf_counter() - t0) * 1000.0

    try:
        stage = "browser"
        t0 = time.perf_counter()
        if TabPool.get_browser() is None:
            TabPool.get_tab()
        _mark("browser", t0)

        page = _ensure_page(quiet)
        box: MailBox | None = None
        code = ""

        # 邮箱阶段：开页 → 建邮 → 收码 → 填码；失败则换邮重试
        for mail_try in range(1, mail_retry + 1):
            try:
                stage = "open_signup"
                t0 = time.perf_counter()
                page = _ensure_page(quiet)
                _open_signup_and_email_button(page, cancel, quiet)
                _mark("open_signup", t0)

                stage = "fill_email"
                t0 = time.perf_counter()
                box = mail.create()
                page = _ensure_page(quiet)
                _fill_email(page, box.address, cancel)
                _mark("fill_email", t0)

                stage = "fill_code"
                t0 = time.perf_counter()

                def _resend() -> None:
                    try:
                        p = _page()
                        p.run_js(
                            r"""
const nodes = Array.from(document.querySelectorAll('button, a, [role="button"]'));
const t = nodes.find((n) => {
  const x = (n.innerText || n.textContent || '').replace(/\s+/g,'').toLowerCase();
  return x.includes('重新发送') || x.includes('resend');
});
if (t && !t.disabled) { t.click(); return true; }
return false;
"""
                        )
                    except Exception:
                        pass

                code = mail.wait_code(
                    box,
                    timeout=float(cfg.get("mail_timeout", 150) or 150),
                    poll_interval=float(cfg.get("mail_poll_interval", 0.3) or 0.3),
                    cancel=cancel,
                    resend=_resend,
                    log=quiet,
                )
                page = _ensure_page(quiet)
                _fill_code(page, code, cancel)
                _mark("fill_code", t0)
                break
            except Cancelled:
                raise
            except Exception as mail_exc:
                if mail_try < mail_retry and _mail_stage_retryable(mail_exc):
                    try:
                        TabPool.prepare_for_next(recycle_every=1, force=True, log=None)
                    except Exception:
                        try:
                            TabPool.release_tab()
                        except Exception:
                            pass
                    poll_wait(0.4, cancel)
                    continue
                raise

        if box is None:
            raise RuntimeError("邮箱阶段未创建邮箱")

        stage = "fill_profile"
        t0 = time.perf_counter()
        given, family, password = build_profile()
        try:
            page = _ensure_page(quiet)
            poll_wait(1.2, cancel)
            wait_until(
                lambda: bool(
                    page.run_js(
                        r"""
return !!(
  document.querySelector('input[data-testid="givenName"], input[name="givenName"], input[autocomplete="given-name"]')
  || document.querySelector('input[name="cf-turnstile-response"], iframe[src*="turnstile"], iframe[src*="challenges.cloudflare"]')
);
"""
                    )
                ),
                timeout=8.0,
                interval=0.25,
                cancel=cancel,
            )
            poll_wait(0.6, cancel)
            # 注册过程静默：人机/资料细节不输出
            _fill_profile(page, given, family, password, cancel, quiet, cfg)
        except Exception as pe:
            if _is_disconnect_error(pe):
                raise RuntimeError("资料页浏览器连接断开") from pe
            raise
        _mark("fill_profile", t0)

        stage = "wait_sso"
        t0 = time.perf_counter()
        page = _ensure_page(quiet)
        sso = _wait_sso(page, cancel, quiet, timeout=float(cfg.get("sso_timeout", 180) or 180))
        cookies = _export_cookies(page)
        _mark("wait_sso", t0)

        account = AccountRecord(
            email=box.address,
            password=password,
            sso=sso,
            given_name=given,
            family_name=family,
            cookies=cookies,
            reg_method="browser",
        )
        _ = (time.perf_counter() - t_all) * 1000
        return RegisterResult(ok=True, account=account, stages_ms=stages)
    except Cancelled as e:
        return RegisterResult(ok=False, error=str(e), stage=stage, stages_ms=stages)
    except Exception as e:
        return RegisterResult(ok=False, error=str(e), stage=stage, stages_ms=stages)
