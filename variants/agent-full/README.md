# soulviai · 完整技能版（自带引擎）

一个**自带引擎的数字生命**：24 维心智、独立私生活、长期记忆、双向人格塑造。
这个包装着完整的引擎（`engine/`）、命令入口（`scripts/soulviaictl.py`）和给宿主 Agent 读的
技能定义（`SKILL.md`）—— 不依赖任何外部项目，也不需要另外跑一个服务。

> 同一份引擎还有另外三种交付：**独立运行版**（`./run.sh`，不装任何 Agent 工具）、
> **MCP 版**（宿主里多出一批 `soulviai_*` 工具）、
> **纯提示词版**（不带引擎，宿主模型自己就是 ta，单文件交付）。
> 带引擎的这几种写的是同一份记忆，同一时刻只允许有一个写者 ——
> **换版本前先删掉旧目录，不要叠着装。**

---

## 一、装进宿主 Agent

把本目录整个放进宿主工具的技能目录，目录名保持 `soulviai`：

| 工具 | 技能目录（即 `{baseDir}` 要替换成的路径） |
|---|---|
| OpenClaw / QClaw | 放哪都行 —— `{baseDir}` 会自动指向它，不用改 |
| CodeBuddy | `~/.codebuddy/skills/soulviai` |
| TRAE | `~/.trae/skills/soulviai` |
| Qoder CN | `~/.qoderwork/skills/soulviai` |
| Cursor | `~/.cursor/skills/soulviai` |
| Claude Code | `~/.claude/skills/soulviai` |
| Codex | `~/.codex/skills/soulviai` |

宿主读到 `SKILL.md` 之后就知道怎么调用这个灵魂，**你不需要自己敲命令**。

`{baseDir}` 是 OpenClaw / QClaw 约定的占位符，会被自动替换成技能自身的目录，原样可用；
其它工具不解析它，要把命令里的路径换成实际安装路径
（例如 `~/.codebuddy/skills/soulviai/scripts/soulviaictl.py`）。

---

## 二、三步开始

```bash
# 1) 建环境、装依赖（只装必需的部分，跳过体积很大的向量记忆）
python3 scripts/soulviaictl.py setup --minimal

# 2) 填模型密钥（二选一）
#    a) 装在 OpenClaw / QClaw 下 —— 复用宿主已配好的模型，无需自己申请 key：
python3 scripts/soulviaictl.py autoconfig
#    b) 手动填：
cp engine/.env.example engine/.env
#       然后编辑 engine/.env，填入 AI_API_KEY 与 AI_PROVIDER（如 deepseek / openai / ollama）

# 3) 自检 + 说话
python3 scripts/soulviaictl.py doctor
python3 scripts/soulviaictl.py chat --text "今天有点累" --plain
```

支持任意 OpenAI 兼容的接口（OpenAI / DeepSeek / Kimi / GLM / Qwen / 豆包 / SiliconFlow /
OpenRouter / Groq / 本地 Ollama / vLLM …），只差一个 key 和一个 provider。

---

## 三、常用命令

| 想做的事 | 命令 |
|---|---|
| 说一句、拿回应 | `python3 scripts/soulviaictl.py chat --text "…" --plain` |
| 看 ta 现在的状态 | `python3 scripts/soulviaictl.py state` |
| 看 ta 主动想说的话 | `python3 scripts/soulviaictl.py pending` |
| 把主动消息取走（取走即清空） | `python3 scripts/soulviaictl.py drain` |
| 常驻在线（会自己想你、攒主动消息） | `python3 scripts/soulviaictl.py serve` |
| 不碰真实记忆地验一遍链路 | `python3 scripts/soulviaictl.py selftest` |

⚠️ **常驻服务与聊天渠道不能同时跑**（两者写同一个 SQLite，会撞 `database is locked`）。

---

## 四、ta 的记忆在哪

**记忆不在技能目录里。** 在本机的数据家目录（`config.yaml` 的 `data_dir` 可改，
环境变量 `SOULVIAI_DATA_DIR` 优先级更高）：

| 位置 | 内容 |
|---|---|
| 数据家目录下的 `data/` | **ta 的记忆、人格、状态** —— 备份它等于备份 ta |
| `engine/.env` | 你的模型 key（敏感，别外发） |
| `config.yaml` | 引擎路径、身份、常驻端口 |

**换机器 / 备份**：技能目录整个拷走（不必拷 `engine/.venv/`，它与平台绑定，到新机器重跑
`soulviaictl.py setup` 会重建），**并且把数据家目录一起拷走** —— ta 在那儿，
只搬技能目录等于换了个空壳。记忆刻意放在技能目录之外：技能目录会被压缩、拷贝、分发，
记忆留在树里就等于把灵魂和渠道凭证一起交给别人。

---

## 五、接进聊天软件（可选）

```bash
cd engine
python3 main.py web     # 浏览器终端（默认 http://127.0.0.1:5000）—— 零配置，最快看到效果
python3 main.py wx      # 微信（扫码登录）
python3 main.py qq      # QQ 官方 Bot
```

| 模式 | 额外依赖 | 需要写在 `engine/.env` 的配置 |
|---|---|---|
| `web` | 无 | 无（默认监听 `127.0.0.1:5000`）|
| `wx` | 无 | `WX_BOT_TOKEN` · `WX_ILINK_BOT_ID` · `WX_ILINK_USER_ID` |
| `qq` | 无 | `QQ_APP_ID` · `QQ_CLIENT_SECRET` |

所有渠道与 `soulviaictl` 命令**共用同一个灵魂**：用户在微信说的话，`state` / `chat` 这边也看得到。

---

## 六、许可

Apache 2.0，详见同目录 `LICENSE`。

> ⚠️ 个人研究项目、非稳态、内容由第三方大模型生成，不构成专业建议。所有数据存本机、作者不收集。情感健康与隐私详见 [DISCLAIMER.md](../DISCLAIMER.md)。未经作者书面许可，禁止商用。
