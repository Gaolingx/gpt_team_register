# grok_auto_register

Grok 免费账号自动注册机（**重写版 v2**）。

> **免责声明**：仅用于自动化流程研究、个人学习与测试环境验证。请遵守 xAI / Grok 服务条款与当地法律法规。禁止滥用、倒卖账号或攻击性用途。风险自负。

## 设计原则

| 原则 | 说明 |
|------|------|
| SSO ≠ OIDC | 账本 SSO 不能直接打免费 Grok 4.5；必须再铸 CPA JSON |
| 分层 | `mail` / `browser` / `session` / `credential` / `orchestrator` |
| 协议优先铸造 | SSO → 纯 HTTP Device Flow；失败回退浏览器 |
| 自动写 JSON，不自动上号 | 默认只写 `data/cpa_auths/xai-*.json`，不热加载 CPA |
| 条件等待 | 少固定 sleep，就绪即继续 |

## 目录

```text
grok_auto_register/
  register_cli.py           # CLI 入口
  config.example.json       # 配置模板（复制为 config.json）
  LICENSE
  turnstilePatch/           # CF Turnstile 辅助扩展
  data/                     # 运行产物（默认 gitignore）
    accounts.txt            # email----password----sso
    cpa_auths/              # xai-<email>.json
  grok_auto/
    mail/                   # Cloudflare / DuckMail / YYDS / TempMail.lol
    browser/                # TabPool / 等待 / 选项
    session/                # 浏览器注册 FSM → SSO
    credential/             # OIDC mint + CPA schema
    orchestrator/           # 队列 / pending / 指标
  scripts/backfill_cpa.py
```

## 安装

```bash
# 克隆后在项目根目录
uv sync
cp config.example.json config.json
# 编辑 config.json：邮箱、代理等（切勿提交该文件）
```

依赖：Python 3.13、本机 Chrome/Edge、可访问 `accounts.x.ai` 与邮箱 API。

## 运行

```bash
# 注册 1 个（含铸造 JSON，不热加载）
uv run python register_cli.py --extra 1

# 批量：目标总数 100，2 注册线程 + 自动 mint workers + 背压
uv run python register_cli.py --count 100 --threads 2 --mint-workers 2

# 在已有账本上再追加 5 个
uv run python register_cli.py --extra 5 --threads 2 --mint-queue-max 4

# 批量加速：关模型探测
uv run python register_cli.py --count 100 --threads 2 --no-probe

# 仅补铸账本缺失的 CPA JSON
uv run python scripts/backfill_cpa.py --limit 10
```

### 常用 CLI

| 参数 | 说明 |
|------|------|
| `--count N` | 账本最终总行数目标（含已有；`0`=不限） |
| `--extra N` | 再新注册 N 个 |
| `--threads N` | 注册并发 1–8 |
| `--mint-workers N` | 铸造并发：`-1` 自动；`0` 内联；`1–10` 固定 |
| `--mint-queue-max N` | 铸造队列背压：`-1` 自动约 `2×workers` |
| `--accounts-file` | 账本路径 |
| `--account-retries` | 整号失败后再试次数（默认 1） |
| `--no-fast` | 关闭快速等待 |
| `--no-probe` | 铸造后不探测模型 |

流水线：注册线程 R → 写账本 → 有界 mint 队列 → 铸造线程 M。峰值浏览器约 **R + M**。  
邮箱阶段验证码失败会换邮重试；整号失败默认再试 1 次。

成功日志示例：

```text
[09:10:02] [线程R1] grok注册成功，获取模型grok-4.5，铸造成功且文件为：xai-xxx.json
```

## 配置要点

| 字段 | 建议 |
|------|------|
| `email_provider` | `cloudflare` / `duckmail` / `yyds` / `tempmail_lol` |
| `duckmail_api_key` | 选 DuckMail 时填写（可空，视服务是否要求） |
| `yyds_api_key` / `yyds_jwt` | 选 YYDS 时至少填一个 |
| `tempmail_lol_api_key` | 选 TempMail.lol 时可选；免费可不填 |
| `cpa_export_enabled` | `true`（写出 JSON） |
| `cpa_copy_to_hotload` | `false`（不自动上号）；需要时再开并填 `cpa_hotload_dir` |
| `cpa_prefer_protocol` | `true` |
| `cpa_probe_after_write` | 批量 `false`；排查可 `true` |
| `cpa_mint_queue_max` | `0`=自动背压；或固定上限 |
| `mail_retry_count` | 邮箱阶段换邮次数，默认 3 |
| `register_account_retries` | 整号再试次数，默认 1 |
| `cpa_base_url` | `https://cli-chat-proxy.grok.com/v1` |
| `proxy` / `cpa_proxy` | 本机代理 |
| `browser_window_mode` | `normal` 前台（默认）；`offscreen` 后台；`minimized` 最小化（已移除无头） |

完整字段见 `config.example.json`。

## 产物

1. `data/accounts.txt`：`邮箱----密码----sso`
2. `data/cpa_auths/xai-*.json`：CPA / CLIProxyAPI 用 OIDC

手动上号：

```bash
cp data/cpa_auths/xai-USER@domain.json "你的CPA/auth-dir/"
```

## 安全（开源必读）

**绝对不要提交或上传：**

- `config.json`（含 API Key、代理、邮箱服务配置）
- `data/accounts.txt`、`data/cpa_auths/*.json`、`*.zip`
- `data/browser_profiles/`、日志、截图

仓库已用 `.gitignore` 忽略上述路径。发布前请自检：

```bash
# 初始化仓库后检查将要提交的文件
git status
git check-ignore -v config.json data/accounts.txt
# 全文搜索本机域名 / 密钥碎片
rg -n "api_key|password|token|127.0.0.1:789" --glob '!*.lock' --glob '!.venv/**'
```

若曾把密钥写进 git 历史，仅删文件不够，需轮换密钥并清理历史。

## 与旧版关系

旧版 `grok_reg-protocol_cpa` 为单体 + GUI 历史包袱。  
本仓库按分层架构重写：**铸造核心在 `credential/`，注册为精简 FSM，邮箱 Provider 化，CLI 只做编排。**

## License

MIT（见 `LICENSE`）。
