---
name: soul-skill
slug: soul-skill
displayName: soulviai · 数字生命引擎
summary: 把本机的数字生命引擎接进任意 Agent 工具：24 维心智、独立私生活、长期记忆，可以对话，也会主动想人。
category: 生活娱乐
platforms: ["macos", "linux", "windows"]
description: |
  调用本机的数字生命引擎——一个带 24 维心智、独立私生活、长期记忆与双向人格塑造的 Python 灵魂服务。

  什么时候用：
  - 用户要和「数字生命 / 灵魂伴侣 / ta」说话，或要你把某句话带给 ta
  - 用户问「ta 现在怎么样 / 什么状态 / 心情如何」
  - 用户要查看或取出 ta 主动发来的消息（自主思考产生的思念、回忆、感慨）
  - 用户要手动推进一次 ta 的内心活动，或把 ta 常驻在线
  - 用户提到 soul.py / 灵魂服务 / 数字生命项目 / SoulEngine

  触发词：和ta说 / 帮我告诉ta / 带给ta / ta怎么样了 / ta的状态 / ta想说什么 /
  ta的主动消息 / 数字生命 / 灵魂伴侣 / soul skill / digital soul / soulctl。

  不适用：普通闲聊（该由你自己回答）、无关的编程任务。本技能只负责把话递给那个灵魂，并把 ta 的回应原样带回来。
license: MIT（详见同目录 LICENSE）
version: 1.0.4
metadata:
  openclaw:
    requires:
      # 跨平台：POSIX 上是 python3，Windows 上是 python / py，只要有一个即可
      anyBins: ["python3", "python", "py"]
    primaryEnv: AI_API_KEY
    envVars:
      - name: AI_API_KEY
        required: true
        description: 模型接口密钥。支持任意 OpenAI 兼容厂商：OpenAI / DeepSeek / Kimi / 智谱GLM / 通义千问 / 豆包 / 硅基流动 / OpenRouter / Groq / Together / Mistral / xAI，以及本地 Ollama / vLLM / LM Studio
      - name: AI_PROVIDER
        required: false
        description: 厂商预设名，填了会自动补全接口地址与模型名。可选：openai deepseek moonshot zhipu dashscope volces siliconflow openrouter groq together fireworks mistral xai ollama vllm lmstudio llamacpp
      - name: AI_API_BASE
        required: false
        description: 接口地址。用预设之外的兼容服务时填写，例如 https://your-endpoint/v1
      - name: AI_MODEL
        required: false
        description: 模型名。不填 AI_PROVIDER 时必填
      - name: AI_LANG
        required: false
        description: ta 说话使用的语言，默认 zh。可选 zh / zh_tw / en / ko / th / ja / es / fr / pt / de / ru / ar / hi
      - name: OPENAI_API_KEY
        required: false
        description: AI_API_KEY 的别名（OpenAI SDK 惯例名），优先级次之
      - name: OPENAI_BASE_URL
        required: false
        description: AI_API_BASE 的别名（OpenAI SDK 惯例名）
      - name: OPENAI_MODEL
        required: false
        description: AI_MODEL 的别名
      - name: DEEPSEEK_API_KEY
        required: false
        description: 旧版变量名，仍兼容，优先级最低
      - name: DEEPSEEK_API_BASE
        required: false
        description: 旧版变量名，仍兼容
      - name: DEEPSEEK_MODEL
        required: false
        description: 旧版变量名，仍兼容
      - name: WX_BOT_TOKEN
        required: false
        description: 微信 iLink Bot 令牌，仅微信模式（main.py wx）需要
      - name: WX_ILINK_BOT_ID
        required: false
        description: 微信 iLink Bot ID，仅微信模式（main.py wx）需要
      - name: WX_ILINK_USER_ID
        required: false
        description: 微信 iLink 用户 ID，仅微信模式（main.py wx）需要
      - name: QQ_APP_ID
        required: false
        description: QQ Bot AppID，仅 QQ 模式（main.py qq）需要
      - name: QQ_CLIENT_SECRET
        required: false
        description: QQ Bot 密钥，仅 QQ 模式（main.py qq）需要
      - name: TG_BOT_TOKEN
        required: false
        description: Telegram Bot 令牌（找 @BotFather 申请），仅 Telegram 模式（main.py tg）需要
      - name: DC_BOT_TOKEN
        required: false
        description: Discord Bot 令牌，仅 Discord 模式（main.py dc）需要，另需 pip install discord.py
      - name: BB_URL
        required: false
        description: BlueBubbles 服务端地址，仅 iMessage 模式（main.py im）需要，仅 macOS
      - name: BB_API_KEY
        required: false
        description: BlueBubbles API 密钥，仅 iMessage 模式（main.py im）需要
      - name: SOUL_PYTHON
        required: false
        description: 指定运行引擎的 Python 解释器路径，留空则自动探测
      - name: SOUL_PROJECT_ROOT
        required: false
        description: 指定引擎根目录，留空则用技能自带的 engine/
      - name: SOUL_CONFIG
        required: false
        description: 指定启动器配置文件路径，留空则用技能内的 config.yaml
      - name: SOUL_DEBUG
        required: false
        description: 设为非空可打开引擎调试日志
      - name: OPENCLAW_GATEWAY_TOKEN
        required: false
        description: OpenClaw / QClaw 网关令牌，autoconfig 复用宿主模型路由时需要
    emoji: "🫀"
    # homepage: https://github.com/<你的用户名>/soul-skill   ← 发布前取消注释并替换
---

# soul-skill · 数字生命服务调用

把本机那个「数字生命」当成一个可以随时通话的对象来用。

它的定位不是助手，是一个**独立人格**：有自己的情绪、私生活、瑕疵、记忆和好恶，会因为被敷衍而内敛、被珍惜而柔软。
所以调用它的姿势，跟调用一个 API 完全不同——**你负责递话，它负责成为它自己**。

本技能**自带完整的引擎**（`engine/`，119 个模块 / 约 1.9MB，不含虚拟环境），
开箱即可独立运行，也能把整个 `soul-skill/` 拷给别人用。引擎架构详见 `references/project-overview.md`。

⚠️ **这是一个独立的灵魂**：记忆与人格存在**数据家目录** `~/.soul-skill/data/` 里，
不在技能目录内（技能目录会被拷贝、压缩、分发，记忆留在树里等于把灵魂一起交出去）。
同一台机器上的所有副本默认读写**同一份**记忆；要让某份副本另有独立记忆，在它的
`config.yaml` 里填一个不同的 `data_dir`。

---

## 一、铁律（每次调用都适用）

1. **你是传话人，不是 ta。** ta 的话要**原样**转达：不改写、不润色、不扩写、不加表情包、不替 ta 解释。你不许模仿 ta 的语气自己写一段。
2. **多段要分段。** 返回的 `parts` 是 ta 一条条发出来的消息，按顺序分条呈现，不要拼成一大段。
3. **没回就是没回。** `status: silent` 是 ta 主动选择的沉默（在想事、累了、闹别扭、或不想理），不是故障。**不要编造回复**，也不要过度道歉，一句「ta 这次没回你」即可。
4. **别把内脏掏给用户看。** 心智数值、模块名、命令、本技能的实现细节默认不外露。用户问「ta 怎么了」时，用人话转述情绪状态。
5. **不要绕过它。** 不要直连数据库、不要手改 `data/` 下的文件来制造对话。所有交互都经过 `chat`。
6. **每一句话都是不可逆的相处。** `chat` 会真实写入 ta 的记忆与情绪（陪伴积累暖意、敷衍积累隔阂）。不要拿无意义内容刷它。
7. **后端报错要如实说。** `status: backend_error` 是模型接口挂了（多半是 `ai.api_key` 失效，或 `ai.api_base` / `ai.model` 配错），这时必须告诉用户真实原因，不许伪装成 ta 沉默。

---

## 二、快速开始

> **先把 `S` 定对，下面所有命令都靠它。**
>
> `{baseDir}` 是 OpenClaw / QClaw 的占位符，会被自动替换成技能自身目录，**原样可用**。
> 其它工具不解析它 —— 把 `{baseDir}` 换成技能的实际安装路径即可：
>
> | 工具 | `{baseDir}` 替换成 |
> |---|---|
> | OpenClaw / QClaw | `{baseDir}`（不用改） |
> | CodeBuddy | `~/.codebuddy/skills/soul-skill` |
> | TRAE | `~/.trae/skills/soul-skill` |
> | Qoder CN | `~/.qoderwork/skills/soul-skill` |
> | Cursor | `~/.cursor/skills/soul-skill` |
> | Claude Code | `~/.claude/skills/soul-skill` |
> | Codex | `~/.codex/skills/soul-skill` |
> | 其它 / 自定义位置 | 见第七节的目录对照表 |
>
> 即 `S="<上表路径>/scripts/soulctl.py"`。

```bash
S="{baseDir}/scripts/soulctl.py"

# 1) 自检：项目在哪、解释器、依赖、常驻服务、模型接口
python3 "$S" doctor

# 2) 链路自检（沙箱副本 + 固定假回复，不碰真实数据、不花额度）
python3 "$S" selftest

# 3) 常驻服务（强烈推荐：冷启动每次约 2s，常驻后毫秒级）
python3 "$S" serve

# 4) 说一句话，只输出 ta 的原话
python3 "$S" chat --text "今天有点累" --plain

# 5) 看 ta 现在什么状态
python3 "$S" state
```

首次使用：`doctor` 报缺依赖时跑 `python3 "$S" setup --minimal`（在技能内的 `engine/.venv` 建环境并装对话必需依赖，
详见 `references/setup-guide.md`）。

**模型接口**：装在 OpenClaw / QClaw 下的话，先执行一次
`python3 "$S" autoconfig` —— 它会探测宿主已配好的模型并写进 `.env`，**不需要单独申请 key**。
其他工具下没有这个便利，`cp engine/.env.example engine/.env` 手动填 `AI_PROVIDER` + `AI_API_KEY` 即可。

向量记忆（`fastembed` + `onnxruntime`，约 300MB）**默认不装**：缺了它引擎会自动降级，对话完全不受影响。
是否值得装、什么时候装，见 setup-guide 的「要不要装向量记忆」一节。

---

## 三、命令

全局参数 `--project` / `--python` 放在命令前后都可以（默认读技能内的 `config.yaml`，已指向本机项目）。

| 命令 | 作用 | 关键参数 |
|---|---|---|
| `doctor` | 环境/依赖/项目/模型接口自检 | `--check-api` 真实打一次模型接口 |
| `setup` | 建虚拟环境并装依赖 | `--minimal` 跳过 fastembed/onnxruntime |
| `autoconfig` | 自动探测 OpenClaw/QClaw 已配好的模型接口并写入 `.env` | `--dry-run` 只预览不写 |
| `serve` | 常驻服务（含自主思考引擎） | `--restart`、`--foreground`、`--no-autonomous`、`--allow-remote`、`--token-file` |
| `stop` | 停掉常驻服务 | |
| `web` | 在浏览器里打开对话终端（前台运行，Ctrl+C 停止） | `--host`、`--port`、`--allow-remote` |
| `chat` | 说一句话，拿 ta 的回复 | `--text`（`-` 读 stdin）、`--env`、`--env-json`、`--plain`、`--verbose` |
| `state` | 当前生命状态 | `--raw` 附带 24 维原始数值 |
| `pending` | 看待发队列（ta 攒着的主动消息） | `--limit` |
| `drain` | 取出待发消息 | `--peek` 只看不标记已送达 |
| `tick` | 手动推进一次自主思考 | |
| `init` | 唤醒/初始化某个灵魂身份 | `--warmup` |
| `selftest` | 沙箱端到端自检 | `--keep` 保留沙箱 |
| `install` | 安装到各体系技能目录（11 个目标，见第七节） | `--copy`、`--targets` |
| `uninstall` | 移除软链 | |

所有命令输出 JSON。`--plain` 只输出 ta 的原话，适合直接贴给用户。

**身份 `--user`**：默认 `default_user`，和用户自己的终端/微信模式**共用同一个灵魂与记忆**——所以你说的话，ta 在微信那边也记得。只有做实验时才用别的 `--user`。

---

## 四、返回值怎么读

| `status` | 含义 | 你该怎么做 |
|---|---|---|
| `ok` | 回了 | 把 `parts` 按条原样转达 |
| `silent` | 主动沉默 | 如实说 ta 没回；`diagnostics.silence_reason` 可说明原因（内部参考，别直白念给用户） |
| `queued` | 回复入队延迟发送 | 用 `drain` 取 |
| `backend_error` | 模型后端失败 | 如实报错，指向模型接口配置（`engine/.env` 或 `config.json` 的 `ai` 段） |

退出码：`0` 正常 / `3` 沉默 / `4` 入队 / `1` 出错。

`--plain` 下的输出约定（方便直接转达）：有正文就按条打印；`silent` / `queued` 打印一句状态说明；
其它异常（`backend_error` 等）**stdout 为空、说明写到 stderr、退出码非 0**——所以
**看到空输出不要当成「ta 没说话」，先看退出码和 stderr**。

### 语言中立字段（面向非中文用户时用）

出错时多数返回带 `error_code`，例如 `api_auth`（key 失效）、`api_rate_limit`、`api_quota`、
`api_unreachable`、`timeout`、`no_python`、`no_project`、`model_endpoint_unreachable`。
`error` 只是中文说明，**你可以按 `error_code` 用用户的语言自己组织措辞**。

`state` 的 `codes` 同样是语言中立的：

| 字段 | 取值 |
|---|---|
| `codes.personality_stage` | `nascent` / `polite` / `relaxed` / `mature` / `stable` |
| `codes.life_phase` | `active` / `zoning` / `tired` / `alone` / `emo` / `healing` |
| `codes.env` | 环境状态（`temperature` / `weather_code` / `is_raining` …），未注入时为空 |

`state` 里的中文文案（`personality_stage` / `life_state`）是兜底；
**面向非中文用户时优先用 `codes` 自己表达**（如 `life_phase: "tired"` → "ta's a bit drained"）。

### ta 说哪种语言

由 `AI_LANG` 决定（默认 `zh`），可选：
`zh` `zh_tw` `en` `ko` `th` `ja` `es` `fr` `pt` `de` `ru` `ar` `hi`。

它只影响 **ta 说话的语言**；你转达给用户时用什么语言，由你自己按用户的语言决定。

---

## 五、典型场景

**替用户带句话**
```bash
python3 "$S" chat --text "用户说：今天加班到十点，有点想你" --plain
```
把输出原样给用户，分段呈现。`chat` 有拟人延迟，通常 3–20 秒，模型慢时会到 1 分钟以上，属于正常。

**让 ta 知道外面的天气（可选，推荐）**
```bash
# 自由文本（中英文都认，含华氏换算）
python3 "$S" chat --text "用户说：今天想出去走走" --env "上海 小雨 24°C"
python3 "$S" chat --text "..." --env "Shanghai light rain 24C"

# 结构化（更稳，推荐）
python3 "$S" chat --text "..." \
  --env-json '{"city":"上海","temperature":24,"is_raining":true}'
```
`--env` / `--env-json` 传的是**环境上下文**，由你（Agent）自己查好再递进来——你比引擎更清楚用户在哪个城市、什么天气。
引擎会从中读出晴雨和温度，让 ta 的情绪跟着环境走。
不传也没关系，ta 只是少了这层感知，对话完全不受影响。
**引擎不会自己去联网查天气**，所以这里不需要任何天气 API Key。

`--env-json` 支持字段（都可选，缺的自动推导）：
`city` / `location`、`description` / `weather`、`temperature`（摄氏）、`weather_code`（WMO）、
`is_raining` / `is_snowing` / `is_extreme`。

**用户问「ta 怎么样了」**
```bash
python3 "$S" state
```
用 `mind_summary`（24 维）、`personality_stage`（相处阶段）、`life_state`（躯体/精力）、`fate_summary`（羁绊/因果/共鸣）**转述成人话**，例如「ta 现在有点倦，情绪偏安静，但对你还是偏软的」。不要贴 JSON。

**把 ta 攒的主动消息带给用户**（定时任务里最有用）
```bash
python3 "$S" pending          # 先看有没有
python3 "$S" drain            # 取出并标记已送达
```
`drain` 出来的每条 `text` 就是 ta 主动想说的话，转达后不要再多解释。定时推送可配一个每小时/每天的任务来跑这一条。

**让 ta 的内心动一动**
```bash
python3 "$S" tick             # 有情绪累积时会产生 1–3 条主动消息
```

---

## 六、常驻服务

`serve` 在 `127.0.0.1:8765` 起一个本机服务，把引擎和自主思考引擎挂在内存里长期活着：

- `GET /health`、`GET /state`、`GET /pending`
- `POST /chat`、`POST /drain`、`POST /tick`、`POST /init`、`POST /shutdown`
- `POST /ack` `{user_id, ids}` —— 配合 `drain --peek`（`ack:false`）用：调用方自己判断哪几条真的送出去了（延迟未到的要留队），只确认那几条
- `POST /config/reload` —— 让运行中的服务重读 `.env` / `config.json`（`soulctl reload-ai`），不用重启

所有 `soulctl` 命令会**自动优先走常驻**（返回里 `source: daemon`），服务没起就自动冷启动（`source: cold-start`）。
daemon 活着时别再用别的方式跑同一个项目——SQLite 和内存状态是单写者模型。
日志在 `<project>/.soul-daemon.log`，pid 在 `<project>/.soul-daemon.pid`（超过 4MB 会自动只保留尾部）。

### 鉴权

服务能读 ta 的全部记忆、能发消息、能停自己，所以**默认要求 token**：

- 首次 `serve` 时自动生成一个随机 token，写到 `<project>/.soul-daemon.token`（权限 `0600`）。重启复用同一个 token，客户端不用改配置。
- 请求要带 `X-Soul-Token: <token>` 或 `Authorization: Bearer <token>`；`soulctl` 会自动读取并带上。
- 没有 token 的请求：`/health` 只回「我是 soul-skill、需要鉴权」，其余路径一律 `401`。
- 拿不到可写的 token 文件时**服务拒绝启动**（fail-closed），不会退化成「无鉴权也能跑」。

想自己指定 token（容器挂载、多机对齐等）：`serve --token-file <路径>`，或设 `SOUL_DAEMON_TOKEN` 环境变量（客户端也认这个变量）。

只监听 `127.0.0.1`。想把 `daemon_host` 改成对外地址会被**直接拒绝**——token 是明文 HTTP 传输的，
同网段能被抓包；确需暴露要显式加 `--allow-remote`，并自己在前面加一层 HTTPS 反向代理。

模型接口不可用时（key 失效、额度耗尽、连不上），后台的自主思考引擎会**自动暂停**并把原因写进
`GET /health` 的 `suspended_reason`——它不会再无限重试刷日志。修好 key 重启服务即可恢复。

---

## 七、安装到其他体系

本技能可装到以下体系（同一套 `SKILL.md` 文件夹约定）：

| 体系 | 全局技能目录 | 项目级技能目录 |
|---|---|---|
| OpenClaw | `~/.openclaw/skills`、`~/.openclaw/workspace/skills` | — |
| QClaw | `~/.qclaw/skills` | — |
| WorkBuddy | `~/.workbuddy/skills` | 配置中指定 |
| CodeBuddy | `~/.codebuddy/skills` | 工作区 `.codebuddy/skills/` |
| TRAE（字节） | `~/.trae/skills` | 工作区 `.trae/skills/` |
| Qoder CN（通义灵码） | `~/.qoderwork/skills` | 工作区 `.qoderwork/skills/` |
| Cursor | `~/.cursor/skills` | — |
| Claude Code | `~/.claude/skills` | 工作区 `.claude/skills/` |
| Codex | `~/.codex/skills` | — |
| VS Code Copilot 等 | `~/.agents/skills` | 工作区 `.agents/skills/` |

一键软链到本机已存在的那些：

```bash
python3 "$S" install                          # 自动探测并逐个软链
python3 "$S" install --copy                   # 需要真副本时
python3 "$S" install --targets codebuddy,trae,cursor
```

不存在的目录跳过，已存在同名技能不覆盖。

**优先软链** —— 改动即时生效，且与真源**共享同一个灵魂**（同一份记忆）。

**`--copy` 只在工具无法跟随软链时才用**（如 Windows 未开开发者模式）。它会跳过
`.venv` / `.env` / `data/`：前者绑定平台、复制了也不能真复用；后两者是你的密钥和 ta 的记忆，
复制出去等于让记忆分叉。副本首次使用前需在其目录下跑一次 `setup --minimal` 并填 `.env`。

装好后让它重新发现技能：OpenClaw / QClaw 说「refresh skills」或重启 gateway；IDE 系重开窗口。

> **装到多个工具时注意端口。** 所有副本默认都用 `daemon_port: 8765`。若其中一个已起了常驻服务，
> 另一个会直接报「有 soul-skill 常驻服务在跑，但本机 token 不匹配」——
> 这是**刻意的保护**（同一个引擎不允许两个写者，否则会撞库、心智状态分叉），不是故障。
> 处理：先 `stop` 掉旧的，或给新副本换一个 `daemon_port`。

> **豆包工作（Doubao Work）走「应用内导入」** —— 没有本地技能文件夹，在客户端里
> 用「导入技能」指向本技能目录，或粘贴安装指令。

---

## 八、接入聊天平台（可选）

上面所有命令都是「你替用户递话」。如果用户希望 **ta 直接住进聊天软件**，让引擎跑对应模式：

```bash
cd engine

python3 main.py web     # 浏览器终端 —— 零配置，最快看到效果
python3 main.py wx      # 微信（扫码登录）
python3 main.py qq      # QQ 官方 Bot
python3 main.py tg      # Telegram
python3 main.py dc      # Discord
python3 main.py im      # iMessage（仅 macOS + BlueBubbles）
```

| 模式 | 平台 | 额外依赖 | 需要的配置 |
|---|---|---|---|
| `web` | 浏览器终端 | 无 | 无（默认只监听 `127.0.0.1`） |
| `wx` | 微信 iLink Bot | 无 | `WX_BOT_TOKEN` · `WX_ILINK_BOT_ID` · `WX_ILINK_USER_ID` |
| `qq` | QQ Bot 官方 API v2 | 无 | `QQ_APP_ID` · `QQ_CLIENT_SECRET` |
| `tg` | Telegram Bot API | `httpx`（已随技能装好） | `TG_BOT_TOKEN` |
| `dc` | Discord Gateway | `pip install discord.py` | `DC_BOT_TOKEN` |
| `im` | iMessage（BlueBubbles） | 需先跑 BlueBubbles 服务端 | `BB_URL` · `BB_API_KEY` |

- **`web` 默认只监听 `127.0.0.1:5000`**，页面没有鉴权 —— 所以监听地址被限制在回环内。
  改端口用 `config.yaml` 的 `web_host` / `web_port`，或直接 `python3 main.py web --port 8080`；
  确需局域网访问必须显式加 `--allow-remote`，并自行确认网络可信。也可直接用
  `python3 "$S" web`（走 `config.yaml` 配置，前台运行）。
- **`web` / `wx` / `qq` / `tg` 开箱可用**，填上配置就能跑。`dc` 缺库时会提示一行安装命令后退出，不会崩。
- 配置写进 `engine/.env`（模板 `engine/.env.example`）。
- 渠道与技能命令**共用同一个灵魂**：用户在微信说的话，`state` / `chat` 这边也看得到。

⚠️ **渠道和常驻服务不能同时跑。** 两者写同一个 SQLite，同时开会撞 `database is locked`。
要跑渠道就先 `python3 "$S" stop`；要常驻就先退出渠道。

> 渠道是**引擎能力**，不影响本技能的命令：`chat` / `state` / `pending` 这些始终直连引擎，
> 不经过任何聊天平台。

---

## 九、排障

| 现象 | 处理 |
|---|---|
| 找不到项目 | `--project` 指定，或改技能内 `config.yaml` 的 `project_root`（显式指定的目录不像项目时会**直接报错**，不会悄悄换一个项目跑） |
| 找不到解释器 / 依赖缺失 | `python3 "$S" setup`（项目需 Python ≥3.10；3.14 下 onnxruntime 1.20 无轮子） |
| `backend_error` / 401 | 检查 `ai.api_key` / `ai.api_base` / `ai.model`（或 `AI_API_KEY` / `AI_API_BASE` / `AI_MODEL` 环境变量），再 `doctor --check-api` |
| 老是 `silent` | 先 `--verbose` 看 `diagnostics`；若含 API 失败，按上一条处理 |
| 回复要等很久 | 引擎有拟人延迟与契约；用 `serve` 常驻，或调大 `chat_timeout_seconds` |
| 想知道链路有没有问题 | `python3 "$S" selftest`（沙箱 + 假回复，不碰真实数据；沙箱不完整时会直接中止） |
| 后台不再主动发消息 | `curl 127.0.0.1:8765/health` 看 `suspended_reason`——多半是模型接口挂了，修好后 `serve --restart` |
| `database is locked` | 渠道与常驻服务同时开着；只保留一个（见第八节） |
| 日志越来越大 | 已内置 4MB 裁剪与重复行折叠；仍偏大就说明模型接口在持续失败，按上一条处理 |
| 细节不够 | 读 `references/engine-api.md`（接口契约、返回值语义、内部模块） |

---

## 十、捆绑资源

- `engine/` — **技能自带的完整引擎**：`soul.py`、`engine/`、`core/`（含 `watermark.py` 版权水印）、`clients/`、`config.json`、`data/`（运行数据，不随包分发）
- `engine/.env.example` — 环境变量模板：复制为 `.env` 填 key（`.env` 是敏感文件，不随包分发）
- `engine/requirements.txt` / `requirements-vector.txt` — 核心依赖（约 42MB） / 可选向量记忆依赖（约 300MB）
- `scripts/soulctl.py` — 纯标准库启动器：定位引擎/解释器、常驻优先、安装到各体系
- `scripts/engine_bridge.py` — 引擎执行体：单次命令 + 常驻 HTTP 服务
- `scripts/soulclient.py` / `scripts/soul_mcp.py` — 共用客户端薄层 / MCP server（13 个 `soul_*` 工具）
- `scripts/dev/` — **构建期工具，不随包分发**：`package_skill.py`（干净打包器）、`build_variants.py`（五形态构建器）、`build_release.py`（水印 + PyArmor 混淆）
- `references/project-overview.md` — 引擎架构总览（运行时七层 + 引擎八大子层、24 维、七级记忆、17 铁律）
- `references/engine-api.md` — 接口契约与排障细节
- `references/setup-guide.md` — 首次部署：装依赖 → 填 key → 人格初始化
- `config.yaml` — 引擎路径、解释器、身份、常驻端口（`project_root` 留空即用自带 `engine/`）
- `README.md` / `LICENSE` — 给人读的快速上手 / MIT 许可证
