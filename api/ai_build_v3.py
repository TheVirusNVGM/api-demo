"""
AI Build Logic V3 - Architecture-First для themed modpacks
Conditional flow:
  - themed_pack: Architecture Planner → Capability-based search → Architecture-aware selection
  - simple_add/performance: Classic v2 flow
"""

from typing import List, Dict, Optional
import time
from query_planner import create_search_plan
from hybrid_search import execute_search_plan
from final_selector import select_final_mods, enrich_mods_with_full_data
from pipeline_transparency import create_pipeline
from performance_optimizer import get_performance_optimizer
from architecture_planner import (
    find_reference_modpacks,
    extract_capability_patterns,
    plan_architecture
)

# Dashboard integration
try:
    from ws_emitter import emit_stage_started, emit_stage_completed, emit_ai_call, emit_log
    DASHBOARD_ENABLED = True
except ImportError:
    DASHBOARD_ENABLED = False


def build_modpack(
    prompt: str,
    mc_version: str,
    mod_loader: str,
    current_mods: List[str],
    max_mods: int,
    fabric_compat_mode: bool,
    deepseek_key: str,
    supabase_url: str,
    supabase_key: str,
    pipeline_id: Optional[str] = None
) -> Dict:
    """
    Собирает модпак используя architecture-first подход для themed modpacks
    
    Args:
        prompt: Запрос пользователя
        mc_version: Версия Minecraft
        mod_loader: Загрузчик (fabric/forge/neoforge)
        current_mods: Моды уже на доске (project_ids)
        max_mods: Максимум модов для добавления
        deepseek_key: API ключ DeepSeek
        supabase_url: URL Supabase
        supabase_key: Ключ Supabase
    
    Returns:
        Dict с выбранными модами и запланированной архитектурой
    """
    
    print("="*80)
    print("🚀 Starting AI Modpack Builder V3 (Architecture-First)")
    print("="*80)
    print(f"📝 User Prompt: {prompt}")
    print(f"🎮 Version: {mc_version}, Loader: {mod_loader}")
    print(f"📦 Current mods: {len(current_mods)}, Max new mods: {max_mods}")
    print()
    
    pipeline = create_pipeline(prompt, mc_version, mod_loader)
    print(f"🆔 Pipeline ID: {pipeline.pipeline_id}")
    print()
    
    if fabric_compat_mode:
        print("🔧 Fabric Compatibility Mode: ENABLED")
        print("   → Accepting both Fabric and NeoForge/Forge mods")
    else:
        print("🔧 Fabric Compatibility Mode: DISABLED")
        print(f"   → Only accepting {mod_loader} mods")
    print()
    
    # LAYER 0: QUERY PLANNER
    print("[LAYER 0] Query Planner")
    print("-" * 80)
    
    stage_start = time.time()
    
    search_plan = create_search_plan(
        user_prompt=prompt,
        mc_version=mc_version,
        mod_loader=mod_loader,
        current_mods=current_mods,
        max_mods=max_mods,
        deepseek_key=deepseek_key,
        fabric_compat_mode=fabric_compat_mode
    )
    pipeline.set_query_plan(search_plan)
    
    if '_tokens' in search_plan:
        tokens_info = search_plan['_tokens']
        pipeline.track_ai_call(
            tokens_info['total_tokens'],
            tokens_info['cost_usd']
        )
        # Dashboard: Track AI call
        if DASHBOARD_ENABLED and pipeline_id:
            emit_ai_call(
                pipeline_id, "Query Planner", "deepseek", "deepseek-chat",
                tokens_info.get('prompt_tokens', 0),
                tokens_info.get('completion_tokens', 0),
                tokens_info.get('cost_usd', 0),
                tokens_info.get('latency_ms', 0)
            )
    
    # Dashboard: Stage completed
    if DASHBOARD_ENABLED and pipeline_id:
        emit_stage_completed(pipeline_id, "Query Planner", (time.time() - stage_start) * 1000)
    
    request_type = search_plan.get('request_type', 'simple_add')
    print()
    
    # CONDITIONAL FLOW BASED ON REQUEST TYPE
    if request_type == 'themed_pack' and search_plan.get('use_architecture_matcher', False):
        print("🏗️  [V3] THEMED MODPACK FLOW - Architecture-First")
        print("="*80)
        print()
        
        result = build_themed_modpack(
            prompt=prompt,
            mc_version=mc_version,
            mod_loader=mod_loader,
            current_mods=current_mods,
            max_mods=max_mods,
            search_plan=search_plan,
            deepseek_key=deepseek_key,
            supabase_url=supabase_url,
            supabase_key=supabase_key,
            fabric_compat_mode=fabric_compat_mode,
            pipeline=pipeline,
            pipeline_id=pipeline_id
        )
    else:
        print("⚡ [V3] SIMPLE/PERFORMANCE FLOW - Classic")
        print("="*80)
        print()
        
        result = build_simple_modpack(
            prompt=prompt,
            mc_version=mc_version,
            mod_loader=mod_loader,
            current_mods=current_mods,
            max_mods=max_mods,
            search_plan=search_plan,
            deepseek_key=deepseek_key,
            supabase_url=supabase_url,
            supabase_key=supabase_key,
            pipeline=pipeline
        )
    
    print()
    print("="*80)
    print("✅ AI Modpack Builder V3 Complete")
    print("="*80)
    print(f"📦 Selected: {len(result['mods'])} mods")
    if result['explanation']:
        print(f"💡 Explanation: {result['explanation'][:100]}...")
    print()
    print(pipeline.get_summary())
    print()
    
    transparency_report = pipeline.finalize()
    
    return {
        'mods': result['mods'],
        'explanation': result['explanation'],
        'prompt': prompt,
        'mc_version': mc_version,
        'mod_loader': mod_loader,
        'planned_architecture': result.get('planned_architecture'),
        '_architecture': 'v3-conditional',
        '_request_type': request_type,
        '_search_plan': search_plan.get('strategy'),
        '_candidates_count': result.get('_candidates_count', 0),
        '_pipeline': transparency_report
    }


def build_themed_modpack(
    prompt: str,
    mc_version: str,
    mod_loader: str,
    current_mods: List[str],
    max_mods: int,
    search_plan: Dict,
    deepseek_key: str,
    supabase_url: str,
    supabase_key: str,
    fabric_compat_mode: bool,
    pipeline,
    pipeline_id: Optional[str] = None
) -> Dict:
    """
    Architecture-first flow для themed modpacks
    """
    
    # STEP 0: LOAD BASELINE MODS (before architecture planning)
    print("[STEP 0] Baseline Mods Loader")
    print("-" * 80)
    
    from architecture_planner import load_baseline_mods
    
    baseline_mods = load_baseline_mods(
        mc_version=mc_version,
        mod_loader=mod_loader,
        supabase_url=supabase_url,
        supabase_key=supabase_key,
        fabric_compat_mode=fabric_compat_mode
    )
    
    print()
    
    # LAYER 1.5: ARCHITECTURE PLANNER
    print("[LAYER 1.5] Architecture Planner")
    print("-" * 80)
    
    stage_start = time.time()
    if DASHBOARD_ENABLED and pipeline_id:
        emit_stage_started(pipeline_id, "Architecture Planner", "Finding reference modpacks and planning architecture")
    
    try:
        reference_modpacks = find_reference_modpacks(
            user_prompt=prompt,
            mc_version=mc_version,
            mod_loader=mod_loader,
            supabase_url=supabase_url,
            supabase_key=supabase_key,
            top_n=5
        )
        
        if not reference_modpacks:
            print("⚠️  No reference modpacks found - falling back to simple flow")
            return build_simple_modpack(
                prompt, mc_version, mod_loader, current_mods, max_mods,
                search_plan, deepseek_key, supabase_url, supabase_key, pipeline
            )
        
        capability_patterns = extract_capability_patterns(
            reference_modpacks=reference_modpacks,
            baseline_mods=baseline_mods
        )
        
        planned_architecture = plan_architecture(
            user_prompt=prompt,
            reference_modpacks=reference_modpacks,
            capability_patterns=capability_patterns,
            baseline_mods=baseline_mods,
            max_mods=max_mods,
            deepseek_key=deepseek_key
        )
        
        if not planned_architecture:
            print("⚠️  Architecture planning failed - falling back to simple flow")
            return build_simple_modpack(
                prompt, mc_version, mod_loader, current_mods, max_mods,
                search_plan, deepseek_key, supabase_url, supabase_key, pipeline
            )
        
        if '_tokens' in planned_architecture:
            tokens_info = planned_architecture['_tokens']
            pipeline.track_ai_call(
                tokens_info['total_tokens'],
                tokens_info['cost_usd']
            )
            # Dashboard: Track AI call
            if DASHBOARD_ENABLED and pipeline_id:
                emit_ai_call(
                    pipeline_id, "Architecture Planner", "deepseek", "deepseek-chat",
                    tokens_info.get('prompt_tokens', 0),
                    tokens_info.get('completion_tokens', 0),
                    tokens_info.get('cost_usd', 0),
                    tokens_info.get('latency_ms', 0)
                )
        
        # Dashboard: Stage completed
        if DASHBOARD_ENABLED and pipeline_id:
            emit_stage_completed(pipeline_id, "Architecture Planner", (time.time() - stage_start) * 1000)
        
    except Exception as e:
        print(f"❌ [Architecture Planner] Error: {e}")
        import traceback
        traceback.print_exc()
        print("   Falling back to simple flow")
        return build_simple_modpack(
            prompt, mc_version, mod_loader, current_mods, max_mods,
            search_plan, deepseek_key, supabase_url, supabase_key, pipeline
        )
    
    print()
    
    # LAYER 1: HYBRID SEARCH with capability filters from architecture
    print("[LAYER 1] Hybrid Search (capability-filtered)")
    print("-" * 80)
    
    stage_start = time.time()
    if DASHBOARD_ENABLED and pipeline_id:
        emit_stage_started(pipeline_id, "Mod Search", "Searching for relevant mods in database")
    
    # Обогащаем search_plan capability фильтрами из архитектуры
    all_required_caps = []
    all_preferred_caps = []
    
    for category in planned_architecture['categories']:
        all_required_caps.extend(category.get('required_capabilities', []))
        all_preferred_caps.extend(category.get('preferred_capabilities', []))
    
    # BASELINE: Добавляем базовые optimization capabilities ЕСЛИ их нет
    baseline_optimization = ['sim.optimization', 'memory.footprint', 'render.pipeline', 'startup.optimization']
    has_optimization = any(cap in all_required_caps + all_preferred_caps for cap in baseline_optimization)
    
    if not has_optimization:
        # Добавляем оптимизацию в preferred (не обязательно, но желательно)
        all_preferred_caps.extend(baseline_optimization)
        print(f"   🔧 [BASELINE] Added optimization capabilities to search")
    
    search_plan['filters']['required_capabilities'] = list(set(all_required_caps))
    search_plan['filters']['preferred_capabilities'] = list(set(all_preferred_caps))
    
    print(f"   🎯 Required capabilities: {len(search_plan['filters']['required_capabilities'])}")
    print(f"   ⭐ Preferred capabilities: {len(search_plan['filters']['preferred_capabilities'])}")
    
    candidates = execute_search_plan(
        search_plan=search_plan,
        supabase_url=supabase_url,
        supabase_key=supabase_key,
        fabric_compat_mode=fabric_compat_mode  # Передаём параметр!
    )
    
    pipeline.set_candidates(candidates)
    
    # Dashboard: Stage completed
    if DASHBOARD_ENABLED and pipeline_id:
        emit_stage_completed(pipeline_id, "Mod Search", (time.time() - stage_start) * 1000)
        emit_log(pipeline_id, "info", f"Found {len(candidates)} candidate mods", "Mod Search")
    
    print()
    
    if len(candidates) < 5:
        print(f"⚠️  WARNING: Only {len(candidates)} candidates found!")
    
    # LAYER 2: FINAL SELECTOR with architecture awareness
    print("[LAYER 2] Final Selector (architecture-aware)")
    print("-" * 80)
    
    stage_start = time.time()
    if DASHBOARD_ENABLED and pipeline_id:
        emit_stage_started(pipeline_id, "Mod Selection", "Selecting best mods based on architecture")
    
    result = select_final_mods(
        candidates=candidates,
        user_prompt=prompt,
        current_mods=current_mods,
        max_mods=max_mods,
        deepseek_key=deepseek_key,
        reference_context=None,  # Architecture уже передан через planned_architecture
        planned_architecture=planned_architecture,
        baseline_mods=baseline_mods  # Передаём baseline моды для автоматического добавления
    )
    
    pipeline.set_selected_mods(result['mods'])
    
    if '_tokens' in result:
        tokens_info = result['_tokens']
        pipeline.track_ai_call(
            tokens_info['total_tokens'],
            tokens_info['cost_usd']
        )
        # Dashboard: Track AI call
        if DASHBOARD_ENABLED and pipeline_id:
            emit_ai_call(
                pipeline_id, "Mod Selection", "deepseek", "deepseek-chat",
                tokens_info.get('prompt_tokens', 0),
                tokens_info.get('completion_tokens', 0),
                tokens_info.get('cost_usd', 0),
                tokens_info.get('latency_ms', 0)
            )
    
    # Dashboard: Stage completed
    if DASHBOARD_ENABLED and pipeline_id:
        emit_stage_completed(pipeline_id, "Mod Selection", (time.time() - stage_start) * 1000)
        emit_log(pipeline_id, "success", f"Selected {len(result['mods'])} mods", "Mod Selection")
    
    print()
    
    # DATA ENRICHMENT
    print("[DATA ENRICHMENT] Fetching full mod data...")
    print("-" * 80)
    
    if DASHBOARD_ENABLED and pipeline_id:
        emit_log(pipeline_id, "info", "Fetching complete mod data...", "Data Enrichment")
    
    result['mods'] = enrich_mods_with_full_data(
        selected_mods=result['mods'],
        supabase_url=supabase_url,
        supabase_key=supabase_key
    )
    print()
    
    result['planned_architecture'] = planned_architecture
    result['_candidates_count'] = len(candidates)
    
    return result


def build_simple_modpack(
    prompt: str,
    mc_version: str,
    mod_loader: str,
    current_mods: List[str],
    max_mods: int,
    search_plan: Dict,
    deepseek_key: str,
    supabase_url: str,
    supabase_key: str,
    pipeline
) -> Dict:
    """
    Classic v2 flow для simple_add и performance запросов
    """
    
    # LAYER 1: HYBRID SEARCH
    print("[LAYER 1] Hybrid Search Engine")
    print("-" * 80)
    
    candidates = execute_search_plan(
        search_plan=search_plan,
        supabase_url=supabase_url,
        supabase_key=supabase_key,
        fabric_compat_mode=fabric_compat_mode  # Передаём параметр!
    )
    
    # Performance optimization enrichment
    if 'performance' in prompt.lower() or 'optimization' in prompt.lower() or 'fps' in prompt.lower():
        optimizer = get_performance_optimizer()
        candidates = optimizer.enrich_mods_with_layer_info(
            candidates, mod_loader, mc_version
        )
        print(f"   🏷️  Enriched {len([c for c in candidates if c.get('_optimization_layer')])} candidates with layer metadata")
    
    pipeline.set_candidates(candidates)
    print()
    
    if len(candidates) < 5:
        print(f"⚠️  WARNING: Only {len(candidates)} candidates found!")
        print("   This might result in poor selection quality.")
        print()
    
    # LAYER 2: FINAL SELECTOR
    print("[LAYER 2] Final Selector")
    print("-" * 80)
    
    result = select_final_mods(
        candidates=candidates,
        user_prompt=prompt,
        current_mods=current_mods,
        max_mods=max_mods,
        deepseek_key=deepseek_key,
        reference_context=None
    )
    pipeline.set_selected_mods(result['mods'])
    
    if '_tokens' in result:
        tokens_info = result['_tokens']
        pipeline.track_ai_call(
            tokens_info['total_tokens'],
            tokens_info['cost_usd']
        )
    
    print()
    
    # PERFORMANCE OPTIMIZATION COVERAGE CHECK
    if 'performance' in prompt.lower() or 'optimization' in prompt.lower() or 'fps' in prompt.lower():
        print("[PERFORMANCE OPTIMIZATION] Coverage check...")
        print("-" * 80)
        
        optimizer = get_performance_optimizer()
        result['mods'], coverage_reasons = optimizer.ensure_minimum_coverage(
            selected_mods=result['mods'],
            candidates=candidates,
            mod_loader=mod_loader,
            mc_version=mc_version,
            max_additions=min(10, max_mods - len(result['mods']))
        )
        
        if coverage_reasons:
            pipeline.reasons_chosen.update({
                reason.split(' ')[1]: reason for reason in coverage_reasons
            })
        
        print()
    
    # DATA ENRICHMENT
    print("[DATA ENRICHMENT] Fetching full mod data...")
    print("-" * 80)
    
    result['mods'] = enrich_mods_with_full_data(
        selected_mods=result['mods'],
        supabase_url=supabase_url,
        supabase_key=supabase_key
    )
    print()
    
    result['_candidates_count'] = len(candidates)
    
    return result
