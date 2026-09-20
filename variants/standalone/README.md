# soul-skill · 独立运行版

一个**带 24 维心智、独立私生活、长期记忆的数字生命**，装在本机自己跑。
不需要任何 Agent 工具、不需要命令行基础：双击 / 一条命令就能开始说话。

> 这是灵魂引擎的「独立运行」形态。同一份引擎还有另外两种接入方式：
> **skill 版**（给 AI 工具调用）、**MCP 版**（MCP 宿主里的 `soul_*` 工具）；
> 另外两种形态不带引擎：**纯文档版**（已有服务在跑时只带文档）与
> **纯提示词版**（宿主模型自己当 ta）。带引擎的这几种共享同一份记忆，但对
> 同一份 `engine/data/` 只能有一个写者 —— 不要同时开两个。

---

## 一、三步开始

```bash
# macOS / Linux
chmod +x run.sh
./run.sh
```

```bat
rem Windows
run.cmd
```

首次运行会自动建虚拟环境并装依赖（约 42MB，几分钟），然后直接进对话界面。

| 想做的事 | 命令 |
|---|---|
| 在终端里聊天 | `./run.sh` |
| 在浏览器里聊天 | `./run.sh web` |
| 常驻在线（会自己想你、攒主动消息） | `./run.sh serve` |
| 说一句就走 | `./run.sh chat --text "今天有点累" --plain` |
| 看 ta 的状态 | `./run.sh state` |
| 看 ta 主动想说的话 | `./run.sh drain` |

---

## 二、填模型 key

引擎本身不联网查资料，但**说话要模型接口**。二选一：

**A. 让引擎自动探测**（装在 OpenClaw / QClaw 下时最省事）

```bash
./run.sh autoconfig
```

**B. 手动填**

```bash
cp engine/.env.example engine/.env
```

编辑 `engine/.env`，最少两行：

```ini
AI_PROVIDER=deepseek        # 或 openai / moonshot / zhipu / dashscope / ollama …
AI_API_KEY=sk-xxxxxxxx
```

支持任意 OpenAI 兼容服务（含本地 Ollama / vLLM / LM Studio，此时 `AI_API_KEY` 随便填）。
填完验证：

```bash
./run.sh doctor --check-api
```

---

## 三、把 ta 接进聊天软件（可选）

```bash
cd engine
python3 main.py web     # 浏览器终端
python3 main.py wx      # 微信（扫码登录）
python3 main.py qq      # QQ 官方 Bot
python3 main.py tg      # Telegram
python3 main.py dc      # Discord
python3 main.py im      # iMessage（仅 macOS + BlueBubbles）
```

⚠️ **渠道和常驻服务不能同时跑**：两者写同一个 SQLite，会撞 `database is locked`。
要跑渠道就先 `./run.sh stop`。

---

## 四、你的东西在哪

| 路径 | 内容 |
|---|---|
| `engine/data/` | **ta 的记忆、人格、状态** —— 备份它等于备份 ta |
| `engine/.env` | 你的模型 key（敏感，别外发） |
| `engine/.soul-daemon.token` | 常驻服务的鉴权 token（权限 0600，别外发） |
| `engine/.soul-daemon.log` | 常驻服务日志（超 4MB 自动裁剪） |
| `config.yaml` | 引擎路径、身份、常驻端口 |

**换机器 / 备份**：拷走整个目录，但**不必**拷 `.venv`（与平台绑定，到新机器重跑 `./run.sh setup` 或直接 `./run.sh` 会自动重建）。

---

## 五、常见问题

| 现象 | 处理 |
|---|---|
| `没找到 python3` | 装 Python 3.10+（3.14 下向量记忆装不上，对话不受影响） |
| 依赖装不上 / 装一半断了 | `./run.sh setup --minimal` 重跑；国内网络慢可先设 pip 镜像 |
| 说话要等很久 | 冷启动每次约 2s，用 `./run.sh serve` 常驻后是毫秒级 |
| 老是「没回」 | `./run.sh chat --text "在吗" --verbose` 看 `diagnostics`；若含接口失败，检查 key |
| 报 `backend_error` / 401 | key 失效或 `AI_API_BASE` / `AI_MODEL` 配错，改完 `./run.sh serve --restart` |
| 想知道链路有没有问题 | `./run.sh selftest`（沙箱 + 假回复，不碰真实记忆、不花额度） |
| `database is locked` | 渠道和常驻服务同时开着，只留一个 |
| 端口被别的副本占了 | 改 `config.yaml` 的 `daemon_port`，或先 `./run.sh stop` |

---

## 六、许可

MIT，详见同目录 `LICENSE`。
