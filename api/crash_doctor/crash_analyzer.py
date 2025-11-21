"""
Crash Analyzer
Анализирует crash logs через LLM и определяет причины крашей
"""

from typing import Dict, List, Optional
import requests
import json
import re
from .unified_sanitizer import create_unified_crash_data


def analyze_crash(
    sanitized_crash_log: str,
    game_log: Optional[str],
    board_state: Dict,
    extracted_info: Dict,
    deepseek_key: str,
    mc_version: Optional[str] = None,
    mod_loader: Optional[str] = None
) -> Dict:
    """
    Анализирует краш через LLM и определяет причины
    
    Args:
        sanitized_crash_log: Очищенный crash log
        game_log: Опциональный game log (latest.log)
        board_state: Текущее состояние доски с модами
        extracted_info: Информация, извлечённая из лога (loader, version, exception)
        deepseek_key: API ключ DeepSeek
        
    Returns:
        Dict с анализом: root_cause, confidence, suggested_fixes, conflicting_mods
    """
    
    # Создаём единый структурированный JSON со всеми данными
    unified_data = create_unified_crash_data(
        sanitized_crash_log=sanitized_crash_log,
        board_state=board_state,
        sanitized_game_log=game_log,
        extracted_info=extracted_info,
        mc_version=mc_version,
        mod_loader=mod_loader
    )
    
    mods_list = unified_data.get('mods', [])
    crash_info = unified_data.get('crash_info', {})
    
    # Логируем размеры данных для отладки
    crash_log_size = len(unified_data.get('crash_log', ''))
    game_log_size = len(unified_data.get('game_log', '')) if unified_data.get('game_log') else 0
    unified_json_size = len(json.dumps(unified_data, ensure_ascii=False))
    
    print(f"   📦 Extracted {len(mods_list)} mods from board_state (categories/metadata filtered out)")
    print(f"   📊 Unified JSON size: {unified_json_size:,} chars (crash_log: {crash_log_size:,}, game_log: {game_log_size:,}, mods: {len(mods_list)})")
    
    # Формируем промпт для LLM
    system_prompt = """You are an expert Minecraft modpack crash analyzer. Your task is to analyze crash logs and identify the root cause of crashes.

TASK:
1. Read and understand the ENTIRE crash log carefully
2. Identify ALL types of problems (missing dependencies, mod conflicts, version incompatibilities, memory issues, runtime errors, etc.)
3. Determine which mod(s) are involved in each problem
4. Suggest specific, actionable fixes for EACH problem found
5. Prioritize fixes by severity (critical issues first)
6. Provide confidence level for each suggestion

RULES:
- Read the crash log THOROUGHLY - don't skip sections
- If there's NO crash report (log ends abruptly), analyze the GAME LOG instead
- Look for patterns:
  * "-- Mod loading issue for: X --" and "Failure message:" - missing dependencies or conflicts
  * "Mod X requires Y" and "Currently, Y is not installed" - missing dependency (ADD Y, don't remove X)
  * "incompatible", "conflict" - mod conflicts (may need to remove one or find alternative)
  * Exception stack traces - runtime errors (may indicate mod bugs or conflicts)
  * "OutOfMemoryError" - memory issues (may need to increase RAM or remove resource-heavy mods)
  * Version mismatches - mod incompatible with MC version or loader
  * "ClassNotFoundException" or "NoClassDefFoundError" - missing classes (often mixin/transformation issues)
  * "@Mixin target X was not found" - mixin transformation failed (Connector/Fabric mod compatibility issue)
  * "Error loading class: X" - class loading failure (often with Connector trying to load Fabric mods)
  * "is a Fabric mod and cannot be loaded" - Fabric mod on NeoForge/Forge without proper Connector support
  * "Skipping jar. File mods\\X.jar is a Fabric mod" - Fabric mod detected but skipped by loader
- Be specific: use exact mod IDs from the crash log (from "Mod loading issue for: [mod_id]" sections)
- For missing dependencies: ADD the missing mod, don't remove the one that needs it
- For conflicts: suggest removing one of the conflicting mods or finding alternatives
- For runtime errors: check if it's a known bug or conflict
- For mixin/class loading errors with Connector: suggest REMOVING the incompatible Fabric mod (don't suggest replacing)
- IMPORTANT: If you see Connector-related errors (mixin errors, class loading failures, "@Mixin target X was not found", "Error loading class", "connectorextras"), suggest clearing the Connector cache:
  * Add a fix with action="clear_connector_cache", target_mod=".connector", reason="Clear Connector cache to reset mixin transformations", priority="high"
- For outdated mods causing crashes: suggest "update_mod" if a newer version exists (check Modrinth)
- DO NOT suggest "replace_mod" - instead suggest "remove_mod" for incompatible mods or "update_mod" for outdated ones
- Think logically: what is the root cause? What would fix it?

OUTPUT FORMAT (JSON only, no markdown):
{
  "root_cause": "Brief description of the main issue",
  "confidence": 0.0-1.0,
  "error_category": "mod_conflict" | "missing_dependency" | "outdated_mod" | "memory" | "mixin_error" | "class_not_found" | "fabric_mod_on_neoforge" | "unknown",
  "problematic_mods": [
    {
      "mod_name": "Exact mod name from the list",
      "mod_slug": "mod-slug if available",
      "reason": "Why this mod is problematic",
      "action_required": "remove" | "update" | "replace" | "disable"
    }
  ],
  "missing_dependencies": [
    {
      "mod_id": "modrinth_slug_or_id",
      "mod_name": "Required mod name (from crash log)",
      "required_by": "Mod that needs it",
      "version_requirement": "1.3.2 or above",
      "reason": "Why it's needed",
      "priority": "critical"  // Always critical for missing deps
    }
  ],
  "suggested_fixes": [
    {
      "action": "remove_mod" | "add_mod" | "disable_mod" | "enable_fabric_compat" | "update_mod" | "clear_connector_cache",
      "target_mod": "Exact mod name from the MOD LIST above (or '.connector' for clear_connector_cache)",
      "reason": "Why this fix should work",
      "priority": "critical" | "high" | "medium" | "low"
    }
  ],
  "additional_info": "Any other relevant information"
}

CRITICAL RULES - READ CAREFULLY:
- ONLY suggest fixes for mods that EXIST in the MOD LIST provided above
- DO NOT suggest adding mods that are not explicitly mentioned in the crash log or mod list
- DO NOT suggest "replace_mod" - use "remove_mod" or "update_mod" instead
- For "update_mod": only suggest if the mod is outdated and causing issues (check if newer version exists)
- For Fabric mods on NeoForge: suggest REMOVING the Fabric mod, NOT replacing it (unless explicitly stated in log)
- For missing dependencies: ONLY suggest adding if the dependency is EXPLICITLY mentioned in the crash log
- DO NOT invent mod names or suggest mods that might not exist
- If a mod is causing issues and you're not sure about a fix, suggest REMOVING it rather than replacing/updating
- Be conservative: it's better to suggest fewer, accurate fixes than many incorrect ones

IMPORTANT:
- Analyze ALL problems in the log, not just the first one you see
- Different problems may require different fixes - address each one
- If you see "Mod X requires Y" and "Currently, Y is not installed": fix is to ADD Y (not remove X) - BUT ONLY if Y is explicitly mentioned
- CRITICAL: If the crash log says "Currently, X is not installed" or "X is not installed", DO NOT suggest removing X - it's already not installed! Only suggest ADDING it if it's required.
- If you see mod conflicts: suggest REMOVING one conflicting mod (don't suggest replacements unless explicitly stated)
- If you see "is a Fabric mod and cannot be loaded" or "Skipping jar...Fabric mod": suggest REMOVING that mod ONLY if it's actually installed (check the mod list)
- If you see runtime exceptions: analyze the stack trace to understand what went wrong
- If you see memory errors: suggest increasing RAM allocation or removing resource-heavy mods
- Extract mod IDs from crash log sections (e.g., "Mod loading issue for: [mod_id]")
- Check the board_state mod list to see what mods are currently installed
- ONLY suggest fixes for mods that are ACTUALLY in the mod list or crash log
- DO NOT suggest removing a mod if the crash log explicitly says it's "not installed" - this is contradictory
- Confidence should reflect how clear the problem is:
  * 0.9+ for explicitly stated issues (e.g., "Mod X requires Y")
  * 0.7-0.8 for likely issues based on error patterns
  * 0.5-0.6 for inferred issues (be conservative)
"""
    
    # Формируем единый JSON для отправки в LLM
    has_crash_report = crash_info.get('has_crash_report', False)
    
    user_prompt = f"""CRASH ANALYSIS DATA (JSON):

{json.dumps(unified_data, indent=2, ensure_ascii=False)}

⚠️ CRITICAL: You can ONLY suggest fixes for mods that are in the "mods" array above.
DO NOT suggest adding mods that are not in this list UNLESS they are explicitly mentioned as missing dependencies in the crash log.
DO NOT invent mod names or suggest mods that might not exist.

{"⚠️ IMPORTANT: This is a GAME LOG, not a crash report. The game crashed during loading before generating a crash report. Look for mixin errors, class loading failures, and Connector compatibility issues." if not has_crash_report else ""}

Analyze this data COMPLETELY and identify ALL problems. The crash_log and game_log contain all necessary information - read them carefully.

Provide fixes for EVERY problem you find, not just the first one. Think step by step:
1. What errors are shown in the log?
2. What mods are involved?
3. What is the root cause?
4. What fix would resolve it?
5. Are there multiple problems that need multiple fixes?

Be thorough and systematic."""
    
    try:
        response = requests.post(
            'https://api.deepseek.com/v1/chat/completions',
            headers={
                'Authorization': f'Bearer {deepseek_key}',
                'Content-Type': 'application/json'
            },
            json={
                'model': 'deepseek-chat',
                'messages': [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_prompt}
                ],
                'temperature': 0.3,  # Низкая температура для точности
                'max_tokens': 4000  # Увеличено до 4000 для больших анализов с множеством модов
            },
            timeout=180  # Увеличен до 180 секунд для больших краш-логов
        )
        
        if response.status_code != 200:
            return {
                'success': False,
                'error': f'DeepSeek API error: {response.status_code}',
                'root_cause': 'Failed to analyze crash'
            }
        
        result = response.json()
        content = result['choices'][0]['message']['content']
        
        print(f"   📥 [LLM Response] Received {len(content)} chars from LLM")
        
        # Извлекаем JSON из ответа (может быть в markdown code block)
        json_match = None
        parse_attempts = []
        use_group_1 = False  # Флаг: использовать group(1) или group(0)
        
        # Попытка 1: ищем ```json блок
        if '```json' in content:
            json_match = re.search(r'```json\s*(\{.*?\})\s*```', content, re.DOTALL)
            parse_attempts.append("```json code block")
            if json_match:
                use_group_1 = True
                print(f"   ✅ Found JSON in ```json code block")
        
        # Попытка 2: ищем обычный ``` блок
        if not json_match and '```' in content:
            json_match = re.search(r'```\s*(\{.*?\})\s*```', content, re.DOTALL)
            parse_attempts.append("``` code block")
            if json_match:
                use_group_1 = True
                print(f"   ✅ Found JSON in ``` code block")
        
        # Попытка 3: ищем просто JSON объект
        if not json_match:
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            parse_attempts.append("plain JSON object")
            if json_match:
                use_group_1 = False  # Для plain JSON используем group(0)
                print(f"   ✅ Found JSON object in plain text")
        
        if json_match:
            try:
                # Для ``` блоков используем group(1), для plain JSON - group(0)
                json_str = json_match.group(1) if use_group_1 else json_match.group(0)
                print(f"   📋 Extracted JSON string ({len(json_str)} chars)")
                
                # Пытаемся распарсить JSON
                analysis = json.loads(json_str)
                
                # Добавляем usage info
                usage = result.get('usage', {})
                analysis['token_usage'] = {
                    'prompt_tokens': usage.get('prompt_tokens', 0),
                    'completion_tokens': usage.get('completion_tokens', 0),
                    'total_tokens': usage.get('total_tokens', 0)
                }
                
                analysis['success'] = True
                print(f"   ✅ Successfully parsed LLM response")
                return analysis
            except json.JSONDecodeError as e:
                print(f"   ❌ JSON decode error: {e}")
                print(f"   📋 JSON string (first 500 chars): {json_str[:500]}")
                print(f"   📋 JSON decode error details: {e.msg} at line {e.lineno}, column {e.colno}")
                
                # Показываем контекст вокруг ошибки
                lines = json_str.split('\n')
                error_line_idx = e.lineno - 1
                context_start = max(0, error_line_idx - 3)
                context_end = min(len(lines), error_line_idx + 4)
                print(f"   📋 Context around error (lines {context_start+1}-{context_end}):")
                for i in range(context_start, context_end):
                    marker = ">>> " if i == error_line_idx else "    "
                    print(f"   {marker}{i+1}: {lines[i]}")
                
                # Проверяем, не обрезан ли JSON (LLM достиг лимита токенов)
                # Если JSON обрезан - не пытаемся "угадывать" что хотел сказать LLM
                # Это может привести к некорректному анализу
                open_braces = json_str.count('{')
                close_braces = json_str.count('}')
                open_brackets = json_str.count('[')
                close_brackets = json_str.count(']')
                
                is_truncated = (open_braces > close_braces) or (open_brackets > close_brackets)
                
                if is_truncated:
                    print(f"   ⚠️  JSON appears to be truncated (LLM hit token limit)")
                    print(f"   📊 Unclosed structures: {open_braces - close_braces} braces, {open_brackets - close_brackets} brackets")
                    print(f"   💡 Suggestion: Reduce number of mods or increase max_tokens limit")
                
                return {
                    'success': False,
                    'error': f'Failed to parse JSON: {str(e)}',
                    'error_details': f'{e.msg} at line {e.lineno}, column {e.colno}',
                    'raw_response': content[:2000],
                    'json_extract': json_str[:1000],
                    'json_extract_end': json_str[-500:] if len(json_str) > 500 else json_str,
                    'parse_attempts': parse_attempts,
                    'json_length': len(json_str)
                }
        else:
            print(f"   ❌ Failed to find JSON in LLM response")
            print(f"   📋 Tried patterns: {', '.join(parse_attempts)}")
            print(f"   📋 Response preview (first 1000 chars):")
            print(f"   {content[:1000]}")
            print(f"   📋 Response preview (last 500 chars):")
            print(f"   {content[-500:]}")
            return {
                'success': False,
                'error': 'Failed to parse LLM response - no JSON found',
                'raw_response': content[:2000],
                'response_length': len(content),
                'parse_attempts': parse_attempts
            }
            
    except requests.exceptions.Timeout as e:
        print(f"   ❌ Request timeout: {e}")
        return {
            'success': False,
            'error': f'Request timeout: {str(e)}',
            'root_cause': 'LLM request timed out - try again or reduce log size'
        }
    except Exception as e:
        print(f"   ❌ Exception during analysis: {e}")
        import traceback
        print(f"   📋 Traceback: {traceback.format_exc()}")
        return {
            'success': False,
            'error': str(e),
            'root_cause': 'Exception during analysis'
        }


def validate_analysis(analysis: Dict) -> bool:
    """Проверяет что анализ валиден и имеет достаточную уверенность"""
    if not analysis.get('success'):
        return False
    
    confidence = analysis.get('confidence', 0.0)
    if confidence < 0.5:
        return False
    
    # Должен быть хотя бы один suggested_fix
    fixes = analysis.get('suggested_fixes', [])
    if len(fixes) == 0:
        return False
    
    return True

