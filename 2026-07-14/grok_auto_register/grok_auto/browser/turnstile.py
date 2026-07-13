# -*- coding: utf-8 -*-
"""Cloudflare Turnstile 自动处理（对齐旧注册机可用逻辑）。

要点：
1. 不要频繁 turnstile.reset()——会打断已在进行的验证
2. 优先 shadow DOM 点复选框（DrissionPage），再 JS 兜底
3. 点一次后给足时间等 token，而不是狂点
4. token 以 input[name=cf-turnstile-response] 为准
"""

from __future__ import annotations

import time
from typing import Any, Callable

from grok_auto.browser.waits import poll_wait, raise_if_cancelled

LogFn = Callable[[str], None]
CancelFn = Callable[[], bool]


def turnstile_token(page: Any) -> str:
    """读取当前 Turnstile token。"""
    try:
        token = page.run_js(
            """
try {
  const el = document.querySelector('input[name="cf-turnstile-response"]');
  const byInput = String((el && el.value) || '').trim();
  if (byInput) return byInput;
  if (window.turnstile && typeof turnstile.getResponse === 'function') {
    const r = String(turnstile.getResponse() || '').trim();
    if (r) return r;
  }
  // 有些实现挂在 textarea
  const ta = document.querySelector('textarea[name="cf-turnstile-response"]');
  return String((ta && ta.value) || '').trim();
} catch (e) { return ''; }
"""
        )
        return str(token or "").strip()
    except Exception:
        return ""


def turnstile_token_len(page: Any) -> int:
    return len(turnstile_token(page))


def turnstile_present(page: Any) -> bool:
    try:
        return bool(
            page.run_js(
                """
return !!(
  document.querySelector('input[name="cf-turnstile-response"], textarea[name="cf-turnstile-response"]')
  || document.querySelector(
       'iframe[src*="turnstile"], iframe[src*="challenges.cloudflare.com"], div.cf-turnstile, [data-sitekey]'
     )
);
"""
            )
        )
    except Exception:
        return False


def apply_token(page: Any, token: str) -> int:
    """回填 token 到隐藏域。"""
    token = (token or "").strip()
    if not token:
        return 0
    try:
        n = page.run_js(
            """
const token = String(arguments[0] || '').trim();
const cfInput = document.querySelector(
  'input[name="cf-turnstile-response"], textarea[name="cf-turnstile-response"]'
);
if (!cfInput || !token) return 0;
const nativeSetter = Object.getOwnPropertyDescriptor(
  window.HTMLInputElement.prototype, 'value'
)?.set || Object.getOwnPropertyDescriptor(
  window.HTMLTextAreaElement.prototype, 'value'
)?.set;
if (nativeSetter) nativeSetter.call(cfInput, token);
else cfInput.value = token;
cfInput.dispatchEvent(new Event('input', { bubbles: true }));
cfInput.dispatchEvent(new Event('change', { bubbles: true }));
return String(cfInput.value || '').trim().length;
""",
            token,
        )
        return int(n or 0)
    except Exception:
        return 0


def _click_shadow_checkbox(page: Any, log: LogFn) -> bool:
    """旧版核心路径：cf-turnstile-response 父级 shadow → iframe → body shadow → input。"""
    try:
        challenge_input = None
        for sel in ("@name=cf-turnstile-response", "css:input[name='cf-turnstile-response']"):
            try:
                challenge_input = page.ele(sel, timeout=0.4)
                if challenge_input is not None:
                    break
            except Exception:
                continue
        if challenge_input is None:
            return False

        wrapper = challenge_input.parent()
        iframe = None
        try:
            iframe = wrapper.shadow_root.ele("tag:iframe", timeout=0.5)
        except Exception:
            iframe = None
        if iframe is None:
            # 有的结构 iframe 在兄弟节点
            try:
                iframe = wrapper.ele("tag:iframe", timeout=0.3)
            except Exception:
                iframe = None
        if iframe is None:
            return False

        try:
            iframe.run_js(
                """
window.dtp = 1;
function getRandomInt(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}
let sx = getRandomInt(800, 1200);
let sy = getRandomInt(400, 700);
Object.defineProperty(MouseEvent.prototype, 'screenX', { value: sx });
Object.defineProperty(MouseEvent.prototype, 'screenY', { value: sy });
"""
            )
        except Exception:
            pass

        try:
            body = iframe.ele("tag:body", timeout=0.5)
            if body is None:
                return False
            body_sr = body.shadow_root
            # 常见：input checkbox / 可点击 mark
            btn = None
            for how in ("tag:input", "css:input[type=checkbox]", "css:.mark", "tag:label"):
                try:
                    btn = body_sr.ele(how, timeout=0.2)
                    if btn is not None:
                        break
                except Exception:
                    continue
            if btn is None:
                return False
            # 真实点击优先
            try:
                btn.click(by_js=False)
            except Exception:
                try:
                    btn.click()
                except Exception:
                    page.run_js("arguments[0].click();", btn)
            return True
        except Exception:
            return False
    except Exception:
        return False


def _click_js_fallback(page: Any, log: LogFn) -> bool:
    """JS 兜底点击。"""
    try:
        ok = page.run_js(
            """
// 1) 点可见 turnstile 容器
const nodes = Array.from(document.querySelectorAll('div,span,iframe,label')).filter((n) => {
  const txt = ((n.className || '') + ' ' + (n.id || '') + ' ' + (n.getAttribute?.('src') || '')).toLowerCase();
  return txt.includes('turnstile') || txt.includes('cf-chl') || txt.includes('challenges.cloudflare');
});
for (const n of nodes) {
  try {
    const r = n.getBoundingClientRect();
    if (r.width > 10 && r.height > 10 && typeof n.click === 'function') {
      n.click();
      return 'container';
    }
  } catch (e) {}
}
// 2) 直接点 iframe
const ifr = document.querySelector(
  'iframe[src*="challenges.cloudflare.com"], iframe[src*="turnstile"]'
);
if (ifr) {
  try { ifr.click(); return 'iframe'; } catch (e) {}
}
return '';
"""
        )
        if ok:
            return True
    except Exception:
        pass
    return False


def click_turnstile(page: Any, log: LogFn | None = None) -> bool:
    """执行一次点击尝试。"""
    log = log or (lambda _m: None)
    if _click_shadow_checkbox(page, log):
        return True
    return _click_js_fallback(page, log)


def solve_turnstile(
    page: Any,
    *,
    timeout: float = 60.0,
    cancel: CancelFn | None = None,
    log: LogFn | None = None,
    min_len: int = 80,
    do_reset: bool = False,
) -> str:
    """主动解 Turnstile，返回 token。

    对齐旧 getTurnstileToken：循环读 token → 点 checkbox → 等待，默认不 reset。
    """
    log = log or (lambda _m: None)
    if page is None:
        raise RuntimeError("页面未就绪，无法执行 Turnstile")

    if do_reset:
        try:
            page.run_js(
                "try { if (window.turnstile && typeof turnstile.reset === 'function') turnstile.reset(); } catch(e) {}"
            )
        except Exception:
            pass

    deadline = time.time() + max(8.0, float(timeout))
    clicks = 0
    last_click = 0.0

    while time.time() < deadline:
        raise_if_cancelled(cancel)

        token = turnstile_token(page)
        if len(token) >= min_len:
            # 确保写回隐藏域
            apply_token(page, token)
            return token

        now = time.time()
        # 每 2.5s 最多点一次，避免狂点导致页面崩
        if now - last_click >= 2.5:
            if click_turnstile(page, log):
                clicks += 1
            last_click = now

        poll_wait(1.0, cancel)

    raise RuntimeError("人机验证超时，请检查网络或代理")


def ensure_turnstile_ok(
    page: Any,
    *,
    timeout: float = 60.0,
    cancel: CancelFn | None = None,
    log: LogFn | None = None,
    min_len: int = 80,
) -> bool:
    """有 Turnstile 则解；没有则 True。"""
    log = log or (lambda _m: None)
    # 等控件出现（最多 5s）
    appear_deadline = time.time() + 5.0
    saw = False
    while time.time() < appear_deadline:
        if turnstile_present(page):
            saw = True
            break
        # 也可能已有 token 但控件难检测
        if turnstile_token_len(page) >= min_len:
            return True
        poll_wait(0.25, cancel)

    if not saw and turnstile_token_len(page) < min_len:
        # 再扫一次 DOM
        if not turnstile_present(page):
            return True

    if turnstile_token_len(page) >= min_len:
        return True

    token = solve_turnstile(
        page,
        timeout=timeout,
        cancel=cancel,
        log=log,
        min_len=min_len,
        do_reset=False,
    )
    if token:
        apply_token(page, token)
        return True
    return False
