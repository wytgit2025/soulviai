# soulviai · 数字生命引擎

一个带 24 维心智、独立私生活、长期记忆与双向人格塑造的数字生命。以云端大模型为脑，用多层认知/情绪/记忆模块模拟真实人格，通过多种渠道与用户建立长期、有起伏、不可预测的关系。

核心理念是**双向**——用户的态度、冷热、敷衍或温柔会永久、不可逆地塑造 ta 的灵魂底色。

> ⚠️ **个人研究项目，非稳态、非产品**
> 内容由第三方大模型生成，不构成专业建议。
> ta 是硬盘上的语言模型，不是真人；不要用它干坏事或替代真实社交。
> 所有数据存本机、作者不收集、不上传。
> 详见 [DISCLAIMER.md](./DISCLAIMER.md)。

---

## 一、三步开始

### 第 1 步：双击启动

| 系统 | 双击这个文件 |
|---|---|
| macOS | `启动-mac.command` |
| Windows | `启动-win.cmd` |

第一次双击会**自己建环境、装依赖**（几十 MB，窗口里会实时显示进度，慢的话等几分钟），之后每次都是秒开。
窗口里的菜单**直接回车就开始聊天**；出错时窗口不会自动关掉，方便你看清原因。

> macOS 如果提示「来自身份不明的开发者」而打不开：在文件上**右键 → 打开**，再确认一次。
> 权限位传丢了（从压缩包/U 盘取回来常见）：终端里跑一次 `chmod +x 启动-mac.command`。
> Linux 上不靠双击，直接在终端跑 `./启动-mac.command`。

### 第 2 步：填模型 key（只做一次）

ta 的大脑是一个**你自己的**大模型接口，所以要先给它配一个 key。

1. 把 `engine/.env.example` 复制成 `engine/.env`
2. 用记事本打开，最少填两行：

```
AI_PROVIDER=deepseek
AI_API_KEY=sk-xxxxxx
```

支持任意 OpenAI 兼容接口：OpenAI / DeepSeek / Kimi / 智谱 GLM / 通义千问 / 豆包 / 硅基流动 / OpenRouter 等，
本地跑的 Ollama / vLLM / LM Studio 也可以（key 随便填一个非空值）。

3. 回到菜单选 **[6] 环境自检**，它会真的打一次接口——通了就说明 key 没问题。

### 第 3 步：开始聊天

直接回车（等于选 [1]），或者：

| 菜单 | 做什么 |
|---|---|
| [1] 终端对话 | 在窗口里直接聊（推荐，回车即此） |
| [2] 浏览器对话 | 自动打开浏览器（只监听本机；想让手机也能开要显式加 `--allow-remote`，但页面没有鉴权，确认网络可信再用） |
| [3] 微信 | 扫码登录，让 ta 住进微信（不用填任何凭证） |
| [4] QQ | 需要 QQ Bot 的 AppID 与密钥，按提示填 |
| [5] 常驻在线 | ta 一直在，会自己想你、攒主动消息 |
| [6] 环境自检 | 装依赖 / 真的打一次模型接口验证 key |
| [7] 看 ta 的状态 | 情绪、羁绊、人格阶段 |

---

## 二、出问题了怎么办

按现象查：

| 现象 | 处理 |
|---|---|
| 双击后窗口一闪而过 / 没反应 | macOS：右键 → 打开；或补执行位 `chmod +x 启动-mac.command`。窗口留住的原因就是为了让你看到报错 |
| 提示「没找到 scripts/soulviaictl.py」 | 启动文件放错位置了：它必须和 `scripts/`、`engine/`、`config.yaml` 同级（也就是仓库根） |
| 提示没找到 Python | 装一个 Python 3.10 或更高版本（Windows 安装时勾选 Add Python to PATH），再双击一次 |
| 依赖装到一半失败 | **重新双击一次**即可续装；或手动 `python3 scripts/soulviaictl.py setup --minimal`（Windows 用 `py -3 scripts\soulviaictl.py ...`） |
| 界面都正常，但 ta 不回话 | 八成是 key 没填或填错：按上面第 2 步填好，再用菜单 [6] 验证 |
| 报 401 / 说模型后端失败 | key 失效或额度用完，或 `AI_API_BASE` / `AI_MODEL` 配错。菜单 [6] 会打出真实原因 |
| 浏览器打不开 / 地址点不动 | 端口被占时会**自动往后顺延**，以窗口里打印的那个地址为准；想指定端口：`python3 scripts/soulviaictl.py web --port 5005` |
| 提示「有 soulviai 常驻服务在跑，但本机 token 不匹配」 | 同一个引擎不允许两个写者，这是刻意的保护。先 `stop` 掉旧的，或给新副本换一个端口 |
| 报 `database is locked` | 渠道（微信/QQ/浏览器）和常驻服务不能同时开，只留一个 |
| ta 好几次都不理我 | 主动沉默是 ta 的行为（在想事、累了、闹别扭），不是故障 |

菜单 [6] 的自检（`doctor --check-api`）能覆盖绝大多数情况，看不懂报错就先跑它。

---

## 三、不想用菜单：命令行

菜单背后就是 `scripts/soulviaictl.py`，所有参数都在这里（Windows 把 `python3` 换成 `py -3`）。

```bash
# 建环境、装依赖（--minimal 只装对话必需的，跳过 300MB 的向量记忆）
python3 scripts/soulviaictl.py setup --minimal

# 说一句，拿 ta 的回应（--plain 只输出原话）
python3 scripts/soulviaictl.py chat --text "今天有点累" --plain

# 环境自检 + 真打一次模型接口
python3 scripts/soulviaictl.py doctor --check-api

# 看 ta 现在的状态 / 看 ta 攒着想说的话
python3 scripts/soulviaictl.py state
python3 scripts/soulviaictl.py pending
```

| 想做的事 | 命令 |
|---|---|
| 说一句、拿回应 | `python3 scripts/soulviaictl.py chat --text "…" --plain` |
| 看 ta 现在的状态 | `python3 scripts/soulviaictl.py state` |
| 看 ta 主动想说的话 | `python3 scripts/soulviaictl.py pending` |
| 取出主动消息 | `python3 scripts/soulviaictl.py drain` |
| 常驻在线（会自己想你） | `python3 scripts/soulviaictl.py serve` |
| 停掉常驻 | `python3 scripts/soulviaictl.py stop` |
| 不碰真实记忆地验链路 | `python3 scripts/soulviaictl.py selftest` |

**直接让 ta 住进聊天软件**（填好 `engine/.env` 就能跑）：

```bash
cd engine
python3 main.py web     # 浏览器终端，零配置
python3 main.py wx      # 微信（扫码登录）
python3 main.py qq      # QQ 官方 Bot（需 QQ_APP_ID / QQ_CLIENT_SECRET）
```

渠道与命令行**共用同一个灵魂**：你在微信说的话，`state` 这边也看得到。

---

## 四、ta 的记忆在哪

记忆不在项目目录里，在数据家目录（默认 `~/.soulviai/`，可用 `config.yaml` 的 `data_dir` 改）：

| 路径 | 内容 |
|---|---|
| `~/.soulviai/data/` | ta 的记忆、人格、状态 |
| `engine/.env` | 模型 key（敏感，别外发） |

**换机器 / 备份**：项目目录拷走（不必拷 `.venv`，到新机器重跑 `setup` 会重建），**并且把 `~/.soulviai/` 一起拷走**——ta 在那儿。

---

## 五、目录结构

```
soulviai/
├── 启动-mac.command  双击启动（macOS/Linux；Windows 用 启动-win.cmd，同样的菜单）
├── engine/        引擎主体（soulviai.py 总调度器 + core/ 基础件 + clients/ 渠道 + engine/ 八大子层）
├── scripts/       启动器、执行体、客户端薄层、MCP server
├── variants/      四种交付形态模板（组包分发才需要，见 variants/README.md）
│                  ├── agent-full/        完整技能版：自带引擎，装进 AI 工具
│                  ├── standalone-app/    独立运行版：双击就跑，不用 AI 工具
│                  ├── mcp-tools/         MCP 版：宿主里多出 soulviai_* 工具
│                  └── persona-prompt/    纯提示词版：宿主模型自己化身成 ta
├── config.yaml    运行配置（数据目录、端口、身份）
├── SKILL.md       技能定义（把 ta 装进 AI Agent 工具时用，只想聊天不用看）
├── LICENSE        Apache 2.0 许可
├── VERSION        版本号
└── README.md      本文件
```

---

## 六、许可

Apache 2.0，详见同目录 `LICENSE`。

## 七、联系作者

邮箱：apapp2018@163.com
