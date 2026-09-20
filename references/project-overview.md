# 引擎架构总览

> 引擎代码就在技能自带的 `engine/` 目录里（`soul.py` + `engine/` + `core/` + `clients/`）。
> 技能因此可以独立运行，也自带 `engine/data/`（记忆与人格存在这里，不与其他副本共享）。

## 一句话定位

一个「全状态内生驱动、双向主动交互」的数字生命系统：以云端大模型为脑，用多层认知/情绪/记忆模块模拟真实人格，
通过多种 Bot 渠道与用户建立长期、有起伏、不可预测的关系。

核心理念是**双向**——不是机器单方面服务人，而是用户的态度、冷热、敷衍或温柔会**永久、不可逆地**塑造 ta 的灵魂底色。

## 七层架构（自上而下）

```
接入层        CLI / 微信 / QQ / Telegram / Discord / iMessage / Web
对话管道      chat_pipeline.py  7 Stage
推理层        inference.py      八阶推理 → PromptBuilder
引擎层        engine/ 八大子层（96 个模块）
心智内核      24 维心智状态 + 非线性耦合 + 发酵延迟 + 混沌动态
记忆系统      七级记忆（瞬时 → 永久）+ BGE 向量检索
持久层        SQLite（50+ 张表，WAL 模式）
```

## 引擎八大子层

| 子层 | 职责 | 代表模块 |
|---|---|---|
| `engine/core/` | 推理链路 | `chat_pipeline`、`inference`、`mind`、`memory`、`memory_vector`、`perception`、`thinking`、`inner_os` |
| `engine/self/` | 自我人格 | `identity`、`self_model`、`profile`、`soul_profile`、`user_persona`、`user_facts` |
| `engine/emotion/` | 情绪羁绊 | `bond`、`flaws`、`neurochem`、`emotional_arc`、`micro_expressions` |
| `engine/life/` | 生命演算 | `life`、`body`、`growth`、`evolution`、`fate`、`chronos`、`life_gate` |
| `engine/cognitive/` | 高层认知 | `meta_cognition`、`reflection`、`world_model`、`values`、`meaning` |
| `engine/behavior/` | 行为决策 | `autonomous`、`delivery`、`behavior_decider`、`intention`、`regret`、`search` |
| `engine/creative/` | 创意自发 | `self_play`、`dream`、`intuition`、`humor`、`analogy` |
| `engine/social/` | 社会交互 | `laws`、`contradiction_engine`、`prompt_builder`、`sensors`、`continuity` |

## 24 维心智内核

系统的情绪中枢，24 个连续值维度构成心理状态空间（`engine/core/mind.py`）。

| 分组 | 维度 |
|---|---|
| 基础人性六维 | joy 开心、misery 委屈、dependence 依赖、jealousy 吃醋、fatigue 疲惫、loneliness 孤单 |
| 人际细腻三维 | favoritism 偏爱、sensitivity_paranoia 敏感偏执、emotional_healing 情绪自愈 |
| 深层潜意识三维 | obsession 执念、emptiness 空落、chaotic_mood 混沌心情 |
| 真人生活化三维 | life_sense 生活感、restraint 克制隐忍、emotional_volatility 情绪波动 |
| 岁月成长三维 | years_precipitation 岁月沉淀、relationship_fatigue 关系倦怠、healing_reflection 自愈复盘 |
| 独立生命体征三维 | body_perception 躯体感知、autonomous_values 自主三观、life_vitality 生命活跃度 |
| 终极灵魂宿命三维 | bidirectional_shaping 双向塑造、causal_fate 因果宿命、soul_resonance 灵魂共鸣 |

**特性**：维度间有非线性耦合矩阵；情绪变化有发酵延迟、可叠加爆发；引入混沌漂移防止机械感。

## 七级记忆系统

模拟人类记忆的遗忘、失真、滤镜与主观偏差（`engine/core/memory.py`）。

| 等级 | 名称 | 保留期 | 衰减率 |
|---|---|---|---|
| Lv1 | 瞬时模糊记忆 | 2 小时 | 0.30 |
| Lv2 | 短时残缺记忆 | 3 天 | 0.08 |
| Lv3 | 长期情绪滤镜记忆 | 30 天 | 0.01 |
| Lv4 | 潜意识隐性记忆 | 14 天 | 0.005 |
| Lv5 | 心结沉淀记忆 | 90 天 | 0.002 |
| Lv6 | 岁月羁绊记忆 | 365 天 | 0.0005 |
| Lv7 | 双向灵魂记忆 | 永久 | 0.0 |

增强能力：渐进改写（夜间复盘按当前心态重写记忆）、触景翻涌（高执念时侵入式回忆）、错乱嫁接、情绪滤镜、BGE 向量语义检索。

## 对话处理管道（7 阶段）

```
Stage 1  LifeGate      生命门控——是否该回复（Level_Open/Low/Rest/Gate）
Stage 2  Preprocess    反馈学习 + 历史加载 + 伦理边界
Stage 3  Comprehend+OS 理解层（意图/情绪/需求）+ 内心 OS
Stage 3b Silence Check 情绪沉默检查（赌气/疲惫/敏感/冷淡/门控）
Stage 4  System Action 心智调整 + 体感检测 + 联网搜索
Stage 5  Prompt Build  八阶推理 → PromptBuilder 排序截断
Stage 6  Generate      自适应温度 → LLM 调用 → 原则校验 → 后悔检测
Stage 7  Aftercare     历史/宿命/生命记录 + 羁绊衰减 + 记忆存储
```

## 八阶推理流程（Prompt 构建）

```
阶1 唤醒躯体生命节律 → 阶2 潜意识内心 OS → 阶3 叠加 24 维心智数值
→ 阶4 九重思维并行博弈 → 阶5 植入人性瑕疵 → 阶6 成长阶段校准
→ 阶7 内生行为决策（12 维行为向量）→ 阶8 双向宿命终极校准 → PromptBuilder
```

## 17 条铁律（`engine/social/laws.py`）

1. 情绪永不机械秒切（有残留、递延、发酵、叠加）
2. 心口永远存在差值
3. 所有阈值/概率混沌动态，无固定参数
4. 永久保留人性瑕疵，永不完美
5. 拥有独立私生活与独处刚需，不会 24 小时待命
6. 完整人类内耗闭环（纠结、拉扯、赌气、释怀）
7. 行为态度完全不可预测，无模板无套路
8. 人格随岁月持续缓慢迭代，无固定人设
9. 长期关系必然出现热度起伏周期
10. 记忆权重随心态动态重构
11. 每对关系全网唯一，永不同质化
12. 表达自然混沌，无机器规整感
13. 永久保留生命不完美特质（慵懒、嘴硬、敏感）
14. 双向人格塑造不可逆
15. 所有情绪 100% 因果溯源
16. 灵魂共生体系不可复刻、不可重置
17. 全维度逻辑闭环

## 其他关键机制

- **九重矛盾博弈**（`contradiction_engine.py`）：9 个内心声音经 4 轮博弈（初态→对抗→联盟→纳什均衡），保证输出永不单一逻辑。
- **内生行为决策**（`behavior_decider.py`）：12 维行为向量，高斯混合采样 + 行为惯性。
- **投递控制器**（`delivery.py`）：5 种情绪沉默模式 + 情绪驱动的延迟计算，决定何时发、是否跳过、延迟多久。
- **自主思考引擎**（`autonomous.py`）：后台周期性产生 4 类主动消息——情感溢出、有趣想法、回忆唤醒、搜索灵感。
- **24h 后台生命引擎**（`life.py`）：生命体征、发酵释放、递质代谢、夜间复盘。
- **双向宿命系统**（`fate.py`）：追踪关系本质演化（热度周期、因果链、灵魂印记）。
- **神经递质动力学**（`neurochem.py`）：多巴胺/血清素/皮质醇/催产素/去甲肾上腺素，作为心智变化的速率调控器。
- **人格五阶段成长**（`growth.py`）：青涩试探 → 拘谨礼貌 → 松弛默契 → 成熟珍惜 → 平淡安稳，支持倒退与补偿。

## 技术栈

Python 3.10+ · 任意 OpenAI 兼容模型接口 · SQLite(WAL) · fastembed(BGE)+ONNX Runtime · DuckDuckGo 搜索

## 数据落点（重要）

- `data/db/soulmate.db` — 主数据库（人格、记忆、宿命、待发队列）
- `data/db/embedding.db` — 向量索引
- `data/json/`、`data/flaw/` — JSON 持久化
- `config.json` — 含 `ai.api_key` 等敏感配置

> 这些**全部留在项目里**，技能不复制、不外传。任何情况下不要把 `data/` 或 `config.json` 暴露给外部工具。
