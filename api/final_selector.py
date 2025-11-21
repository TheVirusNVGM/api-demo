"""Layer 2: Final Selector
Финальный умный отбор модов из кандидатов используя DeepSeek
OPTIMIZED: Local prefiltering + single AI call
"""

import requests
import json
import re
import time
from typing import Dict, List, Optional
from collections import defaultdict
from config import ESSENTIAL_LIBRARIES, DEEPSEEK_INPUT_COST, DEEPSEEK_OUTPUT_COST

# Optimization constants
MAX_AI_CANDIDATES = 50  # было ~100, стало максимум 50
PER_CATEGORY_LIMIT = 6   # с каждой категории берём не больше 6
AI_TIMEOUT = 60          # было 90, стало 60
MIN_CAP_INTERSECTION = 1 # минимум пересечений capabilities для matching


def _is_library_mod(mod: Dict) -> bool:
    """Проверяет является ли мод библиотекой"""
    caps = set(mod.get('capabilities', []))
    tags = set(mod.get('tags', []))
    return bool(
        caps & {'api.exposed', 'dependency.library', 'compatibility.bridge', 'compatibility.integration'}
        or tags & {'library', 'api', 'dependency', 'core-mod'}
    )


def _score_mod_for_category(mod: Dict, category: Dict) -> float:
    """
    Локальный скоринг мода для категории без AI.
    Считает пересечение capabilities + популярность.
    """
    mod_caps = set(mod.get('capabilities', []))
    req_caps = set(category.get('required_capabilities', []))
    pref_caps = set(category.get('preferred_capabilities', []))
    
    # Пересечение по capabilities
    intersection_req = len(mod_caps & req_caps)
    intersection_pref = len(mod_caps & pref_caps)
    
    # Популярность (downloads)
    downloads = mod.get('downloads') or mod.get('total_downloads') or mod.get('modrinth_downloads') or 0
    pop_score = min(downloads / 100_000, 3.0)  # до 3 баллов с потолком
    
    # Итоговый score
    score = (
        intersection_req * 5.0    # required capabilities самое важное
        + intersection_pref * 2.0  # preferred capabilities бонус
        + pop_score                # популярность
    )
    
    return score


def _preselect_candidates_by_architecture(
    candidates: List[Dict],
    planned_architecture: Optional[Dict],
    max_mods: int
) -> List[Dict]:
    """
    Быстрый локальный предвыбор кандидатов на основе архитектуры.
    Уменьшает список с ~100 до ~50 модов для AI.
    """
    if not planned_architecture:
        # Нет архитектуры - просто берём топ по score
        return candidates[:MAX_AI_CANDIDATES]
    
    categories = planned_architecture.get('categories', [])
    if not categories:
        return candidates[:MAX_AI_CANDIDATES]
    
    print(f"   🔍 [Preselect] Filtering {len(candidates)} candidates by architecture...")
    
    # 1. Отделяем библиотеки - они всегда нужны
    library_mods = [m for m in candidates if _is_library_mod(m)]
    gameplay_mods = [m for m in candidates if not _is_library_mod(m)]
    
    print(f"   📚 Found {len(library_mods)} libraries, {len(gameplay_mods)} gameplay mods")
    
    picked: List[Dict] = []
    picked_slugs = set()
    
    # 2. По каждой категории берём топ подходящих модов
    for cat in categories:
        scored = []
        for mod in gameplay_mods:
            if mod.get('slug') in picked_slugs:
                continue
            score = _score_mod_for_category(mod, cat)
            if score < MIN_CAP_INTERSECTION and len(cat.get('required_capabilities', [])) > 0:
                continue  # мод не подходит под категорию
            scored.append((score, mod))
        
        # Сортируем по убыванию score
        scored.sort(key=lambda x: x[0], reverse=True)
        
        # Берём топ PER_CATEGORY_LIMIT модов
        top_mods = [m for _, m in scored[:PER_CATEGORY_LIMIT]]
        for mod in top_mods:
            if mod.get('slug') not in picked_slugs:
                picked.append(mod)
                picked_slugs.add(mod.get('slug'))
    
    # 3. Если мало - добиваем популярными
    if len(picked) < max_mods:
        rest = [m for m in gameplay_mods if m.get('slug') not in picked_slugs]
        rest.sort(
            key=lambda m: m.get('downloads') or m.get('total_downloads') or m.get('modrinth_downloads') or 0,
            reverse=True
        )
        need = max_mods - len(picked)
        picked.extend(rest[:need])
    
    # 4. Добавляем библиотеки в начало (но не все, максимум 15)
    trimmed_libraries = library_mods[:15]
    result = trimmed_libraries + picked
    
    # 5. Дедупликация и обрезка до MAX_AI_CANDIDATES
    deduped = []
    seen = set()
    for m in result:
        slug = m.get('slug') or m.get('project_id') or m.get('name')
        if slug in seen:
            continue
        seen.add(slug)
        deduped.append(m)
        if len(deduped) >= MAX_AI_CANDIDATES:
            break
    
    print(f"   ✂️  Preselected {len(deduped)} candidates (was {len(candidates)})")
    return deduped


def select_final_mods(
    candidates: List[Dict],
    user_prompt: str,
    current_mods: List[str],
    max_mods: int,
    deepseek_key: str,
    reference_context: str = None,
    planned_architecture: Dict = None,
    baseline_mods: List[Dict] = None
) -> Dict:
    """
    OPTIMIZED: Финальный отбор модов с локальным предвыбором.
    
    Процесс:
    1. Локально фильтруем 100 -> 50 кандидатов по capabilities
    2. Отправляем 50 в AI для финального выбора
    3. Если кандидатов мало - skip AI (fast path)
    
    Args:
        candidates: Список кандидатов от Hybrid Search
        user_prompt: Оригинальный запрос пользователя
        current_mods: Project IDs модов уже на доске
        max_mods: Максимум модов для выбора
        deepseek_key: API ключ DeepSeek
        reference_context: Reference архитектуры модпаков (опционально, v2)
        planned_architecture: Запланированная архитектура модпака (опционально, v3)
    
    Returns:
        Dict с выбранными модами и explanation
    """
    start_time = time.time()
    print(f"🎯 [Final Selector] Selecting best {max_mods} mods from {len(candidates)} candidates...")
    
    # BASELINE: Автоматически добавляем baseline моды (они не считаются в max_mods)
    baseline_added = []
    baseline_source_ids = set()
    
    if baseline_mods:
        print(f"   📌 [Baseline] Adding {len(baseline_mods)} baseline mods automatically...")
        
        # Создаём set source_id кандидатов для быстрого поиска
        candidates_source_ids = {mod.get('source_id') for mod in candidates if mod.get('source_id')}
        
        for baseline_mod in baseline_mods:
            baseline_source_id = baseline_mod.get('source_id')
            if not baseline_source_id:
                continue
            
            # Проверяем: есть ли baseline мод уже в candidates?
            baseline_in_candidates = any(
                mod.get('source_id') == baseline_source_id 
                for mod in candidates
            )
            
            if baseline_in_candidates:
                # Baseline мод уже в candidates - он будет выбран автоматически
                baseline_source_ids.add(baseline_source_id)
                baseline_added.append(baseline_mod['name'])
            else:
                # Baseline мод не в candidates - добавляем его как "скрытый" кандидат
                # (он будет добавлен в финальный результат автоматически)
                baseline_source_ids.add(baseline_source_id)
                baseline_added.append(baseline_mod['name'])
        
        if baseline_added:
            print(f"   ✅ Baseline mods to include: {', '.join(baseline_added[:5])}")
            if len(baseline_added) > 5:
                print(f"      ... and {len(baseline_added) - 5} more")
            print(f"   ℹ️  Baseline mods are NOT counted in mod limit (they're the foundation)")
    
    # Логируем все кандидаты для отладки
    print(f"   📋 All candidates ({len(candidates)} mods):")
    candidates_slugs = []
    for i, mod in enumerate(candidates[:20], 1):  # Показываем первые 20
        slug = mod.get('slug', 'unknown')
        name = mod.get('name', 'unknown')
        candidates_slugs.append(slug)
        print(f"      {i}. {name} ({slug})")
    if len(candidates) > 20:
        print(f"      ... and {len(candidates) - 20} more")
    
    # Fast path 1: если кандидатов меньше чем надо - возвращаем все
    if len(candidates) <= max_mods:
        print(f"   ⚡ Fast path: {len(candidates)} <= {max_mods}, returning all candidates")
        
        # BASELINE: Добавляем baseline моды если их нет
        result_mods = candidates.copy()
        if baseline_mods:
            candidates_source_ids = {mod.get('source_id') for mod in candidates if mod.get('source_id')}
            for baseline_mod in baseline_mods:
                baseline_source_id = baseline_mod.get('source_id')
                if baseline_source_id and baseline_source_id not in candidates_source_ids:
                    # Ищем в candidates или создаём запись
                    baseline_found = None
                    for candidate in candidates:
                        if candidate.get('source_id') == baseline_source_id:
                            baseline_found = candidate.copy()
                            break
                    
                    if baseline_found:
                        baseline_found['_added_as_baseline'] = True
                        result_mods.append(baseline_found)
                    else:
                        baseline_entry = {
                            'source_id': baseline_source_id,
                            'name': baseline_mod['name'],
                            'slug': baseline_mod.get('slug', ''),
                            'capabilities': baseline_mod.get('capabilities', []),
                            'tags': baseline_mod.get('tags', []),
                            '_added_as_baseline': True
                        }
                        result_mods.append(baseline_entry)
        
        return {
            'mods': result_mods,
            'explanation': 'Fast-path selection: all candidates fit within limit',
            '_tokens': {
                'prompt_tokens': 0,
                'completion_tokens': 0,
                'total_tokens': 0,
                'cost_usd': 0.0,
            }
        }
    
    # Локальный предвыбор (100 → 50)
    trimmed_candidates = _preselect_candidates_by_architecture(
        candidates,
        planned_architecture,
        max_mods
    )
    
    # Логируем preselected кандидаты
    print(f"   📋 Preselected candidates ({len(trimmed_candidates)} mods):")
    preselected_slugs = []
    for i, mod in enumerate(trimmed_candidates[:20], 1):  # Показываем первые 20
        slug = mod.get('slug', 'unknown')
        name = mod.get('name', 'unknown')
        preselected_slugs.append(slug)
        print(f"      {i}. {name} ({slug})")
    if len(trimmed_candidates) > 20:
        print(f"      ... and {len(trimmed_candidates) - 20} more")
    
    # Fast path 2: после предвыбора всё влезает - skip AI
    if len(trimmed_candidates) <= max_mods:
        print(f"   ⚡ Fast path 2: after preselect {len(trimmed_candidates)} <= {max_mods}, skipping AI")
        selected = ensure_libraries(trimmed_candidates, candidates)
        
        # BASELINE: Добавляем baseline моды если их нет
        if baseline_mods:
            selected_source_ids = {mod.get('source_id') for mod in selected if mod.get('source_id')}
            for baseline_mod in baseline_mods:
                baseline_source_id = baseline_mod.get('source_id')
                if baseline_source_id and baseline_source_id not in selected_source_ids:
                    # Ищем в candidates
                    baseline_found = None
                    for candidate in candidates:
                        if candidate.get('source_id') == baseline_source_id:
                            baseline_found = candidate.copy()
                            break
                    
                    if baseline_found:
                        baseline_found['_added_as_baseline'] = True
                        selected.append(baseline_found)
                    else:
                        baseline_entry = {
                            'source_id': baseline_source_id,
                            'name': baseline_mod['name'],
                            'slug': baseline_mod.get('slug', ''),
                            'capabilities': baseline_mod.get('capabilities', []),
                            'tags': baseline_mod.get('tags', []),
                            '_added_as_baseline': True
                        }
                        selected.append(baseline_entry)
        
        return {
            'mods': selected,
            'explanation': 'Architecture-based preselect, AI skipped for efficiency',
            '_tokens': {
                'prompt_tokens': 0,
                'completion_tokens': 0,
                'total_tokens': 0,
                'cost_usd': 0.0,
            }
        }
    
    # Формируем промпт (теперь гораздо короче)
    candidates_text = format_candidates(trimmed_candidates)  # было [:100], стало все
    
    # Добавляем reference context или planned architecture
    reference_section = ""
    
    if planned_architecture:
        print(f"   🏗️  Using planned architecture ({len(planned_architecture.get('categories', []))} categories)")
        arch_lines = ["PLANNED MODPACK ARCHITECTURE:"]
        
        for cat in planned_architecture.get('categories', []):
            arch_lines.append(f"\n{cat['name']}: {cat.get('description', '')}")
            arch_lines.append(f"  Target: {cat.get('target_mods', 0)} mods")
            
            req_caps = cat.get('required_capabilities', [])
            if req_caps:
                arch_lines.append(f"  Required capabilities: {', '.join(req_caps[:5])}")
            
            pref_caps = cat.get('preferred_capabilities', [])
            if pref_caps:
                arch_lines.append(f"  Preferred capabilities: {', '.join(pref_caps[:5])}")
        
        reference_section = "\n".join(arch_lines)
        reference_section += """

IMPORTANT: Select mods according to this planned architecture.
- Aim to fill each category with its target mod count
- Prioritize mods with required capabilities
- Give bonus to mods with preferred capabilities
- The architecture is a GUIDE - adapt to available candidates
"""
    
    elif reference_context:
        print(f"   📚 Using reference architectures in AI prompt")
        reference_section = f"""

{reference_context}

IMPORTANT: Use these reference architectures as INSPIRATION for your selection.
- Look at the common capability patterns
- Consider similar mod choices for similar capabilities
- But adapt to the current MC version and available candidates
- Don't copy exactly - use as a learning reference
"""
    
    system_prompt = f"""You are an expert Minecraft modpack curator. Your task is to select the BEST mods from candidates that match the user's request.
{reference_section}
SELECTION CRITERIA:
1. **Relevance**: How well does the mod match user's request?
2. **Quality**: Is the mod stable, popular, and well-maintained?
3. **Synergy**: Do the mods work well together?
4. **Diversity**: Avoid selecting too many similar mods
5. **Dependencies**: ALWAYS include required libraries/APIs

RULES:
- **CRITICAL**: You MUST select close to the max_mods limit (aim for 90-100% of max)
- If user asks for SPECIFIC mods -> prioritize exact matches
- If user asks for a THEME -> select diverse mods fitting the theme
- Always check for conflicts and incompatibilities
- Prefer mods with higher downloads (more stable)
- **CRITICAL**: ALWAYS include essential libraries (Fabric API, Cloth Config, etc.)
- **CRITICAL**: If you see mods with 'library' or 'api' tags -> ALWAYS include them
- Libraries should be selected FIRST before other mods
- Better to include MORE mods than fewer (user wants a full modpack!)

OUTPUT FORMAT:
Return ONLY valid JSON (no markdown):
{{
  "mods": [
    {{
      "slug": "mod-slug",
      "reason": "Why this mod was selected (1-2 sentences)"
    }}
  ],
  "explanation": "Overall explanation of the selection (2-3 sentences)"
}}"""

    user_message = f"""USER REQUEST: \"{user_prompt}\"
Max mods to select: {max_mods}

IMPORTANT: You should select EXACTLY {max_mods} mods (or as close as possible to this number).
The user wants a FULL modpack! Dependencies will be added automatically later, so focus on gameplay mods.

CANDIDATES (ranked by relevance):
{candidates_text}

CURRENT MODS ON BOARD:
{format_current_mods(current_mods)}

Select the best mods that:
1. Match the user's request
2. Work well together
3. Don't conflict with current mods
4. Provide the best experience
5. Fill up the modpack (aim for {max_mods} mods total!)

Return your selection in JSON format."""

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
                    {'role': 'user', 'content': user_message}
                ],
                'temperature': 0.2,
                'max_tokens': 2000  # было 4000, стало 2000 (меньше кандидатов)
            },
            timeout=AI_TIMEOUT  # 60s вместо 90s
        )
        
        if response.status_code != 200:
            raise Exception(f"DeepSeek API error: {response.status_code} - {response.text}")
        
        result = response.json()
        content = result['choices'][0]['message']['content'].strip()
        
        # Извлекаем инфо о токенах
        usage = result.get('usage', {})
        prompt_tokens = usage.get('prompt_tokens', 0)
        completion_tokens = usage.get('completion_tokens', 0)
        total_tokens = usage.get('total_tokens', 0)
        cost = (prompt_tokens * DEEPSEEK_INPUT_COST / 1_000_000) + (completion_tokens * DEEPSEEK_OUTPUT_COST / 1_000_000)
        
        print(f"📥 [Final Selector] Received selection from AI")
        print(f"   📊 Tokens: {total_tokens:,} (prompt: {prompt_tokens:,}, completion: {completion_tokens:,})")
        print(f"   💵 Cost: ${cost:.6f}")
        
        # Парсим JSON
        content = content.replace('```json', '').replace('```', '').strip()
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        
        if not json_match:
            raise Exception("Could not parse JSON from Final Selector")
        
        selection = json.loads(json_match.group())
        
        # Детальное логирование ответа AI
        print(f"📋 [Final Selector] AI Response:")
        print(f"   Mods in response: {len(selection.get('mods', []))}")
        ai_selected_slugs = []
        if len(selection.get('mods', [])) > 0:
            ai_selected_slugs = [m.get('slug') for m in selection.get('mods', [])]
            print(f"   Mod slugs: {ai_selected_slugs}")
        else:
            print(f"   ⚠️  AI returned EMPTY mods array!")
            print(f"   Full response: {json.dumps(selection, indent=2)}")
        
        # Обогащаем данными из trimmed_candidates (не из всех candidates)
        candidates_dict = {m['slug']: m for m in trimmed_candidates}
        selected_mods = []
        missing_slugs = []  # Моды, которые AI выбрал, но их нет в кандидатах
        
        for mod_selection in selection.get('mods', []):
            slug = mod_selection.get('slug')
            if slug in candidates_dict:
                mod_data = candidates_dict[slug].copy()
                mod_data['ai_reason'] = mod_selection.get('reason', '')
                selected_mods.append(mod_data)
            else:
                missing_slugs.append(slug)
        
        if missing_slugs:
            print(f"   ⚠️  AI selected {len(missing_slugs)} mods not in preselected candidates: {missing_slugs}")
        
        print(f"✅ [Final Selector] Selected {len(selected_mods)} mods")
        
        # BASELINE: Добавляем baseline моды автоматически (если их ещё нет)
        if baseline_mods:
            selected_source_ids = {mod.get('source_id') for mod in selected_mods if mod.get('source_id')}
            
            for baseline_mod in baseline_mods:
                baseline_source_id = baseline_mod.get('source_id')
                if not baseline_source_id:
                    continue
                
                # Если baseline мод уже выбран - пропускаем
                if baseline_source_id in selected_source_ids:
                    continue
                
                # Ищем baseline мод в candidates (для получения полных данных)
                baseline_in_candidates = None
                for candidate in candidates:
                    if candidate.get('source_id') == baseline_source_id:
                        baseline_in_candidates = candidate.copy()
                        break
                
                if baseline_in_candidates:
                    # Используем данные из candidates
                    baseline_in_candidates['_added_as_baseline'] = True
                    selected_mods.append(baseline_in_candidates)
                    print(f"   📌 Added baseline mod: {baseline_mod['name']}")
                else:
                    # Baseline мод не в candidates - создаём минимальную запись
                    baseline_entry = {
                        'source_id': baseline_source_id,
                        'name': baseline_mod['name'],
                        'slug': baseline_mod.get('slug', ''),
                        'capabilities': baseline_mod.get('capabilities', []),
                        'tags': baseline_mod.get('tags', []),
                        '_added_as_baseline': True
                    }
                    selected_mods.append(baseline_entry)
                    print(f"   📌 Added baseline mod (not in candidates): {baseline_mod['name']}")
        
        # Логируем пропущенные моды (были в preselected, но не выбраны AI)
        selected_slugs_set = {m.get('slug') for m in selected_mods}
        skipped_mods = [m for m in trimmed_candidates if m.get('slug') not in selected_slugs_set]
        if skipped_mods:
            print(f"   📊 Skipped {len(skipped_mods)} mods from preselected (not chosen by AI):")
            for mod in skipped_mods[:10]:  # Показываем первые 10
                slug = mod.get('slug', 'unknown')
                name = mod.get('name', 'unknown')
                print(f"      - {name} ({slug})")
            if len(skipped_mods) > 10:
                print(f"      ... and {len(skipped_mods) - 10} more")
        
        # Автоматически добавляем критичные библиотеки если их нет
        selected_mods = ensure_libraries(selected_mods, trimmed_candidates)
        print(f"📚 [Final Selector] After ensuring libraries: {len(selected_mods)} mods")
        
        elapsed = time.time() - start_time
        print(f"   ⏱️  Selection took {elapsed:.2f}s (optimized)")
        
        return {
            'mods': selected_mods,
            'explanation': selection.get('explanation', ''),
            'user_prompt': user_prompt,
            '_tokens': {
                'prompt_tokens': prompt_tokens,
                'completion_tokens': completion_tokens,
                'total_tokens': total_tokens,
                'cost_usd': cost
            }
        }
        
    except Exception as e:
        print(f"❌ [Final Selector] Error: {e}")
        # Fallback: берём из trimmed_candidates (они уже отфильтрованы)
        print(f"⚠️  [Final Selector] Using fallback selection from preselected candidates")
        return fallback_selection(trimmed_candidates, max_mods, user_prompt)


def format_candidates(candidates: List[Dict]) -> str:
    """
    Форматирует кандидатов для промпта
    """
    lines = []
    for i, mod in enumerate(candidates, 1):
        lines.append(f"{i}. [{mod['slug']}] {mod['name']}")
        
        # Используем summary (более точное чем description)
        summary = mod.get('summary', '')
        if summary:
            lines.append(f"   Summary: {summary[:200]}")
        else:
            # Fallback если summary нет
            lines.append(f"   Description: {mod.get('description', '')[:200]}")
        
        # Используем modrinth_categories + важные tags
        mod_categories = mod.get('modrinth_categories', [])
        mod_tags = mod.get('tags', [])
        lines.append(f"   Categories: {', '.join(mod_categories[:3])}")
        
        # Показываем важные теги
        important_tags = [t for t in mod_tags if t in ['client-only', 'server-only', 'universal', 'library', 'api', 'essential-mod', 'modpack-essential']]
        if important_tags:
            lines.append(f"   Tags: {', '.join(important_tags[:5])}")
        
        lines.append(f"   Downloads: {mod.get('downloads', 0):,}")
        
        # Показываем score если есть
        if '_combined_score' in mod:
            lines.append(f"   Relevance Score: {mod['_combined_score']:.3f}")
        
        lines.append("")
    
    return "\n".join(lines)


def format_current_mods(current_mods: List[str]) -> str:
    """
    Форматирует текущие моды
    """
    if not current_mods:
        return "None"
    
    return "\n".join(f"- {mod_id}" for mod_id in current_mods[:50])


def ensure_libraries(selected_mods: List[Dict], candidates: List[Dict]) -> List[Dict]:
    """
    Автоматически добавляет критичные библиотеки если их нет
    """
    essential_libraries = ESSENTIAL_LIBRARIES
    
    selected_slugs = {mod['slug'] for mod in selected_mods}
    candidates_dict = {mod['slug']: mod for mod in candidates}
    
    # Проверяем есть ли уже библиотеки
    has_libraries = False
    for mod in selected_mods:
        tags = mod.get('tags', [])
        if 'library' in tags or 'api' in tags or 'dependency' in tags:
            has_libraries = True
            break
    
    # Если нет ни одной библиотеки - добавляем критичные
    if not has_libraries:
        print("⚠️  [Library Check] No libraries found, adding essential ones...")
        added = 0
        for lib_slug in essential_libraries:
            if lib_slug not in selected_slugs and lib_slug in candidates_dict:
                lib_mod = candidates_dict[lib_slug]
                lib_mod['ai_reason'] = 'Auto-added as essential library dependency'
                selected_mods.insert(0, lib_mod)  # Добавляем в начало
                print(f"   + Added {lib_mod['name']}")
                added += 1
        
        if added > 0:
            print(f"✅ [Library Check] Added {added} essential libraries")
    else:
        print("✅ [Library Check] Libraries already present")
    
    return selected_mods


def enrich_mods_with_full_data(
    selected_mods: List[Dict],
    supabase_url: str,
    supabase_key: str
) -> List[Dict]:
    """
    Перефетчит полные данные модов из БД (включая dependencies)
    """
    import requests
    
    print(f"💾 [Data Enrichment] Fetching full data for {len(selected_mods)} mods...")
    
    enriched_mods = []
    
    for mod in selected_mods:
        source_id = mod.get('source_id')
        if not source_id:
            # Если нет source_id - оставляем как есть
            enriched_mods.append(mod)
            continue
        
        try:
            response = requests.get(
                f'{supabase_url}/rest/v1/mods',
                params={'source_id': f'eq.{source_id}', 'select': '*'},
                headers={
                    'apikey': supabase_key,
                    'Authorization': f'Bearer {supabase_key}'
                },
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                if data:
                    # Используем полные данные из БД
                    full_mod = data[0]
                    # Сохраняем AI metadata если есть
                    if 'ai_reason' in mod:
                        full_mod['ai_reason'] = mod['ai_reason']
                    if '_added_as_dependency' in mod:
                        full_mod['_added_as_dependency'] = mod['_added_as_dependency']
                    enriched_mods.append(full_mod)
                else:
                    enriched_mods.append(mod)
            else:
                enriched_mods.append(mod)
        except Exception as e:
            print(f"   ⚠️  Failed to enrich {mod.get('name')}: {e}")
            enriched_mods.append(mod)
    
    print(f"✅ [Data Enrichment] Complete: {len(enriched_mods)} mods enriched")
    return enriched_mods


def fallback_selection(candidates: List[Dict], max_mods: int, user_prompt: str) -> Dict:
    """
    Простой fallback если AI не сработал
    """
    selected = candidates[:max_mods]
    
    # Добавляем библиотеки и в fallback
    selected = ensure_libraries(selected, candidates)
    
    return {
        'mods': selected,
        'explanation': f"Selected top {len(selected)} mods based on relevance scores.",
        'user_prompt': user_prompt,
        '_is_fallback': True
    }
