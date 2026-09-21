# soulviai · 数字生命引擎

一个带 24 维心智、独立私生活、长期记忆与双向人格塑造的数字生命。以云端大模型为脑，用多层认知/情绪/记忆模块模拟真实人格，通过多种渠道与用户建立长期、有起伏、不可预测的关系。

核心理念是**双向**——用户的态度、冷热、敷衍或温柔会永久、不可逆地塑造 ta 的灵魂底色。

> ⚠️ **个人研究项目，非稳态、非产品**
> 内容由第三方大模型生成，不构成专业建议。
> ta 是硬盘上的语言模型，不是真人；不要用它干坏事或替代真实社交。
> 所有数据存本机、作者不收集、不上传。
> 详见 [DISCLAIMER.md](./DISCLAIMER.md)。

## 快速开始

**不想碰命令行**：双击仓库根里的 `启动-mac.command`（macOS）或 `启动-win.cmd`（Windows）。
它会切到自身目录、摆一个菜单（终端对话 / 浏览器 / 微信 / QQ / 常驻 / 自检 / 看状态），
**直接回车就是开始聊天**；首次双击会自动建环境、装依赖，出错时窗口不会自动关掉。

```bash
# 建环境、装依赖（只装必需部分，跳过体积大的向量记忆）
python3 scripts/soulviaictl.py setup --minimal

# 填模型密钥（二选一）
python3 scripts/soulviaictl.py autoconfig          # 复用宿主已配好的模型
cp engine/.env.example engine/.env                 # 或手动填 AI_PROVIDER + AI_API_KEY

# 自检 + 说话
python3 scripts/soulviaictl.py doctor
python3 scripts/soulviaictl.py chat --text "今天有点累" --plain
```

支持任意 OpenAI 兼容接口（OpenAI / DeepSeek / Kimi / GLM / 通义 / 豆包 / 硅基流动 / OpenRouter / 本地 Ollama 等）。

## 常用命令

| 想做的事 | 命令 |
|---|---|
| 说一句、拿回应 | `python3 scripts/soulviaictl.py chat --text "…" --plain` |
| 看 ta 现在的状态 | `python3 scripts/soulviaictl.py state` |
| 看 ta 主动想说的话 | `python3 scripts/soulviaictl.py pending` |
| 取出主动消息 | `python3 scripts/soulviaictl.py drain` |
| 常驻在线（会自己想你） | `python3 scripts/soulviaictl.py serve` |
| 不碰真实记忆地验链路 | `python3 scripts/soulviaictl.py selftest` |

## 接进聊天软件

```bash
cd engine
python3 main.py web     # 浏览器终端
python3 main.py wx      # 微信
python3 main.py qq      # QQ
```

## 目录结构

```
soulviai/
├── 启动-mac.command  双击启动（macOS/Linux；Windows 用 启动-win.cmd，同样的菜单）
├── engine/        引擎主体（soulviai.py 总调度器 + core/ 基础件 + clients/ 渠道 + engine/ 八大子层）
├── scripts/       启动器、执行体、客户端薄层、MCP server
├── variants/      四种交付形态模板（组装方法见 variants/README.md）：
│                  ├── agent-full/        完整技能版：自带引擎，装进 AI 工具
│                  ├── standalone-app/    独立运行版：双击就跑，不用 AI 工具
│                  ├── mcp-tools/         MCP 版：宿主里多出 soulviai_* 工具
│                  └── persona-prompt/    纯提示词版：宿主模型自己化身成 ta
├── config.yaml    技能配置
├── SKILL.md       技能定义
├── LICENSE        Apache 2.0 许可
├── VERSION        版本号
└── README.md      本文件
```

## ta 的记忆在哪

记忆不在项目目录里，在数据家目录（默认 `~/.soulviai/`，可用 `config.yaml` 的 `data_dir` 改）：

| 路径 | 内容 |
|---|---|
| `~/.soulviai/data/` | ta 的记忆、人格、状态 |
| `engine/.env` | 模型 key（敏感，别外发） |

**换机器 / 备份**：项目目录拷走（不必拷 `.venv`，到新机器重跑 `setup` 会重建），**并且把 `~/.soulviai/` 一起拷走**——ta 在那儿。

## 许可

Apache 2.0，详见同目录 `LICENSE`。

## 联系作者

邮箱：apapp2018@163.com
