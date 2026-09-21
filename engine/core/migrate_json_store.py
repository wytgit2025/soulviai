# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""JSON 持久化迁移脚本：将全项目 JSON 文件读写迁移到 JsonStore
用法: python -m core.migrate_json_store
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


_JSON_FILE_VARS = {
    "engine/behavior/projection_learning.py": [
        ('_WEIGHTS_FILE', '_get_weight_store()', True),
    ],
    "engine/cognitive/meta_cognition.py": [
        ('_PARAMS_FILE', '_get_meta_store()', False),
    ],
    "engine/cognitive/consciousness_stream.py": [
        ('STREAM_FILE', '_get_stream_store()', False),
    ],
    "engine/life/body.py": [
        ('_BODY_MEMORY_FILE', '_get_body_memory_store()', False),
        ('_BODY_TIMESERIES_FILE', '_get_body_timeseries_store()', False),
    ],
    "engine/life/fate.py": [
        ('_FINGERPRINT_FILE', '_get_fingerprint_store()', False),
    ],
    "engine/social/continuity.py": [
        ('_BREAKPOINT_FILE', '_get_breakpoint_store()', False),
    ],
    "engine/self/self_doubt.py": [
        ('_DOUBT_FILE', '_get_doubt_store()', False),
    ],
    "engine/self/self_narrative.py": [
        ('_NARRATIVE_FILE', '_get_narrative_store()', False),
    ],
    "engine/self/counterfactual_self.py": [
        ('_COUNTERFACTUAL_FILE', '_get_counterfactual_store()', False),
    ],
    "engine/self/temporal_self.py": [
        ('_TEMPORAL_FILE', '_get_temporal_store()', False),
    ],
    "engine/self/perceived.py": [
        ('_PERCEIVED_FILE', '_get_perceived_store()', False),
    ],
    "engine/cognitive/values.py": [
        ('_VALUES_FILE', '_get_values_store()', False),
    ],
    "engine/cognitive/meaning.py": [
        ('_MEANING_FILE', '_get_meaning_store()', False),
    ],
    "engine/creative/creative_spark.py": [
        ('_CREATIVE_FILE', '_get_creative_store()', False),
    ],
    "engine/behavior/delivery_memory.py": [
        ('_MEMORY_FILE', '_get_delivery_memory_store()', False),
    ],
    "engine/behavior/binding.py": [
        ('_BINDING_FILE', '_get_binding_store()', False),
        ('_LEARNING_FILE', '_get_learning_store()', False),
    ],
}


def _add_store_getter(filepath: str, var_name: str, getter_name: str):
    """向文件末尾添加 store getter 函数"""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    getter_code = f"""
def {getter_name}():
    from core.json_store import get_store
    return get_store({var_name}, {{}})
"""
    if getter_name not in content:
        with open(filepath, 'a', encoding='utf-8') as f:
            f.write(getter_code)
        print(f"  + 添加 {getter_name} → {os.path.basename(filepath)}")
    else:
        print(f"  ~ {getter_name} 已存在")


def _replace_load_save(filepath: str, var_name: str, getter_name: str):
    """替换 _load_X / _save_X 函数体为 JsonStore 版本"""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # 查找文件中对应的 load 函数
    load_pattern = r'def _load_' + var_name.lower().replace('_file', '').replace('_path', '') + r'\(\):.*?(?=\ndef |\Z)'
    
    # 更通用的模式：查找包含 open(var_name 或 open(_VAR 的函数
    lines = content.split('\n')
    modified = []
    i = 0
    changes = 0
    while i < len(lines):
        line = lines[i]
        # 检测 JSON load 模式: with open(VAR, "r"... as f: json.load(f)
        if var_name in line and 'json.load' in line and '"r"' in line:
            # 跳过整个 load 块直到找到对应的 return/except
            modified.append(f'    store = {getter_name}')
            modified.append(f'    raw = store.read()')
            # 跳过当前行和后续的 json.load 相关行
            i += 1
            while i < len(lines) and ('json.load' in lines[i] or 'with open' in lines[i] or 'as f' in lines[i]):
                i += 1
            changes += 1
            continue
        
        # 检测 JSON dump 模式: json.dump(X, f) 或 with open(VAR, "w"
        if var_name in line and ('"w"' in line or "'w'" in line or '"w' in line):
            modified.append(f'    store = {getter_name}')
            # 跳过后续的 json.dump 相关行
            i += 1
            while i < len(lines) and ('json.dump' in lines[i] or 'open(' in lines[i] or 'as f' in lines[i] or 'os.makedirs' in lines[i]):
                i += 1
            modified.append(f'    store.write(data)')
            changes += 1
            continue
        
        modified.append(line)
        i += 1
    
    if changes > 0:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write('\n'.join(modified))
        print(f"  ✓ 替换 {changes} 处读写 → {os.path.basename(filepath)}")
    else:
        print(f"  - 未找到匹配模式: {os.path.basename(filepath)}")


def migrate():
    """执行迁移"""
    engine_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'engine')
    
    for rel_path, entries in _JSON_FILE_VARS.items():
        full_path = os.path.join(os.path.dirname(engine_dir), rel_path)
        # 先尝试找 engine 目录下的路径
        alt_path = os.path.join(engine_dir, rel_path.replace('engine/', '', 1))
        
        target = full_path if os.path.exists(full_path) else alt_path
        if not os.path.exists(target):
            print(f"✗ 文件不存在: {rel_path}")
            continue
        
        print(f"\n处理: {rel_path}")
        for var_name, getter_name, _ in entries:
            _add_store_getter(target, var_name, getter_name)


if __name__ == '__main__':
    migrate()
    print("\n✅ 迁移完成。请手动检查以下文件并替换 json.load/json.dump:")
    for rel_path, entries in _JSON_FILE_VARS.items():
        print(f"  - {rel_path}")
