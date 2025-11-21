"""
Main Crash Doctor Analysis Pipeline
Объединяет все компоненты для полного анализа краша
"""

from typing import Dict, Optional
from .log_sanitizer import sanitize_crash_log, sanitize_game_log, extract_crash_info
from .crash_analyzer import analyze_crash, validate_analysis
from .fix_planner import plan_fixes
from .board_patcher import create_patched_board_state


def analyze_and_fix_crash(
    crash_log: str,
    board_state: Dict,
    game_log: Optional[str] = None,
    mc_version: Optional[str] = None,
    mod_loader: Optional[str] = None,
    deepseek_key: str = None
) -> Dict:
    """
    Полный pipeline анализа и исправления краша
    
    Args:
        crash_log: Сырой crash log
        board_state: Текущее состояние доски (формат как в /api/feedback)
        game_log: Опциональный game log (latest.log)
        mc_version: Версия MC (опционально, будет извлечена из лога)
        mod_loader: Загрузчик (опционально, будет извлечён из лога)
        deepseek_key: API ключ DeepSeek
        
    Returns:
        Dict с результатом: success, suggestions, patched_board_state, confidence, token_usage, warnings
    """
    
    print("=" * 80)
    print("🩺 [Crash Doctor] Starting crash analysis...")
    print("=" * 80)
    
    # 1. Санитизация логов
    print("\n📝 [Step 1] Sanitizing logs...")
    
    # Проверяем, есть ли crash report или только game log
    has_crash_report = bool(crash_log and len(crash_log) > 100 and ('Exception' in crash_log or 'Crash Report' in crash_log or '--' in crash_log[:500]))
    
    if not has_crash_report and game_log:
        print("   ⚠️  No crash report found - analyzing game log instead")
        # Используем game log как основной источник
        sanitized_result = sanitize_crash_log(game_log, max_length=20000)
        sanitized_crash_log = sanitized_result['sanitized_log']
        extracted_info = sanitized_result['extracted_info']
        # Также санитизируем game log отдельно для передачи в analyze_crash
        sanitized_game_log = sanitize_game_log(game_log, max_length=10000)
    else:
        sanitized_result = sanitize_crash_log(crash_log, max_length=20000)
        sanitized_crash_log = sanitized_result['sanitized_log']
        extracted_info = sanitized_result['extracted_info']
        
        # Санитизируем game log если есть
        sanitized_game_log = None
        if game_log:
            sanitized_game_log = sanitize_game_log(game_log, max_length=10000)
            print(f"   ✅ Game log sanitized: {len(game_log)} → {len(sanitized_game_log)} chars")
    
    # Используем переданные mc_version/mod_loader или извлечённые из лога
    final_mc_version = mc_version or extracted_info.get('mc_version')
    final_mod_loader = mod_loader or extracted_info.get('mod_loader', 'fabric')
    
    # 2. Анализ через LLM
    print("\n🧠 [Step 2] Analyzing crash with LLM...")
    print(f"   📋 Error type: {extracted_info.get('error_type', 'unknown')}")
    print(f"   🔧 Loader: {final_mod_loader}, MC: {final_mc_version}")
    
    analysis = analyze_crash(
        sanitized_crash_log=sanitized_crash_log,
        game_log=sanitized_game_log,
        board_state=board_state,
        extracted_info=extracted_info,
        deepseek_key=deepseek_key,
        mc_version=final_mc_version,
        mod_loader=final_mod_loader
    )
    
    if not analysis.get('success'):
        error_msg = analysis.get('error', 'Failed to analyze crash')
        print(f"\n❌ [CRASH DOCTOR] Analysis failed: {error_msg}")
        
        # Логируем детали ошибки если есть
        if 'raw_response' in analysis:
            print(f"   📋 Raw LLM response (first 500 chars): {analysis.get('raw_response', '')[:500]}")
        if 'json_extract' in analysis:
            print(f"   📋 Extracted JSON (first 500 chars): {analysis.get('json_extract', '')[:500]}")
        if 'parse_attempts' in analysis:
            print(f"   📋 Parse attempts: {analysis.get('parse_attempts', [])}")
        if 'response_length' in analysis:
            print(f"   📋 Response length: {analysis.get('response_length', 0)} chars")
        
        return {
            'success': False,
            'error': error_msg,
            'suggestions': [],
            'confidence': 0.0,
            'debug_info': {
                'raw_response': analysis.get('raw_response', '')[:1000],
                'json_extract': analysis.get('json_extract', '')[:500] if 'json_extract' in analysis else None,
                'parse_attempts': analysis.get('parse_attempts', []),
                'response_length': analysis.get('response_length', 0)
            }
        }
    
    # Проверяем валидность анализа
    if not validate_analysis(analysis):
        return {
            'success': False,
            'error': 'Analysis confidence too low or no fixes suggested',
            'confidence': analysis.get('confidence', 0.0),
            'suggestions': []
        }
    
    token_usage = analysis.get('token_usage', {})
    print(f"   ✅ Analysis complete: confidence={analysis.get('confidence', 0.0):.2f}")
    print(f"   ✅ Root cause: {analysis.get('root_cause', 'Unknown')}")
    print(f"   ✅ Tokens used: {token_usage.get('total_tokens', 0)}")
    
    # 3. Планирование фиксов
    print("\n📋 [Step 3] Planning fixes...")
    fix_plan = plan_fixes(analysis, board_state, mc_version=final_mc_version, mod_loader=final_mod_loader, extracted_info=extracted_info)
    
    print(f"   ✅ Planned {fix_plan['total_fixes']} fixes")
    print(f"   ✅ Estimated success probability: {fix_plan['estimated_success_probability']:.2f}")
    if fix_plan.get('warnings'):
        print(f"   ⚠️  {len(fix_plan['warnings'])} warnings")
    
    # 4. Создание patched board_state
    print("\n🔧 [Step 4] Creating patched board_state...")
    patched_result = create_patched_board_state(
        original_board_state=board_state,
        fix_plan=fix_plan,
        mc_version=final_mc_version,
        mod_loader=final_mod_loader
    )
    
    applied_ops = patched_result['applied_operations']
    failed_ops = patched_result['failed_operations']
    
    print(f"   ✅ Applied {len(applied_ops)} operations")
    if failed_ops:
        print(f"   ⚠️  {len(failed_ops)} operations failed")
    
    # Формируем финальный результат
    result = {
        'success': True,
        'root_cause': analysis.get('root_cause', 'Unknown'),
        'error_category': analysis.get('error_category', 'unknown'),
        'confidence': analysis.get('confidence', 0.0),
        'suggestions': [
            {
                'action': op.get('action'),
                'target_mod': op.get('target_mod', op.get('mod', 'Unknown')),
                'reason': op.get('reason', ''),
                'priority': op.get('priority', 'medium'),
                'confidence': op.get('confidence', 0.5),
                'success': op.get('success', True),
                'mod_source_id': op.get('mod_source_id'),  # Добавляем mod_source_id
                'mod_slug': op.get('mod_slug'),  # Добавляем mod_slug
                # Для update_mod добавляем информацию об обновлении
                'file_url': op.get('file_url'),
                'latest_filename': op.get('latest_filename'),
                'latest_version': op.get('latest_version')
            }
            for op in fix_plan.get('operations', [])
        ],
        'patched_board_state': patched_result['patched_board_state'],
        'fix_summary': {
            'total_fixes': fix_plan['total_fixes'],
            'applied_operations': len(applied_ops),
            'failed_operations': len(failed_ops),
            'mods_removed': patched_result['total_mods_removed'],
            'mods_disabled': patched_result['total_mods_disabled'],
            'estimated_success_probability': fix_plan['estimated_success_probability']
        },
        'token_usage': token_usage,
        'warnings': fix_plan.get('warnings', []) + [f"Failed: {op['action']} on {op['target']}" for op in failed_ops],
        'extracted_info': extracted_info
    }
    
    print("\n" + "=" * 80)
    print("✅ [Crash Doctor] Analysis complete!")
    print("=" * 80)
    
    return result

