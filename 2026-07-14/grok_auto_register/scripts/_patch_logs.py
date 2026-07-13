# -*- coding: utf-8 -*-
"""一次性补丁：统一步骤日志为 20～50 字清晰中文。"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def patch(path: Path, repls: list[tuple[str, str]], label: str) -> None:
    t = path.read_text(encoding="utf-8")
    for a, b in repls:
        if a not in t:
            print(f"MISS {label}: {a[:60]!r}")
        else:
            t = t.replace(a, b)
    path.write_text(t, encoding="utf-8", newline="\n")
    print(f"OK {label}")


def main() -> None:
    # turnstile
    patch(
        ROOT / "grok_auto/browser/turnstile.py",
        [
            ('log("开始: 已点击 Turnstile 复选框（shadow）")', 'log("已点击人机验证框")'),
            ('log(f"开始: 已尝试 JS 点击 Turnstile（{ok}）")', 'log("已尝试点击人机验证")'),
            ('log("开始: Cloudflare 真人验证")', 'log("开始进行人机验证")'),
            (
                'log(f"成功: Cloudflare 验证通过（token 长度 {len(token)}）")',
                'log("人机验证已通过")',
            ),
            ('log("成功: Cloudflare 已通过")', 'log("人机验证已通过")'),
            ('log("成功: 未检测到 Cloudflare 控件，跳过")', 'log("无需人机验证，已跳过")'),
            (
                'raise RuntimeError(\n        f"Cloudflare 真人验证超时（{int(timeout)}s，点击尝试 {clicks} 次，当前 token 长度 {turnstile_token_len(page)}）"\n    )',
                'raise RuntimeError("人机验证超时，请检查网络或代理")',
            ),
        ],
        "turnstile",
    )

    patch(
        ROOT / "grok_auto/browser/tab_pool.py",
        [
            ('log("成功: 浏览器选项模板已初始化")', 'log("浏览器模板已初始化")'),
            ('log("成功: 浏览器会话已清理（复用进程）")', 'log("浏览器会话已清理")'),
            ('log(f"失败: 清理会话 — {exc}")', 'log("清理浏览器会话失败")'),
            (
                'log(f"开始: 浏览器完整回收（已复用 {served} 次）")',
                'log("开始完整回收浏览器")',
            ),
        ],
        "tab_pool",
    )

    patch(
        ROOT / "grok_auto/mail/cloudflare.py",
        [
            ('log("开始: 触发重新发送验证码")', 'log("已触发重发验证码")'),
            ('log(f"失败: 重发验证码 — {exc}")', 'log("重发验证码失败")'),
            ('log(f"失败: 拉取邮件列表 — {exc}")', 'log("拉取邮件列表失败")'),
            ('log(f"成功: 从列表解析验证码 {code}")', 'log("已从邮件列表取得验证码")'),
            ('log(f"成功: 从详情解析验证码 {code}")', 'log("已从邮件详情取得验证码")'),
            ('log(f"失败: 邮件详情 — {exc}")', 'log("读取邮件详情失败")'),
            (
                'raise TimeoutError(f"Cloudflare 在 {timeout}s 内未收到验证码: {box.address}")',
                'raise TimeoutError("等待验证码超时")',
            ),
        ],
        "cloudflare",
    )

    patch(
        ROOT / "grok_auto/session/browser_register.py",
        [
            ('log("资料已填")', 'log("资料表单已填写完成")'),
            ('log("人机未通过")', 'log("人机验证未通过")'),
            ('log("人机失败")', 'log("人机验证过程失败")'),
            ('log("资料已提交")', 'log("资料页已提交成功")'),
            ('log("已获SSO")', 'log("已成功获取登录凭证SSO")'),
            ('log("重建浏览器")', 'log("浏览器断连，正在重建")'),
            ('log("启动浏览器")', 'log("开始启动浏览器")'),
            ('log("浏览器就绪")', 'log("浏览器已启动就绪")'),
            ('log("打开注册页")', 'log("开始打开账号注册页")'),
            ('log("注册页就绪")', 'log("注册页面已打开就绪")'),
            ('log("创建邮箱")', 'log("开始创建临时邮箱")'),
            ('log("填写邮箱")', 'log("开始填写并提交邮箱")'),
            ('log("邮箱已提交")', 'log("邮箱填写提交完成")'),
            ('log("拉取验证码")', 'log("开始拉取邮箱验证码")'),
            ('log("提交验证码")', 'log("开始提交邮箱验证码")'),
            ('log("验证码完成")', 'log("验证码提交已完成")'),
            ('log("填写资料")', 'log("开始填写注册资料")'),
            ('log("资料完成")', 'log("注册资料填写完成")'),
            ('log("等待SSO")', 'log("开始等待登录凭证SSO")'),
            ('log("注册完成")', 'log("账号注册流程已完成")'),
            ('log(f"失败:{stage}")', 'log(f"注册失败，阶段:{stage}")'),
            ('raise RuntimeError("人机超时")', 'raise RuntimeError("人机验证等待超时")'),
            ('raise RuntimeError("资料页断连")', 'raise RuntimeError("资料页浏览器连接断开")'),
            ('raise RuntimeError("资料失败")', 'raise RuntimeError("注册资料填写失败")'),
            ('raise TimeoutError("等待SSO超时")', 'raise TimeoutError("等待登录凭证SSO超时")'),
        ],
        "browser_register",
    )

    patch(
        ROOT / "grok_auto/credential/mint.py",
        [
            ('log("开始铸造")', 'log("开始铸造CPA认证")'),
            ('log("协议铸造")', 'log("开始协议设备授权铸造")'),
            ('log("协议成功")', 'log("协议设备授权铸造成功")'),
            ('log("协议失败")', 'log("协议铸造失败，准备回退")'),
            ('log("回退浏览器")', 'log("回退到浏览器方式铸造")'),
            ('log("协议异常")', 'log("协议铸造异常，准备回退")'),
            ('log("无SSO走浏览器")', 'log("缺少SSO，改用浏览器铸造")'),
            ('log("浏览器铸造")', 'log("开始浏览器方式铸造")'),
            ('log("浏览器成功")', 'log("浏览器方式铸造成功")'),
            ('log("浏览器失败")', 'log("浏览器方式铸造失败")'),
            ('log("写出JSON")', 'log("认证JSON文件已写出")'),
            ('log("探测模型")', 'log("开始探测上游模型列表")'),
            ('log("探测通过")', 'log("探测通过，含grok-4.5")'),
            ('log("探测失败")', 'log("探测失败，未找到grok-4.5")'),
            ('log("探测对话")', 'log("开始探测最小对话请求")'),
            ('log("对话通过")', 'log("最小对话探测通过")'),
            ('log("对话失败")', 'log("最小对话探测失败")'),
        ],
        "mint",
    )

    # pipeline
    p = ROOT / "grok_auto/orchestrator/pipeline.py"
    t = p.read_text(encoding="utf-8")
    if "from grok_auto.logging_short import" not in t:
        t = t.replace(
            "from grok_auto.browser.options import create_browser_options, describe_browser_env\n",
            "from grok_auto.browser.options import create_browser_options, describe_browser_env\n"
            "from grok_auto.logging_short import short, wrap as wrap_log\n",
        )
    repls = [
        ('log(f"成功: 铸造跳过 {email}（已关闭）")', 'log("铸造已关闭，本号跳过")'),
        ('log(f"开始: 铸造 {email}")', 'log("开始铸造本号认证")'),
        ('log(f"成功: 已复制到热加载 {dst}")', 'log("已复制到热加载目录")'),
        ('log(f"失败: 热加载复制 — {e}")', 'log("复制到热加载目录失败")'),
        (
            'log(f"成功: 铸造完成 {email}（{method}，{ms:.0f}ms）→ {result.get(\'path\')}")',
            'log(f"本号铸造成功，方式:{method}")',
        ),
        ('log(f"失败: 铸造 — {result.get(\'error\')}")', 'log("本号铸造失败")'),
        ('log(f"失败: 铸造异常 — {e}")', 'log("铸造过程发生异常")'),
        ('log(f"失败: pending 落盘 — {e}")', 'log("待铸造任务落盘失败")'),
        ('log("成功: 跳过铸造（cpa_export_enabled=false）")', 'log("配置关闭，跳过铸造")'),
        ('log(f"成功: 已提交铸造任务 {acc.email}")', 'log("已提交铸造任务到队列")'),
        (
            'lg(f"成功: 注册线程就绪（profile=R{wid}）")',
            'lg(f"注册线程R{wid}已就绪")',
        ),
        (
            'lg(f"开始: 注册账号 {idx}/{extra}")',
            'lg(f"开始注册第{idx}/{extra}个账号")',
        ),
        ('lg(f"失败: 注册异常 — {e}")', 'lg("注册线程发生异常")'),
        (
            'make_log("0")("开始: 等待铸造队列清空")',
            'make_log("0")("等待铸造队列清空中")',
        ),
        (
            'make_log("0")("成功: 铸造队列已清空")',
            'make_log("0")("铸造队列已全部清空")',
        ),
        (
            'out(f"成功: 已恢复待铸造 {nrec} 条")',
            'out(short(f"已恢复待铸造任务{nrec}条", 50))',
        ),
    ]
    for a, b in repls:
        if a not in t:
            print("MISS pipeline:", a[:70])
        else:
            t = t.replace(a, b)

    old_make = """    def make_log(wid: str) -> LogFn:
        def _log(msg: str) -> None:
            log_q.put(f"[{time.strftime('%H:%M:%S')}] [{wid}] {msg}")

        return _log"""
    new_make = """    def make_log(wid: str) -> LogFn:
        def _log(msg: str) -> None:
            # 步骤日志：写清楚，最长 50 字
            log_q.put(f"[{time.strftime('%H:%M:%S')}] [{wid}] {short(msg, 50)}")

        return wrap_log(_log, 50)"""
    if old_make in t:
        t = t.replace(old_make, new_make)
    else:
        print("MISS make_log block")

    # 启动摘要
    old_start = """    out(f"开始: 额外注册 {extra} 个（已有 {done}，注册线程={threads}，铸造线程={mint_workers}）")
    out(
        f"成功: 邮箱={cfg.get('email_provider')}，CPA写出={cfg.get('cpa_export_enabled')}，"
        f"热加载={cfg.get('cpa_copy_to_hotload')}"
    )
    out(f"成功: {describe_browser_env(cfg)}")"""
    new_start = """    out(short(f"开始批量注册{extra}个号，注册线程{threads}，铸造线程{mint_workers}", 50))
    out(short(f"邮箱通道{cfg.get('email_provider')}，写出CPA={cfg.get('cpa_export_enabled')}", 50))
    out(short("浏览器使用本机Chrome并按线程隔离配置", 50))"""
    if old_start in t:
        t = t.replace(old_start, new_start)
    else:
        print("MISS start block")

    old_end = """    out(
        f"成功: 本轮结束 — 注册成功 {s['reg_success']}，注册失败 {s['reg_fail']}，"
        f"铸造成功 {s['mint_success']}，铸造失败 {s['mint_fail']}，跳过 {s['mint_skip']}"
    )"""
    new_end = """    out(short(
        f"本轮结束：注册成功{s['reg_success']}失败{s['reg_fail']}，"
        f"铸造成功{s['mint_success']}失败{s['mint_fail']}",
        50,
    ))"""
    if old_end in t:
        t = t.replace(old_end, new_end)
    else:
        print("MISS end block")

    p.write_text(t, encoding="utf-8", newline="\n")
    print("OK pipeline")


if __name__ == "__main__":
    main()
