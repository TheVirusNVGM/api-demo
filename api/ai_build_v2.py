"""
AI Build Logic (Refactored)
3-Layer Architecture:
  Layer 0: Query Planner (AI) → Создаёт план поиска
  Layer 1: Hybrid Search → Выполняет поиск и возвращает кандидатов
  Layer 2: Final Selector (AI) → Финальный отбор модов
"""

from typing import List, Dict
from query_planner import create_search_plan
from hybrid_search import execute_search_plan
from final_selector import select_final_mods, enrich_mods_with_full_data
from pipeline_transparency import create_pipeline
from performance_optimizer import get_performance_optimizer
from architecture_matcher import (
    find_reference_modpacks,
    extract_capability_patterns,
    format_for_ai_context
)


def build_modpack(
    prompt: str,
    mc_version: str,
    mod_loader: str,
    current_mods: List[str],
    max_mods: int,
    fabric_compat_mode: bool,
    deepseek_key: str,
    supabase_url: str,
    supabase_key: str
) -> Dict:
    """
    Собирает модпак используя 3-layer AI архитектуру
    
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
        Dict с выбранными модами и объяснениями
    """
    
    print("="*80)
    print("🚀 Starting AI Modpack Builder (3-Layer Architecture)")
    print("="*80)
    print(f"📝 User Prompt: {prompt}")
    print(f"🎮 Version: {mc_version}, Loader: {mod_loader}")
    print(f"📦 Current mods: {len(current_mods)}, Max new mods: {max_mods}")
    print()
    
    # Создаём pipeline execution для прозрачности
    pipeline = create_pipeline(prompt, mc_version, mod_loader)
    print(f"🆔 Pipeline ID: {pipeline.pipeline_id}")
    print()
    
    # Fabric Compatibility Mode (передан из лаунчера)
    if fabric_compat_mode:
        print("🔧 Fabric Compatibility Mode: ENABLED (user toggled)")
        print("   → Accepting both Fabric and NeoForge/Forge mods")
    else:
        print("🔧 Fabric Compatibility Mode: DISABLED")
        print(f"   → Only accepting {mod_loader} mods")
    print()
    
    # ========================================================================
    # LAYER 0: QUERY PLANNER (AI)
    # ========================================================================
    print("[LAYER 0] Query Planner")
    print("-" * 80)
    
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
    
    # Отслеживаем токены Query Planner
    if '_tokens' in search_plan:
        tokens_info = search_plan['_tokens']
        pipeline.track_ai_call(
            tokens_info['total_tokens'],
            tokens_info['cost_usd']
        )
    
    print()
    
    # ========================================================================
    # LAYER 1: HYBRID SEARCH ENGINE
    # ========================================================================
    print("[LAYER 1] Hybrid Search Engine")
    print("-" * 80)
    
    candidates = execute_search_plan(
        search_plan=search_plan,
        supabase_url=supabase_url,
        supabase_key=supabase_key,
        fabric_compat_mode=fabric_compat_mode  # Передаём параметр!
    )
    
    # Обогащаем candidates layer metadata для performance-запросов
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
    
    # ========================================================================
    # LAYER 1.5: ARCHITECTURE MATCHER (CONDITIONAL)
    # ========================================================================
    reference_context = None
    
    if search_plan.get('use_architecture_matcher', False):
        print("[LAYER 1.5] Architecture Matcher")
        print("-" * 80)
        
        try:
            # Находим reference модпаки
            reference_modpacks = find_reference_modpacks(
                user_prompt=prompt,
                mc_version=mc_version,
                mod_loader=mod_loader,
                supabase_url=supabase_url,
                supabase_key=supabase_key,
                top_n=5
            )
            
            if reference_modpacks:
                # Извлекаем паттерны
                capability_patterns = extract_capability_patterns(reference_modpacks)
                
                # Форматируем для AI контекста
                reference_context = format_for_ai_context(
                    reference_modpacks,
                    capability_patterns,
                    max_context_length=3000
                )
                
                print(f"✅ [Architecture Matcher] Generated reference context ({len(reference_context)} chars)")
            else:
                print("⚠️  [Architecture Matcher] No reference modpacks found")
        
        except Exception as e:
            print(f"❌ [Architecture Matcher] Error: {e}")
            import traceback
            traceback.print_exc()
        
        print()
    else:
        request_type = search_plan.get('request_type', 'unknown')
        print(f"[SKIP] Architecture Matcher (request_type: {request_type})")
        print("-" * 80)
        print("   → Not needed for this type of request")
        print()
    
    # ========================================================================
    # LAYER 2: FINAL SELECTOR (AI)
    # ========================================================================
    print("[LAYER 2] Final Selector")
    print("-" * 80)
    
    result = select_final_mods(
        candidates=candidates,
        user_prompt=prompt,
        current_mods=current_mods,
        max_mods=max_mods,
        deepseek_key=deepseek_key,
        reference_context=reference_context  # Передаём reference архитектуры
    )
    pipeline.set_selected_mods(result['mods'])
    
    # Отслеживаем токены Final Selector
    if '_tokens' in result:
        tokens_info = result['_tokens']
        pipeline.track_ai_call(
            tokens_info['total_tokens'],
            tokens_info['cost_usd']
        )
    
    print()
    
    # ========================================================================
    # PERFORMANCE OPTIMIZATION COVERAGE CHECK (если performance-запрос)
    # ========================================================================
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
    
    # ========================================================================
    # DATA ENRICHMENT (FETCH FULL MOD DATA INCLUDING DEPENDENCIES)
    # ========================================================================
    print("[DATA ENRICHMENT] Fetching full mod data...")
    print("-" * 80)
    
    result['mods'] = enrich_mods_with_full_data(
        selected_mods=result['mods'],
        supabase_url=supabase_url,
        supabase_key=supabase_key
    )
    print()
    
    # ========================================================================
    # FINAL RESULT
    # ========================================================================
    print("="*80)
    print("✅ AI Modpack Builder Complete")
    print("="*80)
    print(f"📦 Selected: {len(result['mods'])} mods")
    if result['explanation']:
        print(f"💡 Explanation: {result['explanation'][:100]}...")
    print()
    print(pipeline.get_summary())
    print()
    
    # Финализируем pipeline и получаем transparency report
    transparency_report = pipeline.finalize()
    
    return {
        'mods': result['mods'],
        'explanation': result['explanation'],
        'prompt': prompt,
        'mc_version': mc_version,
        'mod_loader': mod_loader,
        '_architecture': '3-layer',
        '_search_plan': search_plan.get('strategy'),
        '_candidates_count': len(candidates),
        '_pipeline': transparency_report
    }
