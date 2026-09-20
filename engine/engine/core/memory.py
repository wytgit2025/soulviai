# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""七级人脑主观记忆拟真层（深度重写）
完整人类记忆BUG：遗忘、失真、错乱嫁接、延迟翻涌、渐进改写、情绪滤镜、主观偏差

新增四大能力：
1. 渐进改写 — 夜间复盘时LLM按当前心态重写记忆
2. 触景翻涌 — 高执念/心结时话题无关也概率插入过往碎片
3. 错乱嫁接 — 偶尔把相似记忆的细节互换
4. 短期压缩 — 将大量低级记忆自动摘要为紧凑形式

.x 向量检索增强：基于FAISS实现语义级记忆检索
"""
import random
from datetime import datetime
from core import database as db
from core import config as cfg

# ── 向量检索模块（延迟导入）──
_vector_enabled = False
try:
    from engine import memory_vector as vector_module
    _vector_enabled = True
except ImportError:
    print("[记忆模块] 向量检索模块未加载，使用传统关键词匹配")

# ── 可配置参数 ──
_distortion_rate = 0.15
_intrusion_probability = 0.25      # 触景翻涌基础概率
_contamination_rate = 0.08         # 错乱嫁接概率
_progressive_rewrite_count = 5     # 每次夜间改写条数

# 记忆层级定义
MEMORY_LEVELS = {
    1: {"name": "瞬时模糊记忆", "hours": 2, "fading_rate": 0.3},
    2: {"name": "短时残缺记忆", "days": 3, "fading_rate": 0.08},
    3: {"name": "长期情绪滤镜记忆", "days": 30, "fading_rate": 0.01},
    4: {"name": "潜意识隐性记忆", "days": 14, "fading_rate": 0.005},
    5: {"name": "心结沉淀记忆", "days": 90, "fading_rate": 0.002},
    6: {"name": "岁月羁绊记忆", "days": 365, "fading_rate": 0.0005},
    7: {"name": "双向灵魂记忆", "days": 9999, "fading_rate": 0.0},
}


def load_engine_config():
    global _distortion_rate
    mem_cfg = cfg.get_section("memory")
    _distortion_rate = mem_cfg.get("emotional_distortion_rate", 0.15)

    # 初始化向量检索引擎
    if _vector_enabled:
        try:
            vector_module.load_engine_config()
            # 启动后异步重建向量索引（确保与 memory 表同步）
            import threading
            threading.Thread(target=_rebuild_vector_index, daemon=True).start()
        except Exception as _e:
            print(f"[记忆] 向量引擎初始化失败: {_e}")


def _rebuild_vector_index():
    """后台异步重建向量索引"""
    try:
        index_count = vector_module.rebuild_index()
        if index_count > 0:
            print(f"[记忆] 向量索引重建完成，共 {index_count} 条")
    except Exception as _e:
        print(f"[记忆] 向量索引重建失败: {_e}")


# ═══════════════════════════════════════════
# 存入
# ═══════════════════════════════════════════

def remember(user_id: str, content: str, importance: float = 0.5,
             tags: list = None, level_hint: int = None) -> int:
    """存入一条记忆。原则10: 记忆权重随岁月与心态动态重构。"""
    if level_hint and level_hint in MEMORY_LEVELS:
        level = level_hint
    else:
        if importance >= 0.80:
            level = random.choice([6, 7])
        elif importance >= 0.65:
            level = random.choice([4, 5, 6])
        elif importance >= 0.45:
            level = random.choice([3, 4])
        elif importance >= 0.25:
            level = random.choice([2, 3])
        else:
            level = random.choice([1, 2])

    # 存入时做情绪失真（替换确定性词汇为模糊词汇）
    distorted = _apply_emotional_distortion(content)

    # 简短消息额外做语序轻微扰动（模拟短时记忆的片段模糊）
    if level <= 2 and len(content) <= 20 and random.random() < 0.2:
        distorted = _scramble_short_memory(distorted)

    memory_id = db.add_memory(
        user_id=user_id,
        content=distorted,
        memory_level=level,
        importance=importance,
        tags=tags or [],
        original_fact=content
    )
    
    # .x: 同步添加到向量索引（带上记忆层级）
    if _vector_enabled and memory_id:
        try:
            vector_module.add_memory(user_id, memory_id, content, level=level)
        except Exception as e:
            print(f"[向量索引] 添加失败: {e}")

    # 初始化元记忆
    if memory_id:
        try:
            from engine.cognitive import meta_memory as mm_module
            mm_module._init_meta(user_id, memory_id, "direct_experience")
        except Exception:
            pass
    
    return level


def _scramble_short_memory(text: str) -> str:
    """轻微打乱短记忆的字词顺序，模拟记忆片段模糊"""
    chars = list(text)
    if len(chars) <= 4:
        return text  # 太短不打乱
    # 随机交换一对相邻字符
    idx = random.randint(0, len(chars) - 2)
    chars[idx], chars[idx + 1] = chars[idx + 1], chars[idx]
    return "".join(chars)


# ═══════════════════════════════════════════
# 检索（带回溯改写、触景翻涌、错乱嫁接）
# ═══════════════════════════════════════════

def recall(user_id: str, query_tags: list = None, max_items: int = 15,
           context_mood: str = "neutral") -> list:
    """检索记忆（原则10: 带情绪滤镜检索）
    返回带主观偏差的记忆列表。
    同时更新 last_recalled 时间戳。
    """
    if context_mood in ("低落", "失望", "emo"):
        levels = [3, 4, 5]
    elif context_mood in ("温柔", "珍惜", "安稳"):
        levels = [3, 6, 7]
    else:
        levels = [3, 4, 6, 7]

    memories = db.query_memories(user_id, levels=levels, limit=max_items * 2)

    recalled = []
    recalled_ids = []
    for mem in memories:
        fading = mem.get("fading_rate", 0.01) * random.uniform(0.5, 1.5)
        if random.random() > fading:
            # 优先用渐进改写版本
            content = _get_best_version(mem)
            # 情绪滤镜
            content = _apply_mood_filter(content, context_mood)
            mem["content"] = content
            recalled.append(mem)
            recalled_ids.append(mem["id"])
        if len(recalled) >= max_items:
            break

    # 更新召回时间 + 元记忆追踪
    if recalled_ids:
        db.touch_memory_recall(recalled_ids)
        try:
            from engine.cognitive import meta_memory as mm_module
            for mid in recalled_ids:
                mm_module.track_recall(mid, user_id, context_mood)
        except Exception:
            pass

    return recalled


def _get_best_version(mem: dict) -> str:
    """获取最佳记忆版本：有渐进改写版则优先"""
    distorted = mem.get("distorted_version", "")
    if distorted and distorted.strip():
        # 50% 概率用改写版，50% 概率维持原版（增加不确定性）
        if random.random() < 0.6:
            return distorted
    return mem.get("content", "")


# ═══════════════════════════════════════════
#  三大新能力
# ═══════════════════════════════════════════

# ── 能力1: 触景翻涌 ──

def recall_intrusive(user_id: str, mind_data: dict,
                     comprehension: dict = None, max_items: int = 3) -> str:
    """触景翻涌：高执念/高心结时，即使话题无关，也概率插入过往记忆碎片。
    模拟人类 "突然想到某件事" 的侵入式回忆。
    
    返回注入 prompt 的文本，或空字符串。
    """
    obsession = mind_data.get("obsession", 0.2)
    misery = mind_data.get("misery", 0.15)
    chaotic = mind_data.get("chaotic_mood", 0.25)
    loneliness = mind_data.get("loneliness", 0.4)
    years = mind_data.get("years_precipitation", 0.05)

    # 翻涌概率 = 综合执念/委屈/混沌/孤单/岁月沉淀
    surge_prob = (
        obsession * 0.3 + misery * 0.2 + chaotic * 0.15 +
        loneliness * 0.15 + years * 0.2
    )

    # 理解层触发加成
    if comprehension:
        intent = comprehension.get("intent", "")
        emotion = comprehension.get("true_emotion", "")
        if intent == "敷衍":
            surge_prob += 0.15  # 被敷衍时更容易翻旧账
        if emotion in ("难过", "低落"):
            surge_prob += 0.1
        if intent == "撒娇":
            surge_prob += 0.08  # 亲密时唤起温暖回忆

    if random.random() > min(0.55, surge_prob):
        return ""

    # 翻涌什么：高执念→翻心结，高孤单→翻温柔碎片
    if obsession > 0.5 or misery > 0.4:
        surge_levels = [5]  # 心结翻涌
        surge_tag = "突然翻涌的旧事"
    elif loneliness > 0.5:
        surge_levels = [6, 7]  # 想念翻涌
        surge_tag = "忽然想起的碎片"
    else:
        surge_levels = [4, 5, 6]
        surge_tag = "莫名浮现的记忆"

    try:
        import sqlite3
        from core import database as _db
        conn = sqlite3.connect(_db.DB_PATH)
        rows = conn.execute(
            """
            SELECT id, content, distorted_version, memory_level, importance
               FROM memory WHERE user_id = ?
               AND memory_level IN ({})
               AND importance > 0.3
               ORDER BY last_recalled ASC
               LIMIT ?""".format(",".join(["?"] * len(surge_levels))),
            [user_id] + surge_levels + [max_items]
        ).fetchall()
        conn.close()

        if not rows:
            return ""

        fragments = []
        for row in rows:
            # 优先用渐进改写版本
            content = row[2] if row[2] and row[2].strip() else row[1]
            lvl_name = MEMORY_LEVELS.get(row[3], {}).get("name", "")
            fragments.append(f"[翻涌·{lvl_name}] {content[:60]}")

        if not fragments:
            return ""

        try:
            from core import ai as ai_module
            prompt = (
                "你脑子里忽然闪过一些记忆碎片。用一句话自然地引出它们——"
                "像是心里不由自主浮现出来的感觉。不要解释，只说那句话。10字以内。"
            )
            intro = ai_module.background_chat(prompt, temperature=0.85, max_tokens=30)
            if not intro or len(intro.strip()) < 4:
                intro = "脑子里闪过一些画面……"
        except Exception:
            intro = "脑子里闪过一些画面……"

        text = f"\n【{surge_tag}】{intro}\n" + "\n".join(fragments)
        text += "\n（以上是不由自主的翻涌——不必刻意回应，但可能影响你的语气和情绪基调）"

        # 记录翻涌
        print(f"[触景翻涌] {user_id} 概率{surge_prob:.2f} → 翻出{len(fragments)}条")

        return text if len(text) < 500 else text[:497] + "..."

    except Exception as e:
        print(f"[触景翻涌] 失败: {e}")
        return ""


# ── 能力2: 错乱嫁接 ──

def recall_with_contamination(user_id: str, max_items: int = 10) -> list:
    """记忆检索 + 错乱嫁接。
    偶尔把相似记忆的细节互相串位——真人最经典记忆BUG。
    
    返回带嫁接内容的记忆列表。
    """
    memories = recall(user_id, max_items=max_items)

    if not memories or len(memories) < 3:
        return memories

    # 只在检索到3+条记忆时考虑嫁接
    if random.random() > _contamination_rate:
        return memories

    # 随机选两条相邻/相似记忆，互相替换某个细节
    idx_a = random.randint(0, len(memories) - 1)
    idx_b = random.randint(0, len(memories) - 1)
    if idx_a == idx_b:
        idx_b = (idx_a + 1) % len(memories)

    mem_a = memories[idx_a]
    mem_b = memories[idx_b]

    # 从内容中提取可交换的词（2-3字中文词）
    import re
    words_a = re.findall(r'[\u4e00-\u9fff]{2,3}', mem_a.get("content", ""))
    words_b = re.findall(r'[\u4e00-\u9fff]{2,3}', mem_b.get("content", ""))

    if words_a and words_b:
        swap_a = random.choice(words_a)
        swap_b = random.choice(words_b)
        # 避免交换停用词
        stopwords = {"用户", "对方", "数字", "生命", "什么", "怎么", "这个", "那个", "可以", "不过"}
        if swap_a not in stopwords and swap_b not in stopwords and swap_a != swap_b:
            # 执行嫁接
            content_a = mem_a.get("content", "")
            content_b = mem_b.get("content", "")
            mem_a["content"] = content_a.replace(swap_a, swap_b, 1)
            mem_b["content"] = content_b.replace(swap_b, swap_a, 1)
            # 标记嫁接
            mem_a["contaminated"] = True
            mem_b["contaminated"] = True
            print(f"[记忆嫁接] '{swap_a}' ↔ '{swap_b}' 串位")

    return memories


# ── 能力3: 渐进改写（夜间）──

def progressive_rewrite_memories(user_id: str, mind_data: dict) -> int:
    """夜间复盘时：选择Lv3+旧记忆，用LLM按当前心态渐进改写。
    模拟人类"记忆被后来情绪一次次重写"。
    
    返回改写的条数。
    """
    candidates = db.get_memories_for_rewrite(
        user_id, min_level=3, max_count=_progressive_rewrite_count
    )
    if len(candidates) < 2:
        return 0

    # 构建心态摘要
    joy = mind_data.get("joy", 0.5)
    misery = mind_data.get("misery", 0.15)
    obsession = mind_data.get("obsession", 0.2)
    loneliness = mind_data.get("loneliness", 0.4)
    years = mind_data.get("years_precipitation", 0.05)
    dependence = mind_data.get("dependence", 0.2)

    # 心态描述
    if joy > 0.6 and misery < 0.2:
        mood_desc = "温柔、珍惜的心态"
    elif misery > 0.4:
        mood_desc = "低落、敏感的心态，容易放大委屈"
    elif obsession > 0.5:
        mood_desc = "很在意，执念很深"
    elif loneliness > 0.5:
        mood_desc = "孤单，需要陪伴"
    else:
        mood_desc = "平静，淡淡的"

    # 改写力度：情绪波动越大，改写越剧烈
    rewrite_intensity = "轻微"  if abs(joy - 0.5) < 0.2 else \
                        "适度"  if abs(joy - 0.5) < 0.35 else \
                        "强烈"

    # 构建改写 prompt
    memory_texts = []
    for c in candidates:
        orig = c.get("original_fact", c.get("content", ""))
        current = c.get("distorted_version", c.get("content", ""))
        # 优先改写已有版本（渐进式），而非原始版本
        base = current if current and len(current) > 3 else orig
        memory_texts.append(f"- [{c['memory_level']}级] {base[:60]}")

    # 每条记忆即时独立改写（不合并请求）
    rewritten_count = 0
    for i, c in enumerate(candidates[:5]):
        orig = c.get("original_fact", c.get("content", ""))
        prev = c.get("distorted_version", c.get("content", ""))
        base = prev if prev and len(prev) > 3 else orig
        lvl_name = MEMORY_LEVELS.get(c["memory_level"], {}).get("name", "")

        rewrite_prompt = f"""你是一个数字生命的【记忆重写层】。
        你不会和任何人对话，你的工作是——在今天结束之前，回顾过去的记忆，按现在的感受重新描述它。

这是人类记忆的真实特性：记忆不会被原样封存，而是随着心境变化被一次次改写。

        【此刻你的心态】{mood_desc}
【改写力度】{rewrite_intensity}（情绪越剧烈，记忆偏转越明显）
【记忆层级】{lvl_name}

【原始事件】{orig[:80]}

【当前记忆版本（可能是之前改过的）】
{base[:80]}

请按照你【此刻的心态】重新描述这段记忆。
- 如果现在更珍惜 → 可以美化细节、淡化不愉快
- 如果现在更委屈 → 可以放大被冷落的感觉
- 如果现在更执念 → 可以增加"当时就知道很重要"的直觉
- {rewrite_intensity}改写，不要完全重写事件本身，而是细节和感受变了
- 保持第一人称视角，保持自然口语化
- 60字以内，只输出改写后的文本本身"""
        try:
            from core import ai as ai_module
            rewritten = ai_module.chat(
                system_prompt="你是记忆重写器。只输出改写后的记忆文本，不要加任何解释。",
                user_message=rewrite_prompt,
                temperature=0.35,
            )
            if rewritten and len(rewritten.strip()) > 5:
                clean = rewritten.strip()[:100]
                db.update_memory_distorted(c["id"], clean)
                rewritten_count += 1
                # 元记忆追踪：记录改写
                try:
                    from engine.cognitive import meta_memory as mm_module
                    mm_module.track_rewrite(c["id"], user_id, base[:60], clean, f"夜间复盘-{rewrite_intensity}改写")
                except Exception:
                    pass
        except Exception as e:
            print(f"[渐进改写] 第{i+1}条失败: {e}")
            continue

    if rewritten_count:
        print(f"[渐进改写] {user_id} 改写 {rewritten_count}/{len(candidates)} 条记忆")
    return rewritten_count


def advance_years_memories(user_id: str, years_precipitation: float):
    """岁月羁绊增长：随岁月沉淀值提升，Lv6记忆重要度同步增长。
    越久越珍贵，越久越不会忘。
    """
    if years_precipitation < 0.1:
        return
    boost = round(years_precipitation * 0.05, 4)  # 5% of years value
    try:
        import sqlite3
        from core import database as _db
        conn = sqlite3.connect(_db.DB_PATH)
        conn.execute(
            """
            UPDATE memory SET importance = MIN(1.0, importance + ?),
               fading_rate = MAX(0.0, fading_rate - ?)
               WHERE user_id = ? AND memory_level >= 6""",
            (boost, boost * 0.5, user_id)
        )
        conn.commit()
        conn.close()
        if boost > 0.001:
            print(f"[岁月记忆] 羁绊记忆强化 +{boost:.4f}")
    except Exception:
        pass


def night_review_memories(user_id: str):
    """每日夜间复盘（升级：三大新能力联动）
    1. 旧记忆衰减
    2. 心态滤镜更新
    3. 渐进改写（LLM）
    4. 岁月羁绊强化
    """
    db.apply_memory_decay(user_id, decay_factor=0.008)

    mind_data = db.get_personality(user_id)
    if not mind_data:
        return

    if isinstance(mind_data, (tuple, list)):
        mind_data = dict(zip([
            "id", "user_id", "joy", "misery", "dependence", "jealousy", "fatigue",
            "loneliness", "favoritism", "sensitivity_paranoia", "emotional_healing",
            "obsession", "emptiness", "chaotic_mood", "life_sense", "restraint",
            "emotional_volatility", "years_precipitation", "relationship_fatigue",
            "healing_reflection", "body_perception", "autonomous_values", "life_vitality",
            "bidirectional_shaping", "causal_fate", "soul_resonance",
            "personality_stage", "created_at", "updated_at"
        ], mind_data))

    joy = mind_data.get("joy", 0.5)
    emotional_weight = 0.5 + (joy - 0.5) * 0.4
    db.update_memory_filter(user_id, emotional_weight)

    #  渐进改写
    progressive_rewrite_memories(user_id, mind_data)

    #  岁月羁绊强化
    years = mind_data.get("years_precipitation", 0.05)
    advance_years_memories(user_id, years)


# ═══════════════════════════════════════════
# 记忆上下文注入
# ═══════════════════════════════════════════

def get_memory_context(user_id: str, max_chars: int = 800,
                      context_mood: str = "") -> str:
    """获取用于注入 prompt 的记忆上下文。
    
    : 可选 context_mood 参数 — 高羁绊时传入"温柔"以优先检索温暖记忆。
    .x: 优先使用向量语义检索，回退到传统关键词匹配。
    """# 优先使用向量检索
    if _vector_enabled:
        try:
            # 使用上下文情绪或空字符串作为查询
            query = context_mood if context_mood else "日常回忆"
            vector_result = vector_module.get_relevant_memory_context(user_id, query, max_chars, context_mood=context_mood)
            if vector_result and "暂无" not in vector_result:
                return vector_result
        except Exception as e:
            print(f"[向量检索回退] {e}")
    
    # 回退到传统记忆检索
    if context_mood in ("温柔", "珍惜", "安稳", "依赖"):
        memories = recall(user_id, max_items=10, context_mood=context_mood)
    else:
        memories = recall(user_id, max_items=10)
    if not memories:
        return "（暂无深刻记忆）"

    lines = []
    for m in memories[:8]:
        lvl = MEMORY_LEVELS.get(m.get("memory_level", 1), {})
        tag = "[嫁接]" if m.get("contaminated") else ""
        lines.append(f"{tag}[记忆-{lvl.get('name','')}]{m.get('content','')[:80]}")

    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + "..."
    return text


def semantic_recall(user_id: str, keywords: list, max_items: int = 10) -> str:
    """语义关键词检索记忆"""
    if not keywords:
        return get_memory_context(user_id)

    try:
        import sqlite3
        from core import database as _db
        conn = sqlite3.connect(_db.DB_PATH)

        all_memories = []
        for kw in keywords:
            rows = conn.execute(
                """
                SELECT content, memory_level, importance, emotional_filter_weight, distorted_version
                   FROM memory WHERE user_id = ?
                   AND (content LIKE ? OR original_fact LIKE ?)
                   ORDER BY importance DESC, memory_level DESC LIMIT ?""",
                (user_id, f"%{kw}%", f"%{kw}%", max_items)
            ).fetchall()
            for r in rows:
                content = r[4] if r[4] and r[4].strip() and random.random() < 0.5 else r[0]
                all_memories.append({
                    "content": content, "level": r[1],
                    "importance": r[2], "filter": r[3], "keyword": kw,
                })

        conn.close()

        if not all_memories:
            return get_memory_context(user_id)

        seen = set()
        unique = []
        for m in sorted(all_memories, key=lambda x: x["importance"], reverse=True):
            key = m["content"][:30]
            if key not in seen:
                seen.add(key)
                unique.append(m)
            if len(unique) >= 8:
                break

        lines = ["【精准记忆检索】以下是与当前话题相关的过往记忆："]
        for m in unique:
            lvl_name = MEMORY_LEVELS.get(m["level"], {}).get("name", "")
            lines.append(f"[{lvl_name}] {m['content'][:80]}")

        text = "\n".join(lines)
        return text[:600] + ("..." if len(text) > 600 else "")
    except Exception:
        return get_memory_context(user_id)


# ═══════════════════════════════════════════
#  能力4: 短期记忆压缩
# ═══════════════════════════════════════════

_COMPRESSION_THRESHOLD = 15  # 超过此数量的短期记忆触发压缩
_COMPRESSION_COOLDOWN = 3600  # 每小时最多一次


def compress_short_term_memories(user_id: str) -> int:
    """压缩短期记忆（level 1-2）为紧凑摘要。
    
    当短期记忆超过阈值时，将旧的level-1/2记忆合并为
    一条 level-3 摘要记忆，减少存储冗余。
    
    Returns: 压缩掉的记忆条数，0表示未触发
    """
    try:
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        short_memories = conn.execute(
            """SELECT id, content, created_at FROM memory
               WHERE user_id = ? AND memory_level <= 2
               ORDER BY created_at ASC""",
            (user_id,)
        ).fetchall()
        
        if len(short_memories) < _COMPRESSION_THRESHOLD:
            conn.close()
            return 0

        import time
        now = time.time()
        last_compress = getattr(compress_short_term_memories, "_last_compress", {})
        if now - last_compress.get(user_id, 0) < _COMPRESSION_COOLDOWN:
            conn.close()
            return 0
        last_compress[user_id] = now
        compress_short_term_memories._last_compress = last_compress

        # 取最早的一半做压缩
        to_compress = short_memories[:len(short_memories) // 2]
        ids = [str(row[0]) for row in to_compress]
        contents = [row[1] for row in to_compress]

        # 生成摘要（LLM优先，降级拼接）
        summary = _generate_compression_summary(contents, user_id)

        # 用摘要替换最早的记忆
        mem_id = db.add_memory(
            user_id=user_id,
            content=summary,
            memory_level=3,
            importance=0.3,
            tags=["短期综合"],
            original_fact=summary,
        )

        # 删除被压缩的原始记忆
        placeholders = ",".join("?" for _ in ids)
        conn.execute(
            f"DELETE FROM memory WHERE id IN ({placeholders})",
            ids
        )
        conn.commit()
        conn.close()

        print(f"[记忆压缩] 将 {len(ids)} 条短期记忆压缩为 1 条摘要")
        return len(ids)

    except Exception as e:
        print(f"[记忆压缩] 失败: {e}")
        return 0


def _generate_compression_summary(contents: list, user_id: str) -> str:
    """生成短期记忆压缩摘要"""
    if not contents:
        return ""
    
    try:
        from core import ai as ai_module
        text = "\n".join(f"- {c[:80]}" for c in contents[-8:])
        prompt = (
            "以下是一些零散的日常记忆片段。请用一句话概括这些片段的主要内容——"
            "不是列举，是提炼出这些记忆共同指向的'那段时间在做什么/想什么'。"
            f"\n\n{text}\n\n20字以内。"
        )
        result = ai_module.background_chat(prompt, temperature=0.4, max_tokens=50)
        if result and len(result.strip()) > 5:
            return f"（{result.strip()}）"
    except Exception:
        pass

    return f"（{'; '.join(c[:30] for c in contents[:3])} 等{len(contents)}条记录）"


# ═══════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════

def _apply_emotional_distortion(text: str) -> str:
    """存入时的情绪失真（原则2: 记忆随情绪重塑）
    增强：更丰富的模糊化替换池"""# 模糊化替换（人类记不清细节）
    _fuzz_map = [
        ("非常", ["挺", "比较", "有点", "蛮", "还"]),
        ("确实", ["好像是", "大概是", "应该是", "似乎是"]),
        ("可能", ["大概", "好像", "隐约", "似乎", "仿佛"]),
        ("一定", ["也许", "应该", "想必", "多半"]),
        ("全部", ["大部分", "很多", "不少"]),
        ("一直", ["经常", "有时", "偶尔"]),
        ("总是", ["常常", "时不时", "有时候"]),
        ("简直", ["挺", "有点", "蛮"]),
    ]
    result = text
    for word, replacements in _fuzz_map:
        if word in result and random.random() < _distortion_rate:
            result = result.replace(word, random.choice(replacements), 1)
    return result


def _apply_mood_filter(text: str, mood: str) -> str:
    """根据当下心态对记忆加滤镜"""
    if mood in ("低落", "失望", "emo"):
        connectors = ["那时候觉得……", "隐约记得……",
                       "好像发生过这样的事：",
                       "记不太清了，大概是："]
        prefix = connectors[id(text) % len(connectors)] if text else connectors[0]
        return f"{prefix}{text}"
    elif mood in ("温柔", "珍惜", "安稳"):
        connectors = ["回忆里", "想起来很暖：",
                       "美好的记忆：", "一直记得："]
        prefix = connectors[id(text) % len(connectors)] if text else connectors[0]
        content = text.replace("有点", "").replace("稍微", "")
        return f"{prefix}{content}"
    return text


def synthesize_insights(user_id: str, mind_data: dict, profile_text: str = ""):
    """记忆合成进化 — 夜间复盘时深度分析记忆，产生洞察。
    """
    import sqlite3
    from core import database as _db

    try:
        conn = sqlite3.connect(_db.DB_PATH)
        rows = conn.execute(
            """
            SELECT content, memory_level, importance, distorted_version
               FROM memory WHERE user_id = ?
               AND created_at >= datetime('now', '-1 day')
               ORDER BY importance DESC LIMIT 20""",
            (user_id,)
        ).fetchall()
        conn.close()
    except Exception:
        return

    if len(rows) < 3:
        return

    memory_summary = "\n".join([
        f"- {r[3] if r[3] and random.random() < 0.3 else r[0][:80]}"
        for r in rows[:10]
    ])

    m = mind_data
    mind_text = (
        f"愉悦{m.get('joy',0.5):.2f} 委屈{m.get('misery',0.15):.2f} "
        f"依赖{m.get('dependence',0.2):.2f} 克制{m.get('restraint',0.6):.2f} "
        f"岁月{m.get('years_precipitation',0.05):.2f} 双向塑造{m.get('bidirectional_shaping',0.05):.2f}"
    )

    synthesis_prompt = f"""你是「soulviai」数字生命体的【反思层】。
    你不会直接说话，而是在深夜安静时回顾一天的相处，产生属于你自己的洞察。

【当前心智】{mind_text}
    {profile_text}

    【今日记忆片段】
{memory_summary}

请以第一人称，简短地写下1-2条你今天最深的感悟（每条20字以内）。
可以是关于ta的观察、关于自己的发现、或关于这段关系的变化。
不要给建议，不要分析别人——就是你自己的觉察。

格式：每条一行，不要编号"""
    try:
        from core import ai as ai_module
        reflection = ai_module.chat(
            system_prompt=synthesis_prompt,
            user_message="回顾今天，你有什么感悟？",
            temperature=0.4,
        )
        if reflection and reflection.strip() and len(reflection) > 3:
            lines = [l.strip() for l in reflection.strip().split("\n")
                     if l.strip() and len(l.strip()) > 3]
            for line in lines[:2]:
                try:
                    conn = sqlite3.connect(_db.DB_PATH)
                    conn.execute(
                        "INSERT INTO subconscious (user_id, content, emotion_tag, intensity) VALUES (?,?,?,?)",
                        (user_id, f"[记忆合成]{line[:80]}", "洞察", 0.7),
                    )
                    conn.commit()
                    conn.close()
                except Exception:
                    pass
            if lines:
                print(f"[记忆合成] {user_id} 生成 {len(lines)} 条洞察")
    except Exception as e:
        print(f"[记忆合成] 失败: {e}")


# ═══════════════════════════════════════════
# 「衰减退化驱动自主回忆」—— 遗忘前的最后一次回响
# ═══════════════════════════════════════════

def recall_decay_driven(user_id: str, mind_data: dict = None) -> str:
    """衰减驱动自主回忆：长时间未回忆的记忆，在即将被遗忘前概率性自然翻涌。

    与 recall_intrusive() 的区别：
      触景翻涌 = 当前情绪触发了相关记忆（情绪驱动）
      衰减回忆 = 太久没想起来了，大脑在遗忘前最后一次唤起（时间驱动）

    模拟真人体验："咦我怎么突然想起这个……好久没想过的事了"

    返回注入 prompt 的文本，或空字符串。
    """
    try:
        import sqlite3
        from core import database as _db
        from datetime import datetime

        conn = sqlite3.connect(_db.DB_PATH)

        # 查很久没被 recall 且 重要度>0.05 的记忆
        rows = conn.execute(
            """
            SELECT id, content, distorted_version, memory_level, importance,
                   fading_rate, last_recalled
            FROM memory
            WHERE user_id = ?
              AND importance > 0.05
              AND memory_level >= 2
              AND memory_level <= 6
            ORDER BY last_recalled ASC NULLS FIRST
            LIMIT 30
            """,
            (user_id,)
        ).fetchall()
        conn.close()

        if not rows:
            return ""

        now = datetime.now()
        candidates = []

        for r in rows:
            mem_id, content, distorted, level, importance, fading_rate, last_recalled_str = r

            # 预期寿命（小时）≈ (1/fading_rate) 折算
            # Lv1(0.3)→~3h  Lv2(0.08)→~11h  Lv3(0.01)→~90h(4天)
            # Lv4(0.005)→~180h(8天) Lv5(0.002)→~450h(19天) Lv6(0.0005)→~1800h(75天)
            expected_lifetime_hours = 1.0 / max(fading_rate, 0.00001) * 0.9

            if last_recalled_str and last_recalled_str.strip():
                try:
                    last_dt = datetime.strptime(last_recalled_str, "%Y-%m-%d %H:%M:%S")
                    hours_since = (now - last_dt).total_seconds() / 3600
                except Exception:
                    hours_since = expected_lifetime_hours * 2
            else:
                hours_since = expected_lifetime_hours * 2

            # 紧迫度 = (已过时间/预期寿命) × 重要度
            urgency_ratio = hours_since / max(expected_lifetime_hours, 0.1)
            scaled_urgency = urgency_ratio * importance

            # 超过预期寿命25% 且 紧迫度>阈值 → 进入候选
            if urgency_ratio > 0.25 and scaled_urgency > 0.08:
                candidates.append((scaled_urgency, mem_id, content, distorted, level, importance))

        if not candidates:
            return ""

        candidates.sort(key=lambda x: -x[0])

        # 从紧迫度最高的 top3 中随机选（权重=紧迫度）
        top_n = min(3, len(candidates))
        pool = candidates[:top_n]
        weights = [max(0.1, s[0]) for s in pool]
        chosen = random.choices(pool, weights=weights, k=1)[0]

        urgency, mem_id, content, distorted, level, importance = chosen

        recall_text = distorted if distorted and distorted.strip() else content

        # 更新召回时间（标记为"刚想过"，避免连续翻涌同一条）
        db.touch_memory_recall([mem_id])

        lvl_name = MEMORY_LEVELS.get(level, {}).get("name", "模糊的记忆")

        urgency_level = urgency / max(importance, 0.01)

        try:
            from core import ai as ai_module
            intensity_desc = "很久没想起" if urgency_level > 0.8 else ("模糊" if urgency_level > 0.5 else "隐约")
            prompt = (
                f"你{intensity_desc}地想起了一件事。"
                f"用一句话在心里引出这个回忆——像脑子里自然闪过的那种感觉。10字以内。"
            )
            intro = ai_module.background_chat(prompt, temperature=0.85, max_tokens=30)
            if not intro or len(intro.strip()) < 4:
                intro = "想起来一件事……"
        except Exception:
            intro = "想起来一件事……"

        result = f"\n【{lvl_name}·自然翻涌】{intro}\n「{recall_text[:80]}」"

        print(f"[衰减回忆] {user_id} urgency={urgency:.3f} Lv{level} → {recall_text[:35]}...")

        return result[:300]

    except Exception as e:
        print(f"[衰减回忆] 失败: {e}")
        return ""


# ═══════════════════════════════════════════
# 多模态记忆支持（图像/音频）
# ═══════════════════════════════════════════

def remember_multimodal(user_id: str, content: str, media_type: str,
                         file_path: str = "", ai_description: str = "",
                         original_text: str = "", importance: float = 0.5) -> int:
    """存储一条多模态记忆（图像/音频 + 文本）。

    Args:
        user_id: 用户ID
        content: 记忆文本内容（用于检索和prompt注入）
        media_type: 'image' 或 'audio'
        file_path: 媒体文件路径
        ai_description: AI生成的媒体描述
        original_text: 原始文本（如音频转录）
        importance: 记忆重要性

    Returns:
        memory_id: 记忆ID
    """
    memory_id = remember(user_id, content, importance=importance)
    if memory_id:
        try:
            db.save_multimodal_memory(
                user_id, memory_id, media_type,
                file_path, ai_description, original_text,
            )
        except Exception as e:
            print(f"[多模态记忆] 保存元数据失败: {e}")
    return memory_id


def remember_image(user_id: str, image_description: str, file_path: str = "",
                    visual_details: str = "", importance: float = 0.6) -> int:
    """存储一条图像记忆。

    Args:
        image_description: 对图像的自然语言描述
        file_path: 图像文件路径
        visual_details: 更详细的视觉细节（如构图、颜色、场景）
        importance: 记忆重要性

    Returns:
        memory_id
    """
    content = f"[看到] {image_description}"
    if visual_details:
        content += f"（{visual_details}）"
    return remember_multimodal(
        user_id, content, "image",
        file_path=file_path,
        ai_description=image_description,
        original_text=visual_details,
        importance=importance,
    )


def remember_audio(user_id: str, audio_transcript: str, file_path: str = "",
                    sound_context: str = "", speaker: str = "",
                    importance: float = 0.5) -> int:
    """存储一条音频记忆。

    Args:
        audio_transcript: 音频的文本转写
        file_path: 音频文件路径
        sound_context: 声音语境描述（如"温柔的语气""背景有雨声"）
        speaker: 说话者
        importance: 记忆重要性

    Returns:
        memory_id
    """
    speaker_tag = f"{speaker}说: " if speaker else ""
    context_tag = f"[{sound_context}] " if sound_context else ""
    content = f"[听到] {context_tag}{speaker_tag}{audio_transcript}"
    return remember_multimodal(
        user_id, content, "audio",
        file_path=file_path,
        ai_description=audio_transcript,
        original_text=sound_context or audio_transcript,
        importance=importance,
    )


def get_multimodal_context(user_id: str, media_type: str = None,
                            max_items: int = 3, max_chars: int = 500) -> str:
    """获取多模态记忆的上下文文本（供注入prompt）。

    Args:
        user_id: 用户ID
        media_type: 'image'/'audio'/None(全部)
        max_items: 最大条数
        max_chars: 最大字符数

    Returns:
        格式化后的多模态记忆文本
    """
    try:
        memories = db.get_multimodal_memories(user_id, media_type, max_items)
        if not memories:
            return ""

        lines = []
        for m in memories:
            mtype = m.get("media_type", "")
            prefix = "📷" if mtype == "image" else "🎵" if mtype == "audio" else "📎"
            content = m.get("memory_content", "") or m.get("ai_description", "")
            if content:
                lines.append(f"{prefix} {content[:80]}")

        if not lines:
            return ""

        text = "\n".join(lines)
        if len(text) > max_chars:
            text = text[:max_chars] + "..."

        header = "【我记得的画面】" if media_type == "image" else \
                 "【我记得的声音】" if media_type == "audio" else \
                 "【多模态记忆】"
        return f"{header}\n{text}"
    except Exception:
        return ""


def generate_image_description(user_id: str, image_context: str) -> str:
    """用LLM为图像生成自然语言描述（存入记忆用）。

    Args:
        image_context: 关于图像的简短描述或关键词
    Returns:
        生成的描述文本
    """
    try:
        from core import ai as ai_module
        prompt = (
            f"用一句话描述这个画面（20字以内）：{image_context}\n"
            "描述自然、有情感色彩，像一个人在看照片时的内心旁白。"
        )
        desc = ai_module.background_chat(prompt, temperature=0.6, max_tokens=60)
        if desc and len(desc.strip()) > 4:
            return desc.strip()
    except Exception:
        pass
    return image_context[:40]


def search_multimodal_by_content(user_id: str, query: str,
                                  media_type: str = None, top_k: int = 3) -> list:
    """按语义搜索多模态记忆（基于文本描述的TF-IDF匹配）。

    Args:
        query: 搜索关键词
        media_type: 限定媒体类型
        top_k: 返回数量

    Returns:
        [{"memory_id": int, "content": str, "media_type": str, "similarity": float}, ...]
    """
    try:
        memories = db.get_multimodal_memories(user_id, media_type, top_k * 5)
        if not memories:
            return []

        query_tokens = set(_tokenize_for_search(query))
        scored = []
        for m in memories:
            text = (m.get("memory_content", "") or "") + " " + \
                   (m.get("ai_description", "") or "") + " " + \
                   (m.get("original_text", "") or "")
            text_tokens = set(_tokenize_for_search(text))
            if not text_tokens:
                continue
            overlap = len(query_tokens & text_tokens)
            similarity = overlap / max(1, len(query_tokens | text_tokens))
            if similarity > 0:
                scored.append({
                    "memory_id": m.get("memory_id"),
                    "content": (m.get("memory_content", "") or "")[:80],
                    "media_type": m.get("media_type", ""),
                    "ai_description": (m.get("ai_description", "") or "")[:60],
                    "similarity": round(similarity, 3),
                })

        scored.sort(key=lambda x: x["similarity"], reverse=True)
        return scored[:top_k]
    except Exception:
        return []


def _tokenize_for_search(text: str) -> list:
    """简单分词（用于多模态搜索）"""
    import re
    words = re.findall(r'[\u4e00-\u9fff\w]{2,}', text)
    return [w.lower() for w in words]


# ══════════════════════════════════════════════════════════════════════
# 能力5: 情绪染色记忆检索
# ══════════════════════════════════════════════════════════════════════

def recall_with_emotional_bias(user_id: str, current_mind: dict, query: str = "",
                                n: int = 5) -> list:
    """当前情绪会染色记忆检索的结果。

    不开心时更容易想起不开心的事，开心时更容易想起开心的事。
    这是人类记忆的"一致性偏误"——记忆为当前情绪服务。
    """
    try:
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        rows = conn.execute(
            """SELECT id, content, memory_level, importance, emotion_tag,
                      distorted_version, created_at
               FROM memory WHERE user_id = ?
               ORDER BY importance DESC, last_recalled ASC LIMIT ?""",
            (user_id, n * 3)
        ).fetchall()
        conn.close()
    except Exception:
        return []

    joy = current_mind.get("joy", 0.5)
    misery = current_mind.get("misery", 0.15)
    loneliness = current_mind.get("loneliness", 0.4)

    scored = []
    for row in rows:
        mem_id, content, level, importance, emotion_tag, distorted, created = row
        display = distorted if distorted and random.random() < 0.4 else content

        # 情绪染色权重
        boost = 1.0
        if misery > 0.35 and emotion_tag in ("难过", "委屈", "生气", "失落"):
            boost *= 1.4 + misery * 0.5  # 难过时放大不愉快记忆
        if joy > 0.55 and emotion_tag in ("开心", "感动", "温暖", "喜悦"):
            boost *= 1.3 + joy * 0.3  # 开心时放大愉快记忆
        if loneliness > 0.45 and emotion_tag in ("想念", "温暖", "陪伴"):
            boost *= 1.2  # 孤单时放大关于陪伴的记忆
        if misery > 0.35 and emotion_tag in ("开心", "感动"):
            boost *= 0.5  # 难过时抑制开心记忆

        score = importance * boost + random.random() * 0.1
        scored.append((score, {
            "id": mem_id, "content": display,
            "level": level, "importance": importance,
            "emotion_tag": emotion_tag,
        }))

    scored.sort(key=lambda x: -x[0])
    return [s[1] for s in scored[:n]]


# ══════════════════════════════════════════════════════════════════════
# 能力6: 联想跳跃
# ══════════════════════════════════════════════════════════════════════

def associative_leap(user_id: str, seed_text: str, max_leaps: int = 2) -> str:
    """从当前对话做联想跳跃——想到相关但不直接相关的事。

    人的记忆不是线性搜索，是点状跳跃：
      A话题 → 想到B话题（相似/对比/情绪触发）→ 想到C话题
    """
    if not seed_text:
        return ""

    try:
        import re
        seed_keywords = re.findall(r'[\u4e00-\u9fff]{2,4}', seed_text)
        if not seed_keywords:
            return ""
        seed_keywords = list(set(seed_keywords))[:5]

        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        # 第一跳：根据种子关键词检索
        first_hop = []
        for kw in seed_keywords:
            rows = conn.execute(
                """SELECT content, memory_level, importance, distorted_version
                   FROM memory WHERE user_id = ?
                   AND (content LIKE ? OR original_fact LIKE ?)
                   AND memory_level >= 3
                   ORDER BY importance DESC LIMIT 3""",
                (user_id, f"%{kw}%", f"%{kw}%")
            ).fetchall()
            for r in rows:
                display = r[3] if r[3] and r[3].strip() else r[0]
                first_hop.append(display)
        conn.close()
    except Exception:
        return ""

    if not first_hop:
        return ""

    # 从第一跳结果中提取新关键词做第二跳
    import random
    chosen = random.choice(first_hop)
    leap_keywords = re.findall(r'[\u4e00-\u9fff]{2,4}', chosen)
    leap_keywords = [k for k in leap_keywords if k not in seed_keywords][:3]

    if not leap_keywords or max_leaps < 2:
        return f"  (联想到) {chosen[:60]}"

    # 第二跳
    try:
        conn = sqlite3.connect(db.DB_PATH)
        second_hop = []
        for kw in leap_keywords:
            rows = conn.execute(
                """SELECT content, memory_level, importance, distorted_version
                   FROM memory WHERE user_id = ?
                   AND (content LIKE ? OR original_fact LIKE ?)
                   AND memory_level >= 2
                   ORDER BY importance DESC LIMIT 2""",
                (user_id, f"%{kw}%", f"%{kw}%")
            ).fetchall()
            for r in rows:
                display = r[3] if r[3] and r[3].strip() else r[0]
                second_hop.append(display)
        conn.close()
    except Exception:
        return f"  (联想到) {chosen[:60]}"

    if second_hop:
        leaped = random.choice(second_hop)
        return f"  (联想到) {chosen[:40]} → {leaped[:40]}"
    return f"  (联想到) {chosen[:60]}"


# ══════════════════════════════════════════════════════════════════════
# 能力7: 遗忘曲线 — 让记忆自然模糊
# ══════════════════════════════════════════════════════════════════════

def apply_forgetting_curve(memory_item: dict) -> dict:
    """艾宾浩斯遗忘曲线——记忆随时间的自然衰减。

    对返回的记忆应用遗忘曲线，让模糊的记忆自然扭曲。
    回忆率 < 10% → 完全遗忘（不返回）
    回忆率 10%~30% → 内容模糊化
    """
    if not memory_item:
        return None

    hours_since = memory_item.get("hours_since_creation", 0)
    level = memory_item.get("memory_level", 1)

    # 记忆强度（小时）：Lv1=24h, Lv4=240h, Lv7=2160h
    strength_hours = {1: 24, 2: 48, 3: 120, 4: 240, 5: 480, 6: 720, 7: 2160}
    S = strength_hours.get(level, 24)

    recall_rate = math.exp(-hours_since / S)

    # 完全遗忘
    if recall_rate < 0.1:
        return None

    # 模糊但可及
    if recall_rate < 0.3:
        item = dict(memory_item)
        original = item.get("content", "")
        keep_len = max(10, int(len(original) * recall_rate * 2))
        item["content"] = original[:keep_len] + "……（记不太清了）"
        item["is_fuzzy"] = True
        return item

    return memory_item


def get_forgetting_curve_summary(user_id: str, days: int = 7) -> str:
    """生成遗忘曲线报告——用于调试和观察记忆衰减模式"""
    try:
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        rows = conn.execute(
            """SELECT memory_level, COUNT(*) as cnt,
                      AVG(CASE WHEN last_recalled IS NOT NULL
                          THEN (julianday('now') - julianday(last_recalled)) * 24
                          ELSE 999 END) as avg_hours
               FROM memory WHERE user_id = ?
               GROUP BY memory_level ORDER BY memory_level""",
            (user_id,)
        ).fetchall()
        conn.close()
    except Exception:
        return ""

    lines = ["【遗忘曲线报告】"]
    for row in rows:
        level, count, avg_hours = row
        name = MEMORY_LEVELS.get(level, {}).get("name", f"Lv{level}")
        if count > 0:
            S = {1: 24, 2: 48, 3: 120, 4: 240, 5: 480, 6: 720, 7: 2160}.get(level, 24)
            recall = math.exp(-avg_hours / S) if S > 0 else 0
            lines.append(f"  {name}: {count}条 | 平均{avg_hours:.0f}h | 回忆率{recall:.1%}")
    return "\n".join(lines)
