"""
Feedback Processor
Обрабатывает пользовательские жалобы на моды и автоматически обновляет БД
"""

import json
import requests
from typing import Dict, Optional


def process_feedback(
    feedback_text: str,
    board_state: Dict,
    deepseek_key: str,
    supabase_url: str,
    supabase_key: str
) -> Dict:
    """
    Обрабатывает пользовательский фидбек о проблеме с модами
    
    Args:
        feedback_text: Текст жалобы пользователя
        board_state: Текущее состояние доски (список модов)
        deepseek_key: API ключ Deepseek
        supabase_url: URL Supabase
        supabase_key: Ключ Supabase
    
    Returns:
        Dict с результатом обработки
    """
    print("=" * 80)
    print("🔍 [Feedback Processor] Analyzing user feedback...")
    print("=" * 80)
    print(f"Feedback: {feedback_text}")
    print()
    
    # Извлекаем названия модов из board_state
    mods_list = []
    if 'mods' in board_state:
        mods_list = [
            {
                'name': mod.get('title'),
                'source_id': mod.get('source_id')  # Modrinth ID мода
            }
            for mod in board_state['mods']
        ]
    
    # Формируем промпт для AI
    system_prompt = """You are an expert mod compatibility analyzer. Your task is to analyze user feedback about mod incompatibilities and extract structured data.

TASK:
1. Determine the type of feedback:
   a) INCOMPATIBILITY: Two or more mods don't work together
   b) OUTDATED_MOD: A specific mod is outdated, abandoned, or problematic
2. Extract relevant mods and reasons
3. Return structured JSON

RULES:
- Process BOTH incompatibility AND outdated mod feedback
- For INCOMPATIBILITY: Extract both mods involved and relationship
- For OUTDATED_MOD: Extract single mod and reason (outdated, abandoned, doesn't work with modern mods, causes crashes, etc.)
- Ignore general complaints, feature requests, or vague bugs
- Be conservative: only flag clear issues
- IMPORTANT: If user says "Mod A is incompatible with Mod B", then:
  * incompatible_mods should contain BOTH Mod A and Mod B
  * affected_mods should also contain BOTH Mod A and Mod B
  * This creates bidirectional incompatibility relationship

OUTPUT FORMAT (JSON only, no markdown):
{
  "valid": true/false,
  "feedback_type": "incompatibility" | "outdated_mod",
  "incompatible_mods": [  // For incompatibility feedback
    {
      "mod_name": "Exact mod name from the list",
      "reason": "Clear reason why it's incompatible"
    }
  ],
  "affected_mods": ["Mod Name 1", "Mod Name 2"],  // For incompatibility feedback
  "outdated_mods": [  // For outdated mod feedback
    {
      "mod_name": "Exact mod name from the list",
      "reason": "outdated" | "abandoned" | "doesn't work with modern mods" | "causes crashes" | "replaced by better alternative"
    }
  ],
  "confidence": 0.0-1.0
}

IMPORTANT: Extract mod loader information if mentioned!
- If feedback mentions "on NeoForge", "on Fabric", "on Forge" - extract it
- If no loader mentioned, assume incompatibility is global (all loaders)

EXAMPLE 1:
Feedback: "Fabric API crashes with Forgified Fabric API"
Output: {
  "valid": true,
  "incompatible_mods": [
    {"mod_name": "Fabric API", "reason": "Crashes with Forgified Fabric API"},
    {"mod_name": "Forgified Fabric API", "reason": "Crashes with Fabric API"}
  ],
  "affected_mods": ["Fabric API", "Forgified Fabric API"],
  "loaders": null,
  "confidence": 0.95
}

EXAMPLE 2:
Feedback: "Nvidium doesn't work with Sodium on NeoForge"
Output: {
  "valid": true,
  "feedback_type": "incompatibility",
  "incompatible_mods": [
    {"mod_name": "Nvidium", "reason": "Doesn't work with Sodium on NeoForge"},
    {"mod_name": "Sodium", "reason": "Doesn't work with Nvidium on NeoForge"}
  ],
  "affected_mods": ["Nvidium", "Sodium"],
  "loaders": ["neoforge"],
  "confidence": 0.9
}

EXAMPLE 3:
Feedback: "OptiFine is outdated and doesn't work with modern mods"
Output: {
  "valid": true,
  "feedback_type": "outdated_mod",
  "outdated_mods": [
    {"mod_name": "OptiFine", "reason": "outdated, doesn't work with modern mods"}
  ],
  "confidence": 0.95
}

EXAMPLE 4:
Feedback: "This mod is abandoned by the author and causes crashes"
Output: {
  "valid": true,
  "feedback_type": "outdated_mod",
  "outdated_mods": [
    {"mod_name": "<inferred from context>", "reason": "abandoned, causes crashes"}
  ],
  "confidence": 0.85
}"""
    
    mods_context = "\n".join([f"- {m['name']} (id: {m['source_id']})" for m in mods_list[:50]])
    
    user_message = f"""USER FEEDBACK: "{feedback_text}"

MODS ON BOARD:
{mods_context}

Analyze this feedback and determine:
1. Is this about mod incompatibility? (yes/no)
2. Which specific mod(s) are incompatible?
3. Why are they incompatible?

Return JSON format only."""
    
    try:
        # Отправляем в Deepseek
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
                    {'role': 'user', 'content': user_message}
                ],
                'temperature': 0.1,  # Низкая температура для точности
                'max_tokens': 1000
            },
            timeout=30
        )
        
        if response.status_code != 200:
            return {
                'success': False,
                'error': f'Deepseek API error: {response.status_code}'
            }
        
        result = response.json()
        content = result['choices'][0]['message']['content'].strip()
        
        # Парсим JSON
        content = content.replace('```json', '').replace('```', '').strip()
        
        # Ищем JSON в ответе
        import re
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if not json_match:
            return {
                'success': False,
                'error': 'Could not parse AI response'
            }
        
        analysis = json.loads(json_match.group())
        
        print(f"📥 [AI Analysis] Valid: {analysis.get('valid')}, Confidence: {analysis.get('confidence')}")
        
        if not analysis.get('valid') or analysis.get('confidence', 0) < 0.7:
            print("⚠️  [Feedback Processor] Low confidence or invalid feedback")
            return {
                'success': False,
                'reason': 'Feedback is not about incompatibilities or confidence too low',
                'analysis': analysis
            }
        
        # Обрабатываем валидный фидбек
        feedback_type = analysis.get('feedback_type', 'incompatibility')
        incompatible_mods = analysis.get('incompatible_mods', [])
        affected_mods = analysis.get('affected_mods', [])
        outdated_mods = analysis.get('outdated_mods', [])
        loaders = analysis.get('loaders')  # None или ['neoforge', 'fabric', ...]
        
        print(f"📊 [AI Analysis] Feedback type: {feedback_type}")
        print(f"📊 [AI Analysis] Incompatible mods: {incompatible_mods}")
        print(f"📊 [AI Analysis] Affected mods: {affected_mods}")
        print(f"📊 [AI Analysis] Outdated mods: {outdated_mods}")
        print(f"📊 [AI Analysis] Loaders: {loaders if loaders else 'all (global)'}")
        
        if not incompatible_mods and not outdated_mods:
            return {
                'success': False,
                'reason': 'No incompatible or outdated mods identified'
            }
        
        if feedback_type == 'outdated_mod':
            print(f"✅ [Feedback Processor] Found {len(outdated_mods)} outdated mod(s)")
            
            # Проверяем GOD MODE (фидбек начинается с "GOD***")
            is_god_mode = feedback_text.strip().upper().startswith('GOD***')
            if is_god_mode:
                print(f"👑 [GOD MODE DETECTED] Admin override - instant blacklist")
            
            # Обновляем БД для устаревших модов
            updates_made = []
            
            for outdated_mod in outdated_mods:
                mod_name = outdated_mod['mod_name']
                reason = outdated_mod['reason']
                
                # Находим source_id мода по имени
                matching_mod = None
                
                # 1. Сначала ищем точное совпадение
                for m in mods_list:
                    if m['name'] and mod_name and m['name'].lower() == mod_name.lower():
                        matching_mod = m
                        break
                
                # 2. Если не нашли, ищем fuzzy
                if not matching_mod:
                    for m in mods_list:
                        if m['name'] and mod_name and (m['name'].lower() in mod_name.lower() or mod_name.lower() in m['name'].lower()):
                            matching_mod = m
                            break
                
                if not matching_mod:
                    print(f"   ⚠️  Mod '{mod_name}' not found on board, skipping")
                    continue
                
                if not matching_mod.get('source_id'):
                    print(f"   ⚠️  Mod '{mod_name}' has no source_id, skipping")
                    continue
                
                # Добавляем отметку "outdated" в incompatibilities
                success = mark_mod_as_outdated(
                    mod_source_id=matching_mod['source_id'],
                    reason=reason,
                    supabase_url=supabase_url,
                    supabase_key=supabase_key,
                    is_god_mode=is_god_mode
                )
                
                if success:
                    updates_made.append({
                        'mod': matching_mod['name'],
                        'action': 'marked_as_outdated',
                        'reason': reason
                    })
                    print(f"   ✅ Marked {matching_mod['name']} as outdated")
            
            return {
                'success': True,
                'feedback_type': 'outdated_mod',
                'outdated_mods': outdated_mods,
                'analysis': analysis,
                'updates_made': updates_made
            }
        
        print(f"✅ [Feedback Processor] Found {len(incompatible_mods)} incompatible mod(s)")
        
        # Применяем изменения в БД
        updates_made = []
        
        for incompat_mod in incompatible_mods:
            mod_name = incompat_mod['mod_name']
            reason = incompat_mod['reason']
            
            # Находим source_id мода по имени (exact match сначала, потом fuzzy)
            matching_mod = None
            
            # 1. Сначала ищем точное совпадение
            for m in mods_list:
                if m['name'] and mod_name and m['name'].lower() == mod_name.lower():
                    matching_mod = m
                    break
            
            # 2. Если не нашли, ищем fuzzy
            if not matching_mod:
                for m in mods_list:
                    if m['name'] and mod_name and (m['name'].lower() in mod_name.lower() or mod_name.lower() in m['name'].lower()):
                        matching_mod = m
                        break
            
            if not matching_mod:
                print(f"   ⚠️  Mod '{mod_name}' not found on board, skipping")
                continue
            
            if not matching_mod.get('source_id'):
                print(f"   ⚠️  Mod '{mod_name}' has no source_id, skipping")
                continue
            
            # Находим affected моды (с которыми несовместим)
            for affected_name in affected_mods:
                affected_mod = None
                
                # 1. Сначала ищем точное совпадение
                for m in mods_list:
                    if m['name'] and affected_name and m['name'].lower() == affected_name.lower():
                        affected_mod = m
                        break
                
                # 2. Если не нашли, ищем fuzzy
                if not affected_mod:
                    for m in mods_list:
                        if m['name'] and affected_name and (m['name'].lower() in affected_name.lower() or affected_name.lower() in m['name'].lower()):
                            affected_mod = m
                            break
                
                if not affected_mod or affected_mod['name'] == mod_name:
                    continue
                
                if not affected_mod.get('source_id'):
                    print(f"   ⚠️  Affected mod '{affected_name}' has no source_id, skipping")
                    continue
                
                # Проверяем что мод не несовместим сам с собой
                if matching_mod['source_id'] == affected_mod['source_id']:
                    print(f"   ⚠️  Skipping self-incompatibility: {matching_mod['name']} cannot be incompatible with itself")
                    continue
                
                # Обновляем БД (двунаправленно)
                # 1. Affected mod is incompatible with matching mod
                success1 = add_incompatibility_to_db(
                    mod_source_id=affected_mod['source_id'],
                    incompatible_with_id=matching_mod['source_id'],
                    reason=reason,
                    loaders=loaders,
                    supabase_url=supabase_url,
                    supabase_key=supabase_key
                )
                
                # 2. Matching mod is incompatible with affected mod (обратная связь)
                # Ищем reason для affected_mod в incompatible_mods
                reverse_reason = None
                for incompat in incompatible_mods:
                    if incompat['mod_name'].lower() == affected_mod['name'].lower():
                        reverse_reason = incompat['reason']
                        break
                
                if not reverse_reason:
                    reverse_reason = f"Incompatible with {affected_mod['name']}"
                
                success2 = add_incompatibility_to_db(
                    mod_source_id=matching_mod['source_id'],
                    incompatible_with_id=affected_mod['source_id'],
                    reason=reverse_reason,
                    loaders=loaders,
                    supabase_url=supabase_url,
                    supabase_key=supabase_key
                )
                
                if success1 or success2:
                    updates_made.append({
                        'mod': affected_mod['name'],
                        'incompatible_with': mod_name,
                        'reason': reason
                    })
                    print(f"   ✅ Added: {affected_mod['name']} ↔️ {mod_name}")
        
        return {
            'success': True,
            'updates_made': updates_made,
            'analysis': analysis
        }
        
    except Exception as e:
        print(f"❌ [Feedback Processor] Error: {e}")
        import traceback
        traceback.print_exc()
        return {
            'success': False,
            'error': str(e)
        }


def mark_mod_as_outdated(
    mod_source_id: str,
    reason: str,
    supabase_url: str,
    supabase_key: str,
    is_god_mode: bool = False
) -> bool:
    """
    Помечает мод как устаревший в incompatibilities с особым типом
    Использует ключ "_OUTDATED_" чтобы отличать от обычных incompatibilities
    
    Args:
        is_god_mode: Если True, устанавливает reported_count=100 (мгновенный бан)
    """
    try:
        print(f"   📝 [DB Update] Marking mod '{mod_source_id}' as outdated")
        
        # Получаем текущие incompatibilities
        response = requests.get(
            f'{supabase_url}/rest/v1/mods',
            params={'source_id': f'eq.{mod_source_id}', 'select': 'id,source_id,name,incompatibilities'},
            headers={
                'apikey': supabase_key,
                'Authorization': f'Bearer {supabase_key}'
            },
            timeout=10
        )
        
        if response.status_code != 200:
            print(f"   ❌ [DB Query] Failed to fetch mod: HTTP {response.status_code}")
            return False
            
        data = response.json()
        if not data:
            print(f"   ❌ [DB Query] Mod with source_id '{mod_source_id}' not found in database")
            return False
        
        mod_data = data[0]
        print(f"   ✅ [DB Query] Found mod: {mod_data.get('name')} ({mod_data.get('source_id')})")
        
        current_incompats = mod_data.get('incompatibilities')
        
        # Обрабатываем None, пустую строку или строку JSON
        if current_incompats is None:
            current_incompats = {}
        elif isinstance(current_incompats, str):
            current_incompats = json.loads(current_incompats) if current_incompats else {}
        elif not isinstance(current_incompats, dict):
            current_incompats = {}
        
        # Добавляем или обновляем отметку "outdated"
        if is_god_mode:
            # GOD MODE: мгновенный бан
            current_incompats['_OUTDATED_'] = {
                'reason': reason,
                'type': 'outdated',
                'auto_added': True,
                'reported_count': 100,
                'god_mode': True
            }
            print(f"   👑 [GOD MODE] Instantly blacklisted mod with reported_count=100")
        elif '_OUTDATED_' in current_incompats:
            # Увеличиваем счетчик жалоб
            current_incompats['_OUTDATED_']['reported_count'] = current_incompats['_OUTDATED_'].get('reported_count', 1) + 1
            current_incompats['_OUTDATED_']['latest_reason'] = reason
            print(f"   🔁 [DB Update] Incremented outdated reports: {current_incompats['_OUTDATED_']['reported_count']}")
        else:
            # Создаем новую отметку
            current_incompats['_OUTDATED_'] = {
                'reason': reason,
                'type': 'outdated',
                'auto_added': True,
                'reported_count': 1
            }
            print(f"   ➕ [DB Update] Created new outdated marker")
        
        # Обновляем БД
        update_response = requests.patch(
            f'{supabase_url}/rest/v1/mods',
            params={'source_id': f'eq.{mod_source_id}'},
            headers={
                'apikey': supabase_key,
                'Authorization': f'Bearer {supabase_key}',
                'Content-Type': 'application/json',
                'Prefer': 'return=minimal'
            },
            json={'incompatibilities': current_incompats},
            timeout=10
        )
        
        if update_response.status_code in [200, 204]:
            print(f"   ✅ [DB Update] Successfully marked mod '{mod_source_id}' as outdated")
            return True
        else:
            print(f"   ❌ [DB Update] Failed to update: {update_response.text}")
            return False
        
    except Exception as e:
        print(f"   ❌ [DB Update] Exception occurred: {e}")
        import traceback
        traceback.print_exc()
        return False


def add_incompatibility_to_db(
    mod_source_id: str,
    incompatible_with_id: str,
    reason: str,
    loaders: Optional[list],
    supabase_url: str,
    supabase_key: str
) -> bool:
    """
    Добавляет несовместимость в БД по source_id
    loaders: None = глобальная несовместимость, [список] = только на этих loader'ах
    """
    try:
        print(f"   📝 [DB Update] Updating mod '{mod_source_id}' to mark incompatible with '{incompatible_with_id}'")
        
        # Получаем текущие incompatibilities
        response = requests.get(
            f'{supabase_url}/rest/v1/mods',
            params={'source_id': f'eq.{mod_source_id}', 'select': 'id,source_id,name,incompatibilities'},
            headers={
                'apikey': supabase_key,
                'Authorization': f'Bearer {supabase_key}'
            },
            timeout=10
        )
        
        print(f"   📡 [DB Query] GET status: {response.status_code}")
        
        if response.status_code != 200:
            print(f"   ❌ [DB Query] Failed to fetch mod: HTTP {response.status_code}")
            return False
            
        data = response.json()
        if not data:
            print(f"   ❌ [DB Query] Mod with source_id '{mod_source_id}' not found in database")
            return False
        
        mod_data = data[0]
        print(f"   ✅ [DB Query] Found mod: {mod_data.get('name')} ({mod_data.get('source_id')})")
        
        current_incompats = mod_data.get('incompatibilities')
        
        # Обрабатываем None, пустую строку или строку JSON
        if current_incompats is None:
            current_incompats = {}
        elif isinstance(current_incompats, str):
            current_incompats = json.loads(current_incompats) if current_incompats else {}
        elif not isinstance(current_incompats, dict):
            current_incompats = {}
        
        print(f"   📊 [DB Update] Current incompatibilities count: {len(current_incompats)}")
        
        # Добавляем новую несовместимость
        incompatibility_entry = {
            'reason': reason,
            'type': 'user_reported',
            'auto_added': True
        }
        
        # Добавляем loaders если указаны (не глобальная)
        if loaders:
            incompatibility_entry['loaders'] = loaders
        
        current_incompats[incompatible_with_id] = incompatibility_entry
        
        print(f"   📊 [DB Update] New incompatibilities count: {len(current_incompats)}")
        print(f"   💾 [DB Update] Adding incompatibility: {incompatible_with_id} -> {reason}")
        
        # Обновляем БД
        update_response = requests.patch(
            f'{supabase_url}/rest/v1/mods',
            params={'source_id': f'eq.{mod_source_id}'},
            headers={
                'apikey': supabase_key,
                'Authorization': f'Bearer {supabase_key}',
                'Content-Type': 'application/json',
                'Prefer': 'return=minimal'
            },
            json={'incompatibilities': current_incompats},
            timeout=10
        )
        
        print(f"   📡 [DB Update] PATCH status: {update_response.status_code}")
        
        if update_response.status_code in [200, 204]:
            print(f"   ✅ [DB Update] Successfully updated mod '{mod_source_id}'")
            return True
        else:
            print(f"   ❌ [DB Update] Failed to update: {update_response.text}")
            return False
        
    except Exception as e:
        print(f"   ❌ [DB Update] Exception occurred: {e}")
        import traceback
        traceback.print_exc()
        return False
