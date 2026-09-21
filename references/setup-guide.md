# 首次部署指南

> 目标：让 `soul-skill` 能在本机跑通一次真实对话。
> 技能自带完整引擎（`engine/`），**不需要**任何外部目录。

## 前置条件

| 项 | 要求 | 说明 |
|---|---|---|
| 引擎 | 技能自带 `engine/`（`soul.py` + `engine/`） | ✅ 已就位，119 个模块 / 约 1.9MB（不含 `.venv` 与 `data/`） |
| 引擎 Python | ≥ 3.10（3.11–3.13 最佳） | 由 `setup` 自动定位；系统 `python3` 若为 3.9 则不可用 |
| 依赖 | openai / httpx / requests / python-dotenv（约 42MB） | 由 `setup --minimal` 自动安装 |
| 可选依赖 | numpy / fastembed / onnxruntime | **仅向量记忆用，默认不装**（见下文） |
| 模型 | 任意 OpenAI 兼容接口的 Key | 填入 `engine/.env`（推荐）或 `engine/config.json` |

> ⚠️ 不要用 Python 3.14：`onnxruntime==1.20.0` 没有对应轮子，`setup` 会失败。

## 要不要装向量记忆？（默认不装）

引擎的语义记忆检索依赖 `fastembed` + `onnxruntime`（约 200MB 依赖 + 100MB 模型）。
**默认不装即可**——缺了它引擎会自动降级，对话完全不受影响。

### 判断依据

1. **skill 的核心动作不需要它**：`chat` / `state` / `pending` / `drain` 都不经过向量，
   向量只影响「从已有记忆里检索」这一个环节，不参与回复生成。
2. **冷启动阶段收益约等于零**：向量检索是在「已有记忆」里找人。
   新部署的数据家目录（`~/.soul-skill/data/`）是空的，前几百条对话内几乎没有可供语义检索的记忆。
3. **分发成本高且脆**：每个使用环境都要装 200MB+，首次还要下载模型；
   下载失败会直接卡住首启——而 skill 恰恰是要「到处装」的东西。

### 什么时候值得装

| 场景 | 装向量？ |
|---|---|
| 分发给别人 / 多工具调用 / 演示 | ❌ 保持 minimal |
| 你自己长期用这一个灵魂（记忆已积累数百条、跨月相处） | ✅ 值得 |
| 纯云端执行的工具（技能跑在别人服务器上） | ❌ 根本跑不了本地 Python |

收益随记忆量增长，冷启动阶段接近于零：

```
记忆条数      0 ────── 50 ────── 200 ────── 500+
向量收益      无        低         中          高
回退检索      够用      够用       勉强        吃力
```

### 有 / 无向量，差在哪

| 能力 | 无向量（回退） | 有向量（BGE） |
|---|---|---|
| 记忆注入 prompt | 按层级 + 情绪 + 重要性排序 | 语义相似度检索 |
| 「上次那个事」跨词联想 | 只能字面匹配（`LIKE %kw%`） | 能找到 |
| 情绪加权检索 | 部分保留 | 完整（`MOOD_MULTIPLIER`） |
| 话题扫描 `topics.py` | 直接跳过（仅词重叠兜底） | 语义相关旧话题 |
| 对话本身 | ✅ | ✅ **完全不受影响** |

### 后补是安全的

先用 minimal，之后想开向量随时跑一次完整版 `setup` 即可——
`memory.py` 启动时会异步 `rebuild_index()`，把 `memory` 表里 `level > 2` 的记忆重新编码，
**历史记忆不会丢，也不需要从头再来**。

## 步骤

```bash
# {baseDir} = 本技能所在目录（OpenClaw / QClaw 会解析；
#             CodeBuddy / TRAE / Qoder / Cursor / Claude Code / Codex 等请替换为实际路径）
S="{baseDir}/scripts/soulctl.py"

# 1) 自检（此时大概率报缺依赖，属正常）
python3 "$S" doctor

# 2) 建虚拟环境并装依赖（默认最小集；向量记忆见上一节，可后补）
python3 "$S" setup --minimal
#    若要连向量记忆一起装：
# python3 "$S" setup

# 3) 重新自检，应看到 python 指向 .venv、deps_required_ok: true
python3 "$S" doctor
```

**第 4 步：配置模型接口**。

### 方式 A：在 OpenClaw / QClaw 里跑（推荐，零手工输入）

```bash
python3 "$S" autoconfig          # 探测宿主已配好的模型并写进 .env
python3 "$S" autoconfig --dry-run  # 只看不写
```

它会按顺序探测并**逐个验证连通性**，只把真正可用的那一个写进 `engine/.env`：

1. `models.providers.<id>` —— 直连厂商（纯模型推理，快）
2. `gateway.http.endpoints.chatCompletions` —— 走宿主网关（复用宿主的模型路由，
   但每次调用会执行一轮完整 Agent，较慢）

探测全部失败时**不会写入**，并会说明原因（key 失效 / 宿主未运行等）。

### 方式 B：独立使用（手动填）

引擎走 OpenAI 兼容协议，任意兼容厂商都能接。
最省事的是只填 `provider`——它会自动补全接口地址与模型名：

```jsonc
{
  "ai": {
    "provider": "deepseek",   // 或 openai / moonshot / zhipu / dashscope / volces /
                              // siliconflow / openrouter / groq / ollama / vllm ...
    "api_key": "sk-你的密钥",
    "temperature": 0.85,
    "max_tokens": 1024
  }
}
```

预设表（含各家默认 `base_url` 与模型名）见 `engine/core/ai.py` 的 `PROVIDERS`。

若你的服务不在预设里，就别填 `provider`，把三个值写全：

```jsonc
{
  "ai": {
    "api_key": "sk-xxx",
    "api_base": "https://your-endpoint/v1",
    "model": "your-model-name"
  }
}
```

也可以改用环境变量（优先级高于 config.json），见 `engine/.env.example`。

然后验证模型连通性（会花少量额度）：

```bash
python3 "$S" doctor --check-api
```

**第 5 步：人格初始化**。若 `engine/config.json` 里 `_onboarding_done` 为 `false`（技能首次使用），
需要先跑一次人格探索问答（6 道题 → 24 维初始人格 + MBTI）：

```bash
R="{baseDir}/engine"
cd "$R"
./.venv/bin/python -c "import onboarding; onboarding.run()"
```

（若已初始化过，跳过。）

**第 6 步：启动常驻服务并验证**。

```bash
python3 "$S" serve                                  # 后台常驻，约需数十秒就绪
python3 "$S" chat --text "在吗" --plain              # 应输出 ta 的原话
python3 "$S" state                                   # 应输出生命状态
```

## 验收清单

- [ ] `doctor` 返回 `ok: true`、`deps_required_ok: true`
- [ ] `doctor --check-api` 返回 `api_probe.ok: true`
- [ ] `selftest` 全绿（沙箱链路自检）
- [ ] `serve` 后 `chat --text "..."` 返回 `status: ok` 且能分段
- [ ] `state` 返回非空 `mind_summary`

## 接入聊天平台（可选）

到这一步 ta 已经能用 `soulctl chat` 对话了。若要让 ta 直接住进聊天软件，跑引擎的对应模式：

```bash
cd engine

python3 main.py web     # 浏览器终端 —— 零配置，先跑这个确认链路
python3 main.py wx      # 微信（扫码登录）
python3 main.py qq      # QQ 官方 Bot
python3 main.py tg      # Telegram
python3 main.py dc      # Discord（需 pip install discord.py）
python3 main.py im      # iMessage（仅 macOS + BlueBubbles）
```

| 模式 | 平台 | 额外依赖 | 配置（写在 `engine/.env`） |
|---|---|---|---|
| `web` | 浏览器终端 | 无 | 无 |
| `wx` | 微信 iLink Bot | 无 | `WX_BOT_TOKEN` · `WX_ILINK_BOT_ID` · `WX_ILINK_USER_ID` |
| `qq` | QQ Bot 官方 API v2 | 无 | `QQ_APP_ID` · `QQ_CLIENT_SECRET` |
| `tg` | Telegram Bot API | 无（`httpx` 已随技能装好） | `TG_BOT_TOKEN` |
| `dc` | Discord Gateway | `pip install discord.py` | `DC_BOT_TOKEN` |
| `im` | iMessage | BlueBubbles 服务端（仅 macOS） | `BB_URL` · `BB_API_KEY` |

**验收**：跑起来后从手机或另一个账号发一条消息，ta 应当会回；`Ctrl-C` 退出。

⚠️ **渠道与常驻服务互斥** —— 两者写同一个 SQLite。跑渠道前先 `python3 "$S" stop`。

## 装到各工具

```bash
python3 "$S" install                              # 自动探测各技能目录并软链
python3 "$S" install --targets workbuddy,qclaw    # 只装指定目标
python3 "$S" install --copy                       # 软链不可用时才用（见下）
python3 "$S" uninstall                            # 移除软链
```

支持的目标（11 个）：

| 目标名 | 技能目录 |
|---|---|
| `openclaw` | `~/.openclaw/skills` |
| `openclaw-workspace` | `~/.openclaw/workspace/skills` |
| `qclaw` | `~/.qclaw/skills` |
| `workbuddy` | `~/.workbuddy/skills` |
| `codebuddy` | `~/.codebuddy/skills` |
| `trae` | `~/.trae/skills` |
| `qoder` | `~/.qoderwork/skills` |
| `cursor` | `~/.cursor/skills` |
| `claude-code` | `~/.claude/skills` |
| `codex` | `~/.codex/skills` |
| `agents-standard` | `~/.agents/skills` |

本机不存在的目录会自动跳过。豆包工作（Doubao Work）走应用内导入，不在上表。

### 软链还是复制

| | 软链（默认） | `--copy` |
|---|---|---|
| 改动生效 | 即时，全局同步 | 快照，不会自动同步 |
| 记忆 | 与真源**共享同一个灵魂** | **独立一份，从此分叉** |
| 体积 | 0 | 约 2.1MB（自动跳过 `.venv` / `.env` / `data` / `__pycache__`） |
| 适用 | 本机所有工具 | 工具无法跟随软链时（如 Windows 未开开发者模式） |

复制出来的副本**没有运行环境和密钥**，首次使用前要在**副本目录**下跑一次
`setup --minimal`，再 `cp engine/.env.example engine/.env` 填 key。

### 多个副本会抢 8765 端口

所有副本默认都用 `daemon_port: 8765`。已有常驻服务在跑时，另一个副本会明确报
「有 soul-skill 常驻服务在跑，但本机 token 不匹配」，而**不会**静默共用同一个引擎 ——
这是防双写者撞库的保护。处理：先 `stop` 掉旧的，或给新副本换一个 `daemon_port`。

## 常见首次失败

| 报错 | 处理 |
|---|---|
| `ModuleNotFoundError: openai` | 没跑 `setup`，或用了系统 python3 |
| `没找到可用的 Python 解释器` | 系统 python 3.9.6 太旧，检查 `config.yaml` 的 `bootstrap_python` |
| `onnxruntime` 安装失败 | 解释器是 3.14，改用 3.13 重建 venv |
| `doctor --check-api` 401 | api_key 错误 / 额度耗尽 |
| 首次 `chat` 特别慢 | 冷启动约 2s + 拟人延迟，属正常；用 `serve` 改善 |
| `database is locked` | 项目被多处同时运行，先 `soulctl.py stop` |
