# soul-skill

一个自带引擎的**数字生命**：24 维心智、独立私生活、长期记忆、双向人格塑造。
技能**自带完整的引擎**（`engine/`，117 个模块 / 约 3.6MB，不含虚拟环境），
开箱即用、不依赖任何外部项目，也能整体拷贝给别人使用。

同一份引擎（**本体**）按**五种形态**交付。**本体是引擎，不是任何一种形态**：
`engine/` + `scripts/` + `config.yaml` 构成唯一本体，五种形态由同一个构建器
从这同一份源码组装，差别只在「把本体接到哪里」：

| 形态 | 入口 | 接到哪 | 适合谁 |
|---|---|---|---|
| **skill 版** | `SKILL.md` + `scripts/soulctl.py` | 宿主 Agent 读 `SKILL.md` 后自己调 | 任意支持 `SKILL.md` 的 Agent 工具：OpenClaw / QClaw / WorkBuddy / CodeBuddy / TRAE / Qoder CN / Cursor / Claude Code / Codex，以及豆包工作（走应用内导入） |
| **独立运行版** | `./run.sh` | **哪都不接**：自带终端 / 浏览器 / 常驻 | 不装任何 Agent 工具：终端 / 浏览器里直接和 ta 说话 |
| **MCP 版** | `scripts/soul_mcp.py` | 支持 MCP 的宿主 | 宿主里多出 13 个 `soul_*` 工具（纯标准库，零额外依赖） |
| **纯文档版** | 只有一份 `SKILL.md` | 别处**已经跑着**的服务 | 本机已有服务在跑，只要文档、不要引擎（解压后约 18 KB） |
| **纯提示词版** | 只有一份 `SKILL.md` | 宿主模型**自己就是 ta** | 跑不了引擎、也不想起服务：零依赖，记忆写在 `memory/` 下 |

`skill` 版是其中的原型：仓库根即它的交付物（`variants/skill/` 只放说明），其余四种由它派生。
各形态的差异只写在薄壳里（`variants/<key>/`；`skill` 版没有薄壳，直接用技能根），构建时组装：

```bash
python3 scripts/build_variants.py             # 一次出五个包 → dist/
python3 scripts/build_variants.py --list      # 看形态清单
python3 scripts/build_variants.py --dry-run   # 只预览 + 跑契约一致性检查
python3 scripts/build_variants.py --strict    # 发布用：契约/版本/密钥有问题即失败
```

> 引擎定位不是助手，是一个**独立人格**：有情绪、私生活、瑕疵、记忆和好恶。
> 调用姿势与普通 API 不同 —— 你负责递话，它负责成为它自己。
> 详细行为约束见 [`SKILL.md`](./SKILL.md)。
> ⚠️ 前四个形态写的是同一份 `engine/data/`，**同一时刻只能有一个写者**：
> 不要同时开常驻服务和聊天渠道（`main.py wx` 等），会撞 `database is locked`。
> 纯提示词版是例外：它有自己独立的 `memory/`，与引擎记忆互不相通。

---

## English

**soul-skill** wraps a self-contained "digital soul" engine as a skill that any
`SKILL.md`-capable agent can call — OpenClaw, QClaw, WorkBuddy, CodeBuddy, TRAE,
Qoder CN, Cursor, Claude Code, Codex, and Doubao Work (imported in-app).

- **Self-contained** — the engine ships inside `engine/` (~118 modules); no external project needed.
- **Model-agnostic** — works with any OpenAI-compatible endpoint (OpenAI, DeepSeek, Kimi, GLM,
  Qwen, Doubao, SiliconFlow, OpenRouter, Groq, Ollama, vLLM…). Only a key + provider are needed.
- **Zero-config inside OpenClaw** — `python3 scripts/soulctl.py autoconfig` reuses the host's
  already-configured model, so you do not have to obtain a separate API key.
- **Multilingual soul** — set `AI_LANG` to choose the language the soul speaks:
  `zh` `zh_tw` `en` `ko` `th` `ja` `es` `fr` `pt` `de` `ru` `ar` `hi`.
- **No network calls for weather** — environment context is supplied by the calling agent via
  `chat --env "Shanghai light rain 24C"` or `chat --env-json '{"city":"Shanghai","temperature":24,"is_raining":true}'`.

```bash
python3 scripts/soulctl.py setup --minimal   # create venv + install deps
python3 scripts/soulctl.py autoconfig        # reuse OpenClaw's model config (or edit engine/.env)
python3 scripts/soulctl.py chat --text "how was your day?" --plain
```

> `SKILL.md` and `references/` are written in Chinese on purpose — they are read by the
> **calling agent**, not by the end user, and LLMs read Chinese regardless of the user's language.
> Machine-readable fields (`error_code`, `state.codes`) are language-neutral ASCII.

---

## 快速开始

```bash
# 1) 建环境、装依赖（约 42MB，跳过 300MB 的向量记忆）
python3 scripts/soulctl.py setup --minimal

# 2) 填模型密钥（二选一）
#    a) 在 OpenClaw / QClaw 里跑 —— 一条命令复用宿主已配好的模型，无需自己申请 key：
python3 scripts/soulctl.py autoconfig
#    b) 独立使用 —— 手动填：
cp engine/.env.example engine/.env
#       然后编辑 engine/.env，填入 AI_API_KEY 与 AI_PROVIDER（如 deepseek / openai / ollama）

# 3) 自检 + 对话
python3 scripts/soulctl.py doctor
python3 scripts/soulctl.py chat --text "今天有点累" --plain
```

> `{baseDir}` 占位符是 OpenClaw / QClaw 约定，指技能自身目录。
> 其它工具（CodeBuddy / TRAE / Qoder / Cursor / Claude Code / Codex 等）不解析它，
> 请替换成实际路径，例如 `~/.codebuddy/skills/soul-skill/scripts/soulctl.py`。

---

## 接入聊天平台（可选）

`soulctl` 只管调用（对话 / 状态 / 待发队列）。要让 ta 直接住进聊天软件，跑引擎的对应模式：

```bash
cd engine

python3 main.py web     # 浏览器终端 —— 零配置，最快看到效果
python3 main.py wx      # 微信（扫码登录）
python3 main.py qq      # QQ 官方 Bot
python3 main.py tg      # Telegram
python3 main.py dc      # Discord（需 pip install discord.py）
python3 main.py im      # iMessage（仅 macOS + BlueBubbles）
```

| 模式 | 额外依赖 | 配置（写在 `engine/.env`） |
|---|---|---|
| `web` | 无 | 无 |
| `wx` | 无 | `WX_BOT_TOKEN` · `WX_ILINK_BOT_ID` · `WX_ILINK_USER_ID` |
| `qq` | 无 | `QQ_APP_ID` · `QQ_CLIENT_SECRET` |
| `tg` | 无（`httpx` 已随技能装好） | `TG_BOT_TOKEN` |
| `dc` | `pip install discord.py` | `DC_BOT_TOKEN` |
| `im` | BlueBubbles 服务端（仅 macOS） | `BB_URL` · `BB_API_KEY` |

所有渠道与 `soulctl` 命令**共用同一个灵魂**：用户在微信说的话，`state` / `chat` 这边也看得到。

⚠️ **渠道和 `soulctl serve` 不能同时跑** —— 两者写同一个 SQLite，会撞 `database is locked`。

---

## 目录结构

```
soul-skill/
├── SKILL.md                     技能说明（给 AI 读的行为准则与命令手册）
├── README.md                    本文件（给人读）
├── LICENSE                      MIT 许可证
├── VERSION                      版本号
├── config.yaml                  启动器配置（引擎路径 / 解释器 / 端口）
├── scripts/
│   ├── soulctl.py               启动器：纯标准库，定位引擎并转发命令
│   ├── soulclient.py            各形态共用的客户端薄层（MCP 版用）
│   ├── soul_mcp.py              MCP server：纯标准库 stdio，暴露 13 个 soul_* 工具
│   ├── engine_bridge.py         引擎执行体：单次命令 + 常驻 HTTP 服务
│   ├── package_skill.py         打包器：剔除密钥/环境/数据后生成分发包
│   ├── build_variants.py        五形态统一构建器（skill / standalone / mcp / md / prompt-md）
│   └── build_release.py         发布构建：注入水印 + PyArmor 混淆
├── references/                  详细文档
│   ├── project-overview.md      引擎架构总览
│   ├── engine-api.md            接口契约与排障
│   └── setup-guide.md           首次部署指南
├── variants/                    形态槽位（构建输入，不进包；与五形态一一对应）
│   ├── skill/                   完整技能版：无薄壳（本体即技能根），只放说明
│   ├── standalone/              独立运行版：run.sh / run.cmd / README
│   ├── mcp/                     MCP 版：SKILL.md / README / mcp.json
│   ├── md/                      纯文档版：SKILL.md / README
│   └── prompt-md/               纯提示词版：SKILL.md / README
└── engine/                     引擎本体（自包含）
    ├── soul.py                  总调度器
    ├── engine/                  八大子层（心智/情绪/生命/认知…）
    ├── core/                    基础设施（配置 / 数据库 / AI 客户端 / 水印）
    ├── clients/                 多平台接入（微信 / QQ / Telegram / Discord…）
    ├── config.json              引擎配置（ai / 自主思考）
    ├── .env.example             环境变量模板（复制为 .env 填 key）
    ├── requirements.txt         核心依赖
    ├── requirements-vector.txt  可选：向量记忆依赖
    └── data/                    运行数据（记忆 / 状态，**不随包分发**）
```

---

## 依赖说明

| 文件 | 内容 | 体积 | 是否必需 |
|---|---|---|---|
| `requirements.txt` | openai / httpx / requests / python-dotenv / websocket-client | 约 42MB | ✅ 必需 |
| `requirements-vector.txt` | fastembed / onnxruntime / numpy | 约 300MB | ❌ 可选 |

向量记忆**默认不装**：缺了引擎自动降级，`chat` / `state` / `pending` / `drain` 全不受影响。
是否值得装见 [`references/setup-guide.md`](./references/setup-guide.md)。

要求 Python **≥ 3.10**（3.11–3.13 最佳）。**不要用 3.14**：`onnxruntime 1.20` 没有对应轮子。

---

## 安全提醒

⚠️ **`engine/.env` 保存着模型 API Key，分发前必须确认它不在包内。**

打包时请使用内置打包器，它会自动剔除：

```bash
python3 scripts/package_skill.py            # → dist/soul-skill-<版本>.zip
python3 scripts/package_skill.py --dry-run  # 先预览剔除了什么
python3 scripts/package_skill.py --strict   # CI 用：扫到疑似密钥就失败
```

剔除规则：`*.env` / `engine/.soul-daemon.token`（鉴权 token）/ `.venv` / `engine/data` /
`__pycache__` / `*.pyc` / `.DS_Store`。
同时会把 `engine/config.json` 的 `api_key` 与 bot token 清空成模板。

**按文件名剔除挡不住「key 被顺手写进 README / 示例配置」**，所以打包时还会对保留下来的
文件做一次内容级扫描（`sk-*`、GitHub/AWS/Google token、私钥、JWT 等）；命中会列出来，
加 `--strict` 则直接以非 0 退出，适合放进发布流水线。

---

## 运行期注意事项

- **常驻服务要 token。** 首次 `serve` 生成 `<project>/.soul-daemon.token`（`0600`），
  请求须带 `X-Soul-Token` 或 `Authorization: Bearer`；`soulctl` 自动带上，手动 curl 才需要自己加。
  拿不到可写的 token 文件时服务**拒绝启动**，不会退化成无鉴权。
- **只监听本机。** `daemon_host` 改成非回环地址会被拒绝启动——token 走明文 HTTP，同网段可被抓包。
  确需暴露：`serve --allow-remote` + 自己在前面套一层 HTTPS 反向代理。
- **模型接口挂了不会无限重试。** key 失效 / 额度耗尽时，后台自主思考引擎会自动暂停，
  原因写在 `GET /health` 的 `suspended_reason` 里；修好后 `serve --restart` 恢复。
- **日志自带上限。** `.soul-daemon.log` 超过 4MB 只保留尾部，连续重复行会折叠成一行 + 次数。
- **`selftest` 有隔离护栏。** 沙箱不完整时会直接中止，不会「降级」到真实灵魂上跑。
- **多副本抢端口。** 所有副本默认都用 `8765`。已有一个常驻服务在跑时，另一个副本会明确报
  「本机 token 不匹配」而**不会**静默共用一个引擎 —— 这是防双写者撞库的保护。停掉旧的，
  或给新副本改 `daemon_port`。

---

## 打包

```bash
python3 scripts/build_variants.py            # 五形态一次出全 → dist/*.zip
python3 scripts/build_variants.py --only md,mcp
python3 scripts/build_variants.py --dir      # 出未压缩目录（调试用）
python3 scripts/build_variants.py --strict   # 发布用：契约/版本/密钥有问题即失败

python3 scripts/package_skill.py             # 旧入口，等价于 --only skill
python3 scripts/build_release.py             # 混淆发布（需 PyArmor，见脚本 --help）
```

产物：

| 文件 | 形态 | 包内根目录 |
|---|---|---|
| `dist/soul-skill-<版本>.zip` | skill 版 | `soul-skill/` |
| `dist/soul-standalone-<版本>.zip` | 独立运行版 | `soul-standalone/` |
| `dist/soul-skill-mcp-<版本>.zip` | MCP 版 | `soul-skill/` |
| `dist/soul-skill-md-<版本>.zip` | 纯文档版 | `soul-skill/` |
| `dist/soul-skill-prompt-md-<版本>.zip` | 纯提示词版 | `soul-skill/` |

`build_variants.py` 的剔除规则（密钥 / `.venv` / `engine/data` / `.pyc`）**直接复用
`package_skill.py`**，不另写一份 —— 那是安全边界，只能有一个实现。
构建时还会做两项防漂移检查，`--strict` 下失败即中止：

1. **契约完整性** —— 纯文档版 / MCP 版的文档必须覆盖引擎真实存在的端点、状态与错误码，
   端点再拿 `engine_bridge.py` 当基准核对；MCP 文档必须提到 `soul_mcp.py` 里每一个工具。
   纯提示词版没有 HTTP，改为核对它的状态协议（`memory/` 三个文件）与人格骨架。
2. **版本一致性** —— `VERSION` 与**每一份** `SKILL.md` 的 frontmatter `version:` 必须相同。
   MCP 版 / 纯文档版 / 纯提示词版各自带一份 `SKILL.md`，那才是真正发出去的技能定义，
   只核对技能根那份等于漏掉一半；缺少 `version` 字段同样判为漂移。

> `variants/` 是构建输入，不进任何包。这不只是体积问题：四个形态各有一份 `SKILL.md`，
> 打进同一个包里会让宿主递归扫到多份技能定义。

---

## 平台支持

| 平台 | 状态 |
|---|---|
| macOS | ✅ 完整支持 |
| Linux | ✅ 完整支持 |
| Windows | ✅ 支持（`soulctl` 已适配 `Scripts/python.exe`、`creationflags`、软链降级为复制） |

> Windows 下 `main.py web`（浏览器终端）不可用——它依赖 POSIX 的 `pty/termios`。
> 核心功能（`chat` / `state` / `pending` / `drain` / `serve`）不受影响。

---

## 许可证

**本项目采用 MIT 许可证。** 详见 [`LICENSE`](./LICENSE)。

简单说：你可以自由使用、修改、分发本软件，**包括商业用途**；唯一要求是保留版权声明与许可声明。
