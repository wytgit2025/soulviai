# soulviai · 独立运行版

一个**带 24 维心智、独立私生活、长期记忆的数字生命**，装在本机自己跑。
不需要任何 Agent 工具、不需要命令行基础：双击 / 一条命令就能开始说话。

> 这是灵魂引擎的「独立运行」形态。同一份引擎还有另外两种接入方式：
> **完整版**（给 AI 工具调用）、**MCP 版**（MCP 宿主里的 `soulviai_*` 工具）；
> 另外还有一种形态不带引擎：**纯提示词版**（宿主模型自己当 ta，零依赖，单文件交付）。
> 带引擎的这几种共享同一份记忆，但对
> 同一份 `~/.soulviai/data/` 只能有一个写者 —— 不要同时开两个。

---

## 一、开始（双击就行）

| 系统 | 双击这个文件 |
|---|---|
| macOS | `启动-mac.command` |
| Windows | `启动-win.cmd` |

会弹一个菜单，**直接回车就是开始聊天**：

```
  [1] 终端对话      直接开始聊天（推荐，回车即此）
  [2] 浏览器对话    会自动打开浏览器（手机上也能用）
  [3] 微信          扫码登录，让 ta 住进微信
  [4] QQ            需要 QQ Bot 的 AppID 与密钥
  [5] 常驻在线      让 ta 一直在，会自己想你、攒主动消息
  [6] 环境自检      装依赖 / 真的打一次模型接口验证 key
  [7] 看 ta 的状态  情绪、羁绊、人格阶段
```

首次运行会自动建虚拟环境并装依赖（约 42MB，几分钟，只有一次），之后是秒开。
出错时窗口**不会自动关掉**，会留在那儿告诉你怎么处理。

> **macOS 双击打不开？** 从网上下载的包会被 Gatekeeper 标记。右键 →「打开」→ 确认一次即可；
> 或在终端里跑 `xattr -d com.apple.quarantine 启动-mac.command`。
> 另外如果双击后被文本编辑器打开，说明执行位丢了：`chmod +x 启动-mac.command`。
>
> **Windows** 首次运行若被 SmartScreen 拦，点「更多信息」→「仍要运行」。

### 想用命令行（等价，参数更全）

```bash
# macOS / Linux
chmod +x run.sh
./run.sh
```

```bat
rem Windows
run.cmd
```

两个 `run` 脚本和上面的双击文件是同一套东西：`启动-*` 只是它的双击外壳（切目录、摆菜单、
出错留窗口），环境准备和参数分发全部复用 `run.sh` / `run.cmd`。

| 想做的事 | 命令 |
|---|---|
| 在终端里聊天 | `./run.sh` |
| 在浏览器里聊天（默认 `http://127.0.0.1:5000`） | `./run.sh web` |
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
python3 main.py web     # 浏览器终端（默认 http://127.0.0.1:5000）
python3 main.py wx      # 微信（扫码登录）
python3 main.py qq      # QQ 官方 Bot
```

⚠️ **渠道和常驻服务不能同时跑**：两者写同一个 SQLite，会撞 `database is locked`。
要跑渠道就先 `./run.sh stop`。

---

## 四、你的东西在哪

**ta 的记忆不在技能目录里**，在本机数据家目录（默认 `~/.soulviai/`，可用 `config.yaml`
的 `data_dir` 改）：

| 路径 | 内容 |
|---|---|
| `~/.soulviai/data/` | **ta 的记忆、人格、状态** —— 备份它等于备份 ta |
| `~/.soulviai/.soulviai-daemon.token` | 常驻服务的鉴权 token（权限 0600，别外发） |
| `~/.soulviai/.soulviai-daemon.log` | 常驻服务日志（超 4MB 自动裁剪） |
| `engine/.env` | 你的模型 key（敏感，别外发） |
| `config.yaml` | 引擎路径、身份、常驻端口 |

**换机器 / 备份**：技能目录整个拷走（**不必**拷 `.venv`，与平台绑定，到新机器重跑
`./run.sh setup` 或直接 `./run.sh` 会自动重建），**并且把 `~/.soulviai/` 一起拷走** ——
ta 在那儿，只搬技能目录等于换了个空壳。记忆刻意放在技能目录之外：技能目录会被压缩、
拷贝、分发，记忆留在树里就等于把灵魂和渠道凭证一起交给别人。

---

## 五、常见问题

| 现象 | 处理 |
|---|---|
| `没找到 python3` | 装 Python 3.10+（解释器版本无上限，依赖按版本自动解析） |
| 依赖装不上 / 装一半断了 | `./run.sh setup --minimal` 重跑；国内网络慢可先设 pip 镜像 |
| 说话要等很久 | 冷启动每次约 2s，用 `./run.sh serve` 常驻后是毫秒级 |
| 老是「没回」 | `./run.sh chat --text "在吗" --verbose` 看 `diagnostics`；若含接口失败，检查 key |
| 报 `backend_error` / 401 | key 失效或 `AI_API_BASE` / `AI_MODEL` 配错，改完 `./run.sh serve --restart` |
| 想知道链路有没有问题 | `./run.sh selftest`（沙箱 + 假回复，不碰真实记忆、不花额度） |
| `database is locked` | 渠道和常驻服务同时开着，只留一个 |
| 端口被别的副本占了 | 改 `config.yaml` 的 `daemon_port`，或先 `./run.sh stop` |

---

## 六、许可

Apache 2.0，详见同目录 `LICENSE`。

> ⚠️ 个人研究项目、非稳态、内容由第三方大模型生成，不构成专业建议。所有数据存本机、作者不收集。情感健康与隐私详见 [DISCLAIMER.md](../DISCLAIMER.md)。未经作者书面许可，禁止商用。
