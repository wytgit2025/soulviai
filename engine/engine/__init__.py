# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""
soulviai — 引擎各层架构包
┌─ core/      核心推理链路     perception, comprehend, inference, mind, memory
├─ self/      自我人格体系     self_model, identity, profile, soul_profile
├─ emotion/   情绪羁绊系统     bond, flaws, neurochem, emotional_arc
├─ life/      生命演算系统     life, body, growth, evolution, fate
├─ cognitive/ 高层认知系统     meta_cognition, reasoning, reflection, values
├─ behavior/  行为决策系统     behavior_decider, autonomous, delivery, topics
├─ creative/  创意自发系统     creative_spark, self_play, dream, intuition
└─ social/    社会交互系统     unified_agent, subconscious, sensors, laws
"""
import importlib

_MODULE_MAP = {
    # core/
    'perception':           'engine.core.perception',
    'comprehend_inner':     'engine.core.comprehend_inner',
    'inference':            'engine.core.inference',
    'inner_os':             'engine.core.inner_os',
    'mind':                 'engine.core.mind',
    'thinking':             'engine.core.thinking',
    'memory':               'engine.core.memory',
    'memory_vector':        'engine.core.memory_vector',
    # self/
    'self_model':           'engine.self.self_model',
    'self_narrative':       'engine.self.self_narrative',
    'self_doubt':           'engine.self.self_doubt',
    'self_preservation':    'engine.self.self_preservation',
    'recursive_self':       'engine.self.recursive_self',
    'counterfactual_self':  'engine.self.counterfactual_self',
    'temporal_self':        'engine.self.temporal_self',
    'perceived':            'engine.self.perceived',
    'identity':             'engine.self.identity',
    'soul_profile':         'engine.self.soul_profile',
    'profile':              'engine.self.profile',
    'user_profile':         'engine.self.user_profile',
    'user_persona':         'engine.self.user_persona',
    'user_facts':           'engine.self.user_facts',
    # emotion/
    'bond':                 'engine.emotion.bond',
    'emotion_contagion':    'engine.emotion.emotion_contagion',
    'emotional_arc':        'engine.emotion.emotional_arc',
    'neurochem':            'engine.emotion.neurochem',
    'micro_expressions':    'engine.emotion.micro_expressions',
    'flaws':                'engine.emotion.flaws',
    # life/
    'life':                 'engine.life.life',
    'life_gate':            'engine.life.life_gate',
    'body':                 'engine.life.body',
    'chronos':              'engine.life.chronos',
    'growth':               'engine.life.growth',
    'evolution':            'engine.life.evolution',
    'fate':                 'engine.life.fate',
    # cognitive/
    'meta_cognition':       'engine.cognitive.meta_cognition',
    'meta_evaluator':       'engine.cognitive.meta_evaluator',
    'reasoning_loop':       'engine.cognitive.reasoning_loop',
    'reasoning_memory':     'engine.cognitive.reasoning_memory',
    'reflection':           'engine.cognitive.reflection',
    'consciousness_stream': 'engine.cognitive.consciousness_stream',
    'world_model':          'engine.cognitive.world_model',
    'meaning':              'engine.cognitive.meaning',
    'values':               'engine.cognitive.values',
    # behavior/
    'behavior_decider':     'engine.behavior.behavior_decider',
    'autonomous':           'engine.behavior.autonomous',
    'delivery':             'engine.behavior.delivery',
    'delivery_memory':      'engine.behavior.delivery_memory',
    'projection_learning':  'engine.behavior.projection_learning',
    'intention':            'engine.behavior.intention',
    'prospective':          'engine.behavior.prospective',
    'regret':               'engine.behavior.regret',
    'genuine_hesitation':   'engine.behavior.genuine_hesitation',
    'defense':              'engine.behavior.defense',
    'scenarios':            'engine.behavior.scenarios',
    'binding':              'engine.behavior.binding',
    'experience':           'engine.behavior.experience',
    'feedback':             'engine.behavior.feedback',
    'search':               'engine.behavior.search',
    'topics':               'engine.behavior.topics',
    # creative/
    'creative_spark':       'engine.creative.creative_spark',
    'self_play':            'engine.creative.self_play',
    'thinking_fragments':   'engine.creative.thinking_fragments',
    'timeline':             'engine.creative.timeline',
    'dream':                'engine.creative.dream',
    'intuition':            'engine.creative.intuition',
    'analogy':              'engine.creative.analogy',
    'commitment':           'engine.creative.commitment',
    'humor':                'engine.creative.humor',
    # social/
    'prompt_builder':       'engine.social.prompt_builder',
    'sensors':              'engine.social.sensors',
    'subconscious':         'engine.social.subconscious',
    'laws':                 'engine.social.laws',
    'contradiction_engine': 'engine.social.contradiction_engine',
    'continuity':           'engine.social.continuity',
    'agent_factory':        'engine.social.agent_factory',
    'society_simulator':    'engine.social.society_simulator',
    # society/ (已合并入 social/)
    'collective_pool':      'engine.social.collective_pool',
    'swarm_intelligence':   'engine.social.swarm_intelligence',
    # behavior/ 沙盒
    'behavior_sandbox':     'engine.behavior.behavior_sandbox',
    'curiosity':            'engine.behavior.curiosity',
    # cognitive/ 元记忆
    'meta_memory':          'engine.cognitive.meta_memory',
    # life/ 元维度
    'meta_dimension':       'engine.life.meta_dimension',
}

def __getattr__(name):
    if name in _MODULE_MAP:
        return importlib.import_module(_MODULE_MAP[name])
    raise AttributeError(f"module 'engine' has no attribute '{name}'")
