# -*- coding: utf-8 -*-
"""每线程一个 Chromium：复用清会话，错误时回收。

多线程约束：
- 每线程独立 browser / profile / debug port
- 禁止多线程共用同一 user-data-dir
"""

from __future__ import annotations

import threading
from typing import Any, Callable


class TabPool:
    """Per-thread Chromium 管理。"""

    _options_factory = None
    _options_lock = threading.Lock()
    _thread_local = threading.local()
    _all_browsers: list[Any] = []
    _all_browsers_lock = threading.Lock()
    # worker_id 可由业务线程 set_worker_id 注入，用于 profile 目录命名
    _worker_ids: dict[int, str] = {}
    _worker_ids_lock = threading.Lock()

    @classmethod
    def init(cls, browser_options_or_factory, log: Callable[[str], None] | None = None) -> None:
        with cls._options_lock:
            if callable(browser_options_or_factory):
                cls._options_factory = browser_options_or_factory
            else:
                cls._options_factory = lambda: browser_options_or_factory
        # 静默：不再输出模板初始化日志

    @classmethod
    def set_worker_id(cls, worker_id: str | int) -> None:
        """注册当前线程对应的 worker 名（如 R1），用于隔离 profile。"""
        with cls._worker_ids_lock:
            cls._worker_ids[threading.get_ident()] = str(worker_id)

    @classmethod
    def _profile_key(cls) -> str:
        tid = threading.get_ident()
        with cls._worker_ids_lock:
            wid = cls._worker_ids.get(tid)
        return wid or f"t{tid}"

    @classmethod
    def _create_browser(cls):
        from DrissionPage import Chromium

        with cls._options_lock:
            factory = cls._options_factory
        if factory is None:
            return None
        # 优先传 profile_key；工厂不支持时退回无参
        key = cls._profile_key()
        try:
            opts = factory(profile_key=key)  # type: ignore[call-arg]
        except TypeError:
            try:
                opts = factory(key)  # type: ignore[misc]
            except TypeError:
                opts = factory()
        browser = Chromium(opts)
        # 记录端口便于释放
        try:
            addr = str(getattr(opts, "address", "") or "")
            if ":" in addr:
                cls._thread_local.debug_port = int(addr.rsplit(":", 1)[-1])
        except Exception:
            cls._thread_local.debug_port = None
        with cls._all_browsers_lock:
            cls._all_browsers.append(browser)
        return browser

    @classmethod
    def _unregister(cls, browser) -> None:
        if browser is None:
            return
        with cls._all_browsers_lock:
            cls._all_browsers = [b for b in cls._all_browsers if b is not browser]

    @classmethod
    def _stealth_tab(cls, tab) -> None:
        """新标签页尽量隐藏 webdriver（扩展也会做，这里双保险）。"""
        if tab is None:
            return
        try:
            tab.run_js(
                """
try {
  Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
} catch (e) {}
try {
  if (window.chrome) {
    // keep chrome object present like real Chrome
  }
} catch (e) {}
"""
            )
        except Exception:
            pass

    @classmethod
    def get_tab(cls):
        tab = getattr(cls._thread_local, "tab", None)
        if tab is not None:
            return tab
        browser = cls._create_browser()
        if browser is None:
            raise RuntimeError("TabPool 未初始化")
        tab_ids = browser.tab_ids
        tab = browser.get_tab(tab_ids[0]) if tab_ids else browser.new_tab()
        cls._thread_local.browser = browser
        cls._thread_local.tab = tab
        cls._thread_local.served = 0
        cls._stealth_tab(tab)
        return tab

    @classmethod
    def get_browser(cls):
        return getattr(cls._thread_local, "browser", None)

    @classmethod
    def sync_tab(cls) -> None:
        browser = getattr(cls._thread_local, "browser", None)
        if browser is None:
            return
        tabs = browser.tab_ids
        if tabs:
            cls._thread_local.tab = browser.get_tab(tabs[-1])

    @classmethod
    def clear_session(cls, log: Callable[[str], None] | None = None) -> bool:
        """清 cookie/storage 并收敛标签，保留 Chromium 进程以便复用。"""
        browser = getattr(cls._thread_local, "browser", None)
        tab = getattr(cls._thread_local, "tab", None)
        if browser is None:
            return False
        try:
            if tab is not None:
                try:
                    tab.get("about:blank")
                except Exception:
                    pass
                for js in (
                    "try{localStorage.clear()}catch(e){}",
                    "try{sessionStorage.clear()}catch(e){}",
                    "try{indexedDB.databases&&indexedDB.databases().then(ds=>ds.forEach(d=>indexedDB.deleteDatabase(d.name)))}catch(e){}",
                ):
                    try:
                        tab.run_js(js)
                    except Exception:
                        pass

            # 尽力清 cookie（API 因 DrissionPage 版本而异）
            cleared = False
            for target in (tab, browser):
                if target is None or cleared:
                    continue
                for attr_path in (("set", "cookies", "clear"), ("cookies", "clear")):
                    try:
                        obj = target
                        for name in attr_path[:-1]:
                            obj = getattr(obj, name)
                        getattr(obj, attr_path[-1])()
                        cleared = True
                        break
                    except Exception:
                        continue
            if not cleared:
                try:
                    cks = browser.cookies()
                    if isinstance(cks, list):
                        for c in cks:
                            try:
                                browser.set.cookies.remove(c)  # type: ignore[attr-defined]
                            except Exception:
                                pass
                except Exception:
                    pass

            # 多标签收敛到一个
            try:
                tabs = list(browser.tab_ids or [])
                if len(tabs) > 1:
                    keep = tabs[0]
                    for tid in tabs[1:]:
                        try:
                            browser.get_tab(tid).close()
                        except Exception:
                            pass
                    cls._thread_local.tab = browser.get_tab(keep)
                elif tabs:
                    cls._thread_local.tab = browser.get_tab(tabs[0])
            except Exception:
                cls.sync_tab()
            cls._stealth_tab(getattr(cls._thread_local, "tab", None))
            return True
        except Exception:
            return False

    @classmethod
    def mark_served(cls) -> int:
        n = int(getattr(cls._thread_local, "served", 0) or 0) + 1
        cls._thread_local.served = n
        return n

    @classmethod
    def served_count(cls) -> int:
        return int(getattr(cls._thread_local, "served", 0) or 0)

    @classmethod
    def release_tab(cls) -> None:
        browser = getattr(cls._thread_local, "browser", None)
        port = getattr(cls._thread_local, "debug_port", None)
        if browser is not None:
            try:
                browser.quit(del_data=True)
            except TypeError:
                try:
                    browser.quit()
                except Exception:
                    pass
            except Exception:
                pass
            cls._unregister(browser)
        try:
            from grok_auto.browser.options import release_debug_port

            release_debug_port(port)
        except Exception:
            pass
        cls._thread_local.browser = None
        cls._thread_local.tab = None
        cls._thread_local.served = 0
        cls._thread_local.debug_port = None

    @classmethod
    def prepare_for_next(cls, *, recycle_every: int = 25, force: bool = False, log=None):
        """账号间：优先清会话复用，达阈值则完整回收。"""
        if force or cls.get_browser() is None:
            cls.release_tab()
            return cls.get_tab()
        every = int(recycle_every or 0)
        served = cls.served_count()
        if every > 0 and served >= every:
            if log:
                pass
            cls.release_tab()
            return cls.get_tab()
        if cls.clear_session(log=log):
            cls.mark_served()
            return cls.get_tab()
        cls.release_tab()
        return cls.get_tab()

    @classmethod
    def shutdown(cls) -> None:
        cls.release_tab()
        with cls._all_browsers_lock:
            browsers = list(cls._all_browsers)
            cls._all_browsers.clear()
        for b in browsers:
            try:
                b.quit(del_data=True)
            except Exception:
                try:
                    b.quit()
                except Exception:
                    pass
