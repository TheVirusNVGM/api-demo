"""
Architecture Refiner - уточнение и расширение архитектуры модпака после получения модов

Работает после Architecture Planner и Dependency Resolver:
1. Видит реальные моды с их capabilities
2. Анализирует первоначальный скелет категорий
3. Умно расширяет/уточняет категории под реальный набор модов
4. Разделяет перегруженные категории
5. Объединяет малозаполненные категории
"""

import requests
import json
import re
from typing import Dict, List, Optional
from collections import Counter, defaultdict
import os
from config import DEEPSEEK_API_KEY, DEEPSEEK_INPUT_COST, DEEPSEEK_OUTPUT_COST

# Загружаем capabilities reference для классификации
CAPS_REFERENCE = None
TAGS_SYSTEM = None

def load_capabilities_reference():
    global CAPS_REFERENCE
    if CAPS_REFERENCE is None:
        caps_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'capabilities_reference.json')
        with open(caps_path, 'r', encoding='utf-8') as f:
            CAPS_REFERENCE = json.load(f)
    return CAPS_REFERENCE

def load_tags_system():
    """Загружает систему тегов из tags_system.json"""
    global TAGS_SYSTEM
    if TAGS_SYSTEM is None:
        tags_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'tags_system.json')
        with open(tags_path, 'r', encoding='utf-8') as f:
            TAGS_SYSTEM = json.load(f)
    return TAGS_SYSTEM

def get_library_tags():
    """Возвращает множество тегов, которые точно указывают на библиотеку"""
    tags_system = load_tags_system()
    # Библиотечные теги из категории "technical"
    technical_tags = tags_system.get('categories', {}).get('technical', {}).get('tags', [])
    library_tags = {'library', 'api', 'dependency', 'core-mod'}
    # Фильтруем только библиотечные теги из technical категории
    return {tag for tag in technical_tags if tag in library_tags}

def classify_dependency_mod(
    mod: Dict,
    mod_tags: set,
    mod_caps_set: set,
    mod_name_lower: str,
    library_tags_set: set,
    library_caps: set,
    performance_caps: set,
    graphics_caps_strict: set,
    gameplay_caps: set
) -> tuple:
    """
    Формализованная система правил для классификации зависимостей с весами и приоритетами
    
    Returns:
        (category, reason, weight) где:
        - category: 'library', 'performance', 'graphics', 'gameplay'
        - reason: строка с объяснением
        - weight: числовой вес уверенности (0-100)
    """
    # Загружаем worldgen capabilities для контекстной проверки
    caps_ref = load_capabilities_reference()
    worldgen_caps = set(caps_ref['categories'].get('world_generation', []))
    
    # Вычисляем пересечения
    gameplay_intersection = mod_caps_set & gameplay_caps
    performance_intersection = mod_caps_set & performance_caps
    graphics_intersection = mod_caps_set & graphics_caps_strict
    lib_intersection = mod_caps_set & library_caps
    
    # Проверяем наличие библиотечных индикаторов
    has_library_tags = bool(mod_tags & library_tags_set)
    library_name_keywords = ['api', 'library', 'lib', 'core', 'foundation']
    has_library_name = any(keyword in mod_name_lower for keyword in library_name_keywords)
    
    # ПРАВИЛО 1: Performance capabilities (вес: 100) - самый высокий приоритет
    if performance_intersection:
        return ('performance', f'performance caps: {list(performance_intersection)[:2]}', 100)
    
    # ПРАВИЛО 2: Graphics capabilities (вес: 100) - высокий приоритет
    if graphics_intersection:
        return ('graphics', f'graphics caps: {list(graphics_intersection)[:2]}', 100)
    
    # ПРАВИЛО 3: Library теги (вес: 95) - очень надёжный индикатор
    if has_library_tags:
        matched_tags = list(mod_tags & library_tags_set)[:2]
        return ('library', f'library tags: {matched_tags}', 95)
    
    # ПРАВИЛО 4: Library название (вес: 90) - надёжный индикатор
    if has_library_name:
        matched_keywords = [kw for kw in library_name_keywords if kw in mod_name_lower][:2]
        return ('library', f'library name keywords: {matched_keywords}', 90)
    
    # ПРАВИЛО 5: Library capabilities + только worldgen (вес: 85)
    # Комбинация: library caps + worldgen = API для структур (библиотека)
    if lib_intersection:
        significant_gameplay_caps = gameplay_intersection - worldgen_caps
        if not significant_gameplay_caps:
            worldgen_found = list(gameplay_intersection & worldgen_caps)[:2]
            lib_caps_found = list(lib_intersection)[:2]
            return ('library', f'library caps: {lib_caps_found}, only worldgen: {worldgen_found}', 85)
    
    # ПРАВИЛО 6: Library capabilities + значимые gameplay (вес: 80)
    # Комбинация: library caps + gameplay = gameplay мод с API (Farmers Delight, Mekanism)
    if lib_intersection and gameplay_intersection:
        significant_gameplay_caps = gameplay_intersection - worldgen_caps
        if significant_gameplay_caps:
            sig_caps = list(significant_gameplay_caps)[:2]
            return ('gameplay', f'library caps + significant gameplay: {sig_caps}', 80)
    
    # ПРАВИЛО 7: Только library capabilities без gameplay (вес: 75)
    if lib_intersection and not gameplay_intersection:
        lib_caps_found = list(lib_intersection)[:2]
        return ('library', f'library caps only: {lib_caps_found}', 75)
    
    # ПРАВИЛО 8: Gameplay capabilities (вес: 70)
    if gameplay_intersection:
        gameplay_caps_found = list(gameplay_intersection)[:2]
        return ('gameplay', f'gameplay caps: {gameplay_caps_found}', 70)
    
    # ПРАВИЛО 9: Fallback - библиотека по умолчанию для зависимостей (вес: 50)
    return ('library', 'dependency fallback (no clear indicators)', 50)

def classify_regular_mod(
    mod: Dict,
    mod_tags: set,
    mod_caps_set: set,
    mod_name_lower: str,
    mod_summary_lower: str,
    library_tags_set: set,
    library_caps: set,
    performance_caps: set,
    graphics_caps_strict: set,
    gameplay_caps: set,
    ui_caps: set
) -> tuple:
    """
    Формализованная система правил для классификации обычных модов с весами и приоритетами
    
    Returns:
        (category, reason, weight) где:
        - category: 'library', 'performance', 'graphics', 'gameplay'
        - reason: строка с объяснением
        - weight: числовой вес уверенности (0-100)
    """
    # Вычисляем пересечения
    gameplay_intersection = mod_caps_set & gameplay_caps
    performance_intersection = mod_caps_set & performance_caps
    graphics_intersection = mod_caps_set & graphics_caps_strict
    lib_intersection = mod_caps_set & library_caps
    ui_intersection = mod_caps_set & ui_caps
    
    has_library_tags = bool(mod_tags & library_tags_set)
    library_name_keywords = ['api', 'library', 'lib', 'core', 'foundation']
    has_library_name = any(keyword in mod_name_lower for keyword in library_name_keywords)
    
    # ПРАВИЛО 1: Performance capabilities (вес: 90) - ПРИОРИТЕТ над library tags
    # Если у мода есть performance capabilities, это performance мод, даже если есть library тег
    if performance_intersection:
        return ('performance', f'performance caps: {list(performance_intersection)[:2]}', 90)
    
    # ПРАВИЛО 2: Graphics capabilities (вес: 90) - ПРИОРИТЕТ над library tags
    # Если у мода есть graphics capabilities, это graphics мод, даже если есть library тег
    if graphics_intersection:
        # Проверяем контекст ниже, но сначала возвращаем graphics если это чистая графика
        pass  # Продолжаем проверку контекста ниже
    
    # ПРАВИЛО 3: Library теги (вес: 90) - но ТОЛЬКО если нет performance/graphics
    if has_library_tags and not performance_intersection and not graphics_intersection:
        matched_tags = list(mod_tags & library_tags_set)[:2]
        return ('library', f'library tags: {matched_tags}', 90)
    
    # ПРАВИЛО 4: Library название (вес: 85) - но ТОЛЬКО если нет performance/graphics
    if has_library_name and not performance_intersection and not graphics_intersection:
        matched_keywords = [kw for kw in library_name_keywords if kw in mod_name_lower][:2]
        return ('library', f'library name keywords: {matched_keywords}', 85)
    
    # ПРАВИЛО 5: Graphics capabilities (вес: 90) - с проверкой контекста
    if graphics_intersection:
        # Проверяем: это чистая графика или gameplay с визуалом?
        # Gameplay tags из tags_system.json
        gameplay_tags_keywords = [
            'weapons', 'swords', 'bows', 'armor', 'tools', 'building-blocks', 'decorative-blocks',
            'combat', 'pvp', 'boss-fights', 'dungeons', 'biomes', 'structures', 'villages',
            'hostile-mobs', 'passive-mobs', 'boss-mobs'
        ]
        has_gameplay_tags = any(tag in mod_tags for tag in gameplay_tags_keywords)
        
        # Проверка summary на gameplay keywords
        gameplay_keywords_in_summary = [
            'mob', 'mobs', 'creature', 'monster', 'weapon', 'armor', 'sword', 'bow',
            'block', 'blocks', 'item', 'items', 'craft', 'dungeon', 'structure', 'biome',
            'adds', 'new mobs', 'new creatures', 'new items', 'new blocks'
        ]
        has_gameplay_summary = any(keyword in mod_summary_lower for keyword in gameplay_keywords_in_summary)
        
        # Graphics контекст (shader/lighting) - приоритет над gameplay
        graphics_context_keywords = [
            'shader', 'shaders', 'lighting', 'light', 'shadow', 'shadows',
            'render', 'rendering', 'smooth lighting', 'dynamic light', 'iris', 'sodium',
            'flywheel', 'smooth shading', 'path block', 'visual effect'
        ]
        has_graphics_context = any(keyword in mod_summary_lower for keyword in graphics_context_keywords)
        
        # Если graphics контекст → GRAPHICS независимо от упоминания blocks
        if has_graphics_context:
            return ('graphics', f'graphics caps + graphics context: {list(graphics_intersection)[:2]}', 90)
        
        # Если есть gameplay индикаторы → GAMEPLAY (мод с визуалом)
        if gameplay_intersection or has_gameplay_tags or has_gameplay_summary:
            reason_parts = []
            if gameplay_intersection:
                reason_parts.append(f'gameplay caps: {list(gameplay_intersection)[:2]}')
            if has_gameplay_tags:
                matched_tags = [tag for tag in gameplay_tags_keywords if tag in mod_tags][:2]
                reason_parts.append(f'gameplay tags: {matched_tags}')
            if has_gameplay_summary:
                matched_keywords = [kw for kw in gameplay_keywords_in_summary if kw in mod_summary_lower][:2]
                reason_parts.append(f'gameplay summary: {matched_keywords}')
            return ('gameplay', f'graphics + {", ".join(reason_parts)}', 80)
        
        # Чистая графика
        return ('graphics', f'graphics caps: {list(graphics_intersection)[:2]}', 90)
    
    # ПРАВИЛО 5: Library capabilities БЕЗ gameplay контента (вес: 80)
    # Проверка на tech integration или compatibility с контентом
    if lib_intersection:
        tech_keywords = {'energy', 'electricity', 'power', 'voltage', 'joules', 'forge energy', 'rf', 'fe converter'}
        content_keywords = {'recipe', 'recipes', 'item', 'items', 'block', 'blocks', 'food', 'foods', 'add', 'adds', 'new', 'craft', 'crafting'}
        
        is_tech_integration = any(kw in mod_name_lower or kw in mod_summary_lower for kw in tech_keywords)
        has_content = any(kw in mod_summary_lower for kw in content_keywords)
        
        # Если это tech integration или compatibility с контентом → gameplay
        if is_tech_integration and 'compatibility.integration' in lib_intersection:
            return ('gameplay', f'tech integration (not library): {list(lib_intersection)[:2]}', 75)
        
        if 'compatibility.integration' in lib_intersection and has_content:
            return ('gameplay', f'compatibility with content (not library)', 75)
        
        # Чистая библиотека
        if not gameplay_intersection:
            return ('library', f'library caps only: {list(lib_intersection)[:2]}', 80)
    
    # ПРАВИЛО 7: Gameplay capabilities (вес: 75)
    if gameplay_intersection:
        return ('gameplay', f'gameplay caps: {list(gameplay_intersection)[:2]}', 75)
    
    # ПРАВИЛО 8: UI capabilities (вес: 70-80) - проверяем контекст
    if ui_intersection:
        # Если UI + library caps = UI library (REI, JEI) → библиотека
        if lib_intersection:
            return ('library', f'UI + library caps: {list(ui_intersection)[:2]} + {list(lib_intersection)[:2]}', 80)
        # Обычные UI моды (инвентарь, HUD) → gameplay
        return ('gameplay', f'ui caps: {list(ui_intersection)[:2]}', 70)
    
    # ПРАВИЛО 9: Fallback - gameplay по умолчанию для обычных модов (вес: 50)
    return ('gameplay', 'regular mod fallback (no clear indicators)', 50)


def refine_architecture(
    initial_architecture: Dict,
    mods: List[Dict],
    user_prompt: str,
    deepseek_key: str = DEEPSEEK_API_KEY
) -> Optional[Dict]:
    """
    Уточняет и расширяет архитектуру модпака на основе реальных модов
    
    Args:
        initial_architecture: Изначальный скелет от Architecture Planner
        mods: Реальные моды (после AI selection + dependencies)
        user_prompt: Запрос пользователя (для контекста темы)
        deepseek_key: API ключ
    
    Returns:
        Dict с уточнённой архитектурой категорий
    """
    
    print(f"\n🔧 [Architecture Refiner] Refining architecture based on actual mods...")
    print(f"   Initial categories: {len(initial_architecture.get('categories', []))}")
    print(f"   Total mods to organize: {len(mods)}")
    
    # Анализируем реальные моды
    mod_analysis = analyze_mods(mods)
    
    print(f"   📊 Mod analysis:")
    print(f"      Gameplay mods: {mod_analysis['gameplay_count']}")
    print(f"      Library mods: {mod_analysis['library_count']}")
    print(f"      Unique capability prefixes: {len(mod_analysis['capability_prefixes'])}")
    
    # Формируем контекст для AI
    initial_categories_text = format_initial_categories(initial_architecture)
    mod_distribution_text = format_mod_distribution(mods, initial_architecture)
    capability_analysis_text = format_capability_analysis(mod_analysis)
    
    system_prompt = """You are an expert modpack architect specializing in category refinement.

Your task: Refine and expand the initial category skeleton based on ACTUAL mods that were selected.

CONTEXT:
- You see the initial planned categories (the "skeleton")
- You see the REAL mods with their capabilities
- Some categories may be overloaded (20+ mods) - they need splitting
- Some categories may be underutilized (1-3 mods) - they may need merging
- Libraries/dependencies should be grouped separately from gameplay mods

REFINING PRINCIPLES:

1. **RENAME AND REFINE categories creatively:**
   - DO NOT keep generic initial category names - RENAME them to be thematic and evocative
   - Use the mod summaries and user request to create NEW creative names
   - Expand naturally from the skeleton but IMPROVE the names to match the modpack's atmosphere
   - Maintain the modpack's core identity from user's request through CREATIVE naming
   - Example: If initial has "Medieval Combat" → rename to "Knight's Arsenal" or "Royal Armory"
   - Example: If initial has "Core Libraries" → rename to "Castle Foundations" or "Royal Archives"

2. **Split overloaded categories:**
   - If a category has 15+ mods → split into 2-3 sub-categories
   - Split by logical sub-themes based on actual mod capabilities
   - Example: "Medieval Combat" (23 mods) → "Weapons & Armory", "Combat Mechanics", "Player Skills"

3. **Handle libraries smartly:**
   - Libraries (api.exposed, dependency.library) should have their own category
   - But name it creatively based on modpack theme
   - Example: For medieval pack → "Core Foundation" instead of just "Libraries"

4. **Ideal category size:**
   - Target: 5-10 mods per category
   - Acceptable: 3-15 mods per category
   - CRITICAL: If a category has 15+ mods → SPLIT it into 2-3 sub-categories immediately
   - Avoid: 20+ mod categories (too cluttered) - MUST split these
   - Avoid: 1-2 mod categories (merge with related category only if truly related)

5. **Use actual capabilities:**
   - Look at what capabilities the mods ACTUALLY have
   - Group mods with related capability prefixes
   - Don't force mods into wrong categories

6. **Creative naming - BE EVOCATIVE AND THEMATIC:**
   - Category names MUST match the modpack's atmosphere and theme
   - Use the mod summaries to understand what mods actually do, then create thematic names
   - Examples for medieval/fantasy packs:
     * "Knight's Arsenal" / "Royal Armory" instead of "Combat Mods"
     * "Castle Keep" / "Fortress Architecture" instead of "Building Blocks"
     * "Mystical Realms" / "Enchanted Lands" instead of "Fantasy Biomes"
     * "Royal Archives" / "Castle Foundations" instead of "Libraries"
     * "Enchanted Visuals" / "Atmospheric Lighting" instead of "Graphics"
   - Examples for tech packs:
     * "Engineering Hub" instead of "Tech Mods"
     * "Power Grid" instead of "Energy Systems"
   - Examples for adventure packs:
     * "Explorer's Toolkit" instead of "Adventure Mods"
     * "Shadow Realms" instead of "Dimensions"
   - AVOID generic names: "Core Systems", "Gameplay Mods", "Content", "General"
   - Each name should evoke emotion and match the modpack's unique identity
   - Look at mod summaries to understand the actual functionality and create names accordingly

OUTPUT FORMAT (JSON only):
{
  "categories": [
    {
      "name": "Category Name",
      "description": "What this category provides",
      "required_capabilities": ["capability.prefix", ...],
      "preferred_capabilities": ["capability.prefix", ...],
      "estimated_mods": 8
    }
  ],
  "reasoning": "Brief explanation of key changes made to initial architecture"
}

CRITICAL RULES:
- ALWAYS rename categories to be creative and thematic - DO NOT keep generic names
- DO NOT reduce the number of categories - MAINTAIN or INCREASE the initial category count
- If initial architecture has many categories (10+), keep them or split further - DO NOT merge into fewer
- Create enough categories so each has 5-10 mods ideally (if category has 15+ mods → SPLIT it)
- Be creative and thematic with names - use examples above as inspiration
- Split overloaded categories (15+ mods) into 2-3 sub-categories by logical themes
- Only merge tiny categories (1-2 mods) if they're truly related
- Separate libraries from gameplay mods
- If a category name is generic (e.g., "Combat Mods", "Building Blocks", "Core Libraries") → RENAME it creatively
- Look at mod summaries to understand functionality, then create evocative names that match the modpack's theme
- IMPORTANT: With {len(mods)} mods, you should have AT LEAST {len(initial_architecture.get('categories', []))} categories, preferably MORE if some categories are overloaded
"""

    # Собираем sample summaries модов для понимания их функциональности
    sample_mods_with_summaries = []
    for mod in mods[:15]:  # Первые 15 модов для примера
        mod_name = mod.get('name', mod.get('slug', 'Unknown'))
        mod_summary = mod.get('summary', mod.get('description', ''))[:150]
        mod_caps = mod.get('capabilities', [])[:5]
        is_dep = mod.get('_added_as_dependency', False)
        dep_label = " [DEPENDENCY]" if is_dep else ""
        sample_mods_with_summaries.append(f"  - {mod_name}{dep_label}: {mod_summary}")
        if mod_caps:
            sample_mods_with_summaries.append(f"    Capabilities: {', '.join(mod_caps)}")
    
    mod_summaries_text = "\n".join(sample_mods_with_summaries) if sample_mods_with_summaries else "No mod summaries available"
    
    user_message = f"""USER REQUEST: "{user_prompt}"

INITIAL ARCHITECTURE (skeleton):
{initial_categories_text}

ACTUAL MODS DISTRIBUTION:
{mod_distribution_text}

SAMPLE MODS WITH SUMMARIES (to understand actual functionality):
{mod_summaries_text}

CAPABILITY ANALYSIS:
{capability_analysis_text}

Total mods: {len(mods)} ({mod_analysis['gameplay_count']} gameplay + {mod_analysis['library_count']} libraries)
Initial categories: {len(initial_architecture.get('categories', []))}

IMPORTANT INSTRUCTIONS:
1. Use mod summaries to understand what mods actually do, then create thematic category names that match their functionality
2. DO NOT reduce the number of categories - maintain {len(initial_architecture.get('categories', []))} categories or INCREASE if some are overloaded
3. Look at "ACTUAL MODS DISTRIBUTION" above - if you see "⚠️ OVERLOADED" categories (15+ mods) → SPLIT them into 2-3 sub-categories with creative names
4. If a category would have 15+ mods → SPLIT it into 2-3 sub-categories with creative names IMMEDIATELY
5. Create enough categories so each has 5-10 mods ideally
6. With {len(mods)} mods, you need AT LEAST {max(8, len(initial_architecture.get('categories', [])))} categories for good organization
7. If initial architecture has {len(initial_architecture.get('categories', []))} categories, your refined architecture should have {len(initial_architecture.get('categories', []))} or MORE categories (not fewer!)

Refine the architecture to organize these mods effectively. Return ONLY valid JSON."""

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
                'temperature': 0.8,  # Высокая креативность для названий категорий
                'max_tokens': 2500
            },
            timeout=60
        )
        
        if response.status_code != 200:
            print(f"   ⚠️  AI refinement failed: {response.status_code}")
            return initial_architecture  # Fallback к изначальной архитектуре
        
        result = response.json()
        content = result['choices'][0]['message']['content'].strip()
        
        usage = result.get('usage', {})
        prompt_tokens = usage.get('prompt_tokens', 0)
        completion_tokens = usage.get('completion_tokens', 0)
        total_tokens = usage.get('total_tokens', 0)
        cost = (prompt_tokens * DEEPSEEK_INPUT_COST / 1_000_000) + (completion_tokens * DEEPSEEK_OUTPUT_COST / 1_000_000)
        
        print(f"📥 [Architecture Refiner] Received refined plan")
        print(f"   📊 Tokens: {total_tokens:,} (prompt: {prompt_tokens:,}, completion: {completion_tokens:,})")
        print(f"   💵 Cost: ${cost:.6f}")
        
        # Парсим JSON
        content = content.replace('```json', '').replace('```', '').strip()
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        
        if not json_match:
            print(f"   ⚠️  Could not parse JSON, using initial architecture")
            return initial_architecture
        
        refined_architecture = json.loads(json_match.group())
        
        if 'categories' not in refined_architecture or not refined_architecture['categories']:
            print(f"   ⚠️  No categories in refined plan, using initial architecture")
            return initial_architecture
        
        print(f"✅ [Architecture Refiner] Refined to {len(refined_architecture['categories'])} categories:")
        total_estimated = 0
        for cat in refined_architecture['categories']:
            estimated = cat.get('estimated_mods', 0)
            total_estimated += estimated
            print(f"   📚 {cat['name']}: ~{estimated} mods")
            req_caps = cat.get('required_capabilities', [])
            if req_caps:
                print(f"      Capabilities: {', '.join(req_caps[:5])}")
        
        print(f"   🎯 Total estimated: {total_estimated} mods")
        
        if refined_architecture.get('reasoning'):
            print(f"   💡 Reasoning: {refined_architecture['reasoning'][:150]}...")
        
        # Добавляем метаданные
        refined_architecture['_tokens'] = {
            'prompt_tokens': prompt_tokens,
            'completion_tokens': completion_tokens,
            'total_tokens': total_tokens,
            'cost_usd': cost
        }
        
        refined_architecture['_refined_from'] = {
            'initial_categories': len(initial_architecture.get('categories', [])),
            'final_categories': len(refined_architecture['categories']),
            'total_mods': len(mods)
        }
        
        return refined_architecture
        
    except Exception as e:
        print(f"   ❌ [Architecture Refiner] Error: {e}")
        print(f"   Falling back to initial architecture")
        return initial_architecture


def analyze_mods(mods: List[Dict]) -> Dict:
    """
    Анализирует реальные моды для понимания их распределения
    """
    
    all_capabilities = []
    capability_prefixes = set()
    library_count = 0
    gameplay_count = 0
    
    for mod in mods:
        caps = mod.get('capabilities', [])
        all_capabilities.extend(caps)
        
        # Извлекаем префиксы
        for cap in caps:
            prefix = cap.split('.')[0]
            capability_prefixes.add(prefix)
        
        # Определяем тип мода
        is_library = any(cap.startswith(('api.', 'dependency.', 'compatibility.')) for cap in caps)
        
        if is_library or mod.get('_added_as_dependency'):
            library_count += 1
        else:
            gameplay_count += 1
    
    # Частота capabilities
    capability_frequency = Counter(all_capabilities)
    prefix_frequency = Counter([cap.split('.')[0] for cap in all_capabilities])
    
    return {
        'total_mods': len(mods),
        'gameplay_count': gameplay_count,
        'library_count': library_count,
        'capability_prefixes': list(capability_prefixes),
        'top_capabilities': capability_frequency.most_common(15),
        'top_prefixes': prefix_frequency.most_common(10),
        'all_capabilities': all_capabilities
    }


def format_initial_categories(initial_architecture: Dict) -> str:
    """
    Форматирует изначальные категории для промпта
    """
    lines = []
    for i, cat in enumerate(initial_architecture.get('categories', []), 1):
        lines.append(f"{i}. {cat['name']} (target: {cat.get('target_mods', 0)} mods)")
        req_caps = cat.get('required_capabilities', [])
        if req_caps:
            lines.append(f"   Required: {', '.join(req_caps[:5])}")
    
    return "\n".join(lines)


def format_mod_distribution(mods: List[Dict], initial_architecture: Dict) -> str:
    """
    Показывает как моды распределились бы по изначальным категориям
    """
    from collections import defaultdict
    
    # Простое распределение по первому совпадению capabilities
    distribution = defaultdict(list)
    
    for mod in mods:
        mod_caps = set(mod.get('capabilities', []))
        mod_name = mod.get('name', mod.get('slug', 'Unknown'))
        is_lib = mod.get('_added_as_dependency', False)
        
        assigned = False
        for cat in initial_architecture.get('categories', []):
            cat_caps = set(cat.get('required_capabilities', []) + cat.get('preferred_capabilities', []))
            
            # Проверка по префиксам
            for mod_cap in mod_caps:
                for cat_cap in cat_caps:
                    if mod_cap.split('.')[0] == cat_cap.split('.')[0]:
                        label = f"{mod_name} {'[LIB]' if is_lib else ''}"
                        distribution[cat['name']].append(label)
                        assigned = True
                        break
                if assigned:
                    break
            if assigned:
                break
        
        if not assigned:
            label = f"{mod_name} {'[LIB]' if is_lib else ''}"
            distribution['Unassigned'].append(label)
    
    # Форматируем с выделением перегруженных категорий
    lines = []
    for cat_name in sorted(distribution.keys(), key=lambda x: -len(distribution[x])):
        mods_in_cat = distribution[cat_name]
        mod_count = len(mods_in_cat)
        
        # Выделяем перегруженные категории
        if mod_count >= 15:
            lines.append(f"⚠️  {cat_name}: {mod_count} mods (OVERLOADED - MUST SPLIT into 2-3 sub-categories)")
        elif mod_count >= 10:
            lines.append(f"📊 {cat_name}: {mod_count} mods (consider splitting)")
        else:
            lines.append(f"{cat_name}: {mod_count} mods")
        
        if mod_count <= 5:
            for mod in mods_in_cat:
                lines.append(f"  - {mod}")
        else:
            for mod in mods_in_cat[:3]:
                lines.append(f"  - {mod}")
            lines.append(f"  ... and {mod_count - 3} more")
    
    return "\n".join(lines)


def format_capability_analysis(mod_analysis: Dict) -> str:
    """
    Форматирует анализ capabilities для промпта
    """
    lines = []
    lines.append(f"Top capability prefixes:")
    for prefix, count in mod_analysis['top_prefixes']:
        lines.append(f"  - {prefix}: {count} occurrences")
    
    lines.append(f"\nTop specific capabilities:")
    for cap, count in mod_analysis['top_capabilities'][:10]:
        lines.append(f"  - {cap}: {count} mods")
    
    return "\n".join(lines)


def distribute_mods_to_categories(
    categories: List[Dict],
    mods: List[Dict],
    user_prompt: str,
    deepseek_key: str = DEEPSEEK_API_KEY
) -> Dict[str, List[Dict]]:
    """
    Распределяет моды по категориям с использованием AI.
    Важно: categories уже должны иметь креативные названия от Architecture Refiner.
    
    Использует AI для точного распределения модов по категориям
    
    Args:
        categories: Список категорий от Refiner
        mods: Список модов с полной информацией
        user_prompt: Запрос пользователя (для контекста)
        deepseek_key: API ключ
    
    Returns:
        Dict[category_name] -> List[mods]
    """
    
    print(f"\n🎯 [Mod Distribution] AI-based distribution to categories...")
    print(f"   Categories: {len(categories)}")
    print(f"   Mods to distribute: {len(mods)}")
    
    # Загружаем capabilities reference
    caps_ref = load_capabilities_reference()
    
    # Создаём множества capabilities по категориям
    library_caps = set(caps_ref['categories']['compatibility'])
    
    # Performance: УБИРАЕМ render.pipeline (двусмысленная capability)
    performance_caps = set(caps_ref['categories']['performance']) - {'render.pipeline'}
    
    # Graphics & Shaders: строгие graphics capabilities (БЕЗ visual.effects - слишком broad)
    graphics_caps_strict = {
        'shaders.runtime',
        'postprocessing.pipeline',
        'sky.effects',
        'lighting.system',
        'particles.system',
        'water.rendering',
        'ctm.connected_textures',
        'render.pipeline'  # будем проверять отдельно
    }
    
    ui_caps = set(caps_ref['categories']['ui'])
    gameplay_caps = set(
        caps_ref['categories']['gameplay'] + 
        caps_ref['categories']['world_generation'] +
        caps_ref['categories']['atmosphere']
    )
    
    # Отделяем библиотеки, performance, graphics и геймплейные моды
    library_mods = []
    performance_mods = []
    graphics_mods = []
    gameplay_mods = []
    
    # Debug: соберём причины классификации с весами
    debug_classifications = []
    
    # Загружаем библиотечные теги один раз
    library_tags_set = get_library_tags()
    
    for mod in mods:
        mod_slug = mod.get('slug', 'unknown')
        mod_caps = mod.get('capabilities', [])
        mod_caps_set = set(mod_caps)
        mod_tags = set(mod.get('tags', []))
        mod_name_lower = mod.get('name', '').lower()
        mod_summary_lower = mod.get('summary', '').lower()
        
        # КРИТЕРИЙ 1 (ПРИОРИТЕТ): Явно помечен как dependency
        # Используем формализованную систему правил с весами
        if mod.get('_added_as_dependency', False):
            category, reason, weight = classify_dependency_mod(
                mod=mod,
                mod_tags=mod_tags,
                mod_caps_set=mod_caps_set,
                mod_name_lower=mod_name_lower,
                library_tags_set=library_tags_set,
                library_caps=library_caps,
                performance_caps=performance_caps,
                graphics_caps_strict=graphics_caps_strict,
                gameplay_caps=gameplay_caps
            )
            
            # Распределяем по категориям на основе результата классификации
            if category == 'library':
                library_mods.append(mod)
                debug_classifications.append(f"✅ {mod_slug} → LIBRARY (weight: {weight}, {reason})")
            elif category == 'performance':
                performance_mods.append(mod)
                debug_classifications.append(f"⚡ {mod_slug} → PERFORMANCE (weight: {weight}, {reason})")
            elif category == 'graphics':
                graphics_mods.append(mod)
                debug_classifications.append(f"🎨 {mod_slug} → GRAPHICS (weight: {weight}, {reason})")
            else:  # gameplay
                gameplay_mods.append(mod)
                debug_classifications.append(f"❌ {mod_slug} → GAMEPLAY (weight: {weight}, {reason})")
            continue
        
        # КРИТЕРИЙ 2 (ПРИОРИТЕТ): Обычные моды (не dependencies)
        # Используем формализованную систему правил с весами
        category, reason, weight = classify_regular_mod(
            mod=mod,
            mod_tags=mod_tags,
            mod_caps_set=mod_caps_set,
            mod_name_lower=mod_name_lower,
            mod_summary_lower=mod_summary_lower,
            library_tags_set=library_tags_set,
            library_caps=library_caps,
            performance_caps=performance_caps,
            graphics_caps_strict=graphics_caps_strict,
            gameplay_caps=gameplay_caps,
            ui_caps=ui_caps
        )
        
        # Распределяем по категориям на основе результата классификации
        if category == 'library':
            library_mods.append(mod)
            debug_classifications.append(f"✅ {mod_slug} → LIBRARY (weight: {weight}, {reason})")
        elif category == 'performance':
            performance_mods.append(mod)
            debug_classifications.append(f"⚡ {mod_slug} → PERFORMANCE (weight: {weight}, {reason})")
        elif category == 'graphics':
            graphics_mods.append(mod)
            debug_classifications.append(f"🎨 {mod_slug} → GRAPHICS (weight: {weight}, {reason})")
        else:  # gameplay
            gameplay_mods.append(mod)
            debug_classifications.append(f"❌ {mod_slug} → GAMEPLAY (weight: {weight}, {reason})")
        continue
    
    print(f"   📊 Split: {len(gameplay_mods)} gameplay, {len(graphics_mods)} graphics, {len(performance_mods)} performance, {len(library_mods)} libraries")
    
    # Debug: показываем ВСЕ классификации для анализа
    print(f"\n🔍 [Library Detection Debug] All {len(debug_classifications)} classifications:")
    for classification in debug_classifications:
        print(f"   {classification}")
    
    # Находим категории для библиотек, performance и graphics модов
    library_category = None
    performance_category = None
    graphics_category = None
    
    # Ищем категории по capabilities
    for cat in categories:
        cat_caps = set(cat.get('required_capabilities', []))
        
        # Library category: compatibility capabilities
        if cat_caps & library_caps and not library_category:
            library_category = cat['name']
            print(f"   🔍 Found library category by capabilities: '{library_category}'")
        
        # Performance category: performance capabilities (ПЕРВЫМ, чтобы не перезаписать graphics)
        # Ищем категорию с performance.optimization capability или похожим названием
        if cat_caps & performance_caps and not performance_category:
            cat_name_lower = cat['name'].lower()
            # Приоритет: категории с "performance" или "optimization" в названии
            if 'performance' in cat_name_lower or 'optimization' in cat_name_lower:
                # НЕ берем категории с graphics capabilities как performance
                if not (cat_caps & graphics_caps_strict):
                    performance_category = cat['name']
                    print(f"   🔍 Found performance category by capabilities: '{performance_category}'")
        
        # Graphics category: graphics capabilities (strict) - ПОСЛЕ performance
        # ВАЖНО: НЕ берём библиотечные категории для graphics модов
        if cat_caps & graphics_caps_strict and not graphics_category:
            # Исключаем библиотечные категории (которые имеют library capabilities)
            if not (cat_caps & library_caps):
                graphics_category = cat['name']
                print(f"   🔍 Found graphics category by capabilities: '{graphics_category}'")
        
        # Если performance категория еще не найдена, ищем любую с performance caps (но не graphics)
        if cat_caps & performance_caps and not performance_category:
            # НЕ берем категории с graphics capabilities как performance
            if not (cat_caps & graphics_caps_strict):
                performance_category = cat['name']
                print(f"   🔍 Found performance category by capabilities: '{performance_category}'")
    
    # Размещаем моды в найденные категории
    all_distributions = defaultdict(list)
    
    # Библиотеки - разделяем на подкатегории если их слишком много (20+)
    if library_category and library_mods:
        if len(library_mods) >= 20:
            # Разделяем библиотеки на подкатегории
            api_libs = []  # API библиотеки (api.exposed)
            core_libs = []  # Core библиотеки (dependency.library, core-mod)
            compat_libs = []  # Compatibility библиотеки (compatibility.bridge)
            other_libs = []  # Остальные
            
            for lib_mod in library_mods:
                lib_caps = set(lib_mod.get('capabilities', []))
                lib_tags = set(lib_mod.get('tags', []))
                
                if 'api.exposed' in lib_caps or any('api' in tag for tag in lib_tags):
                    api_libs.append(lib_mod)
                elif 'dependency.library' in lib_caps or 'core-mod' in lib_tags:
                    core_libs.append(lib_mod)
                elif 'compatibility.bridge' in lib_caps:
                    compat_libs.append(lib_mod)
                else:
                    other_libs.append(lib_mod)
            
            # Размещаем по подкатегориям
            if api_libs:
                api_cat_name = library_category.replace('Archives', 'APIs').replace('Foundations', 'APIs')
                all_distributions[api_cat_name] = api_libs
                print(f"   📚 Placed {len(api_libs)} API libraries into '{api_cat_name}'")
            
            if core_libs:
                core_cat_name = library_category.replace('Archives', 'Core').replace('APIs', 'Core')
                all_distributions[core_cat_name] = core_libs
                print(f"   📚 Placed {len(core_libs)} core libraries into '{core_cat_name}'")
            
            if compat_libs:
                compat_cat_name = library_category.replace('Archives', 'Compatibility').replace('Core', 'Compatibility')
                all_distributions[compat_cat_name] = compat_libs
                print(f"   📚 Placed {len(compat_libs)} compatibility libraries into '{compat_cat_name}'")
            
            if other_libs:
                all_distributions[library_category] = other_libs
                print(f"   📚 Placed {len(other_libs)} other libraries into '{library_category}'")
        else:
            all_distributions[library_category] = library_mods
            print(f"   📚 Placed {len(library_mods)} libraries into '{library_category}'")
    elif library_mods:
        # Создаём тематическое название на основе промпта
        prompt_lower = user_prompt.lower()
        if 'medieval' in prompt_lower or 'fantasy' in prompt_lower or 'castle' in prompt_lower:
            library_category = 'Castle Foundations'
        elif 'tech' in prompt_lower or 'automation' in prompt_lower:
            library_category = 'Core Systems'
        elif 'adventure' in prompt_lower or 'exploration' in prompt_lower:
            library_category = 'Explorer\'s Toolkit'
        else:
            library_category = 'Essential Libraries'
        all_distributions[library_category] = library_mods
        print(f"   ⚠️  No library category found, created fallback '{library_category}'")
    
    # Graphics моды
    print(f"   🔍 DEBUG: graphics_category='{graphics_category}', len(graphics_mods)={len(graphics_mods)}")
    if graphics_category and graphics_mods:
        all_distributions[graphics_category] = graphics_mods
        print(f"   🎨 Placed {len(graphics_mods)} graphics mods into '{graphics_category}'")
    elif graphics_mods:
        graphics_category = 'Graphics & Shaders'
        all_distributions[graphics_category] = graphics_mods
        print(f"   ⚠️  No graphics category found, created fallback '{graphics_category}'")
    else:
        print(f"   ⚠️  DEBUG: Skipped graphics placement (category={graphics_category}, mods={len(graphics_mods)})")
    
    # Performance моды
    print(f"   🔍 DEBUG: performance_category='{performance_category}', len(performance_mods)={len(performance_mods)}")
    if performance_mods:
        # Логируем какие performance моды есть
        perf_mod_names = [m.get('name', m.get('slug', 'Unknown')) for m in performance_mods]
        print(f"   🔍 Performance mods found: {', '.join(perf_mod_names[:5])}")
        if len(performance_mods) > 5:
            print(f"      ... and {len(performance_mods) - 5} more")
    
    if performance_category and performance_mods:
        # Проверяем, что performance_category не совпадает с graphics_category
        if performance_category == graphics_category:
            # Если совпадает - создаем отдельную категорию Performance
            performance_category = 'Performance & Optimization'
            all_distributions[performance_category] = performance_mods
            print(f"   ⚡ Placed {len(performance_mods)} performance mods into '{performance_category}' (separated from graphics)")
        else:
            all_distributions[performance_category] = performance_mods
            print(f"   ⚡ Placed {len(performance_mods)} performance mods into '{performance_category}'")
    elif performance_mods:
        # Если performance моды есть, но категория не найдена - создаём или ищем по названию
        # Сначала пытаемся найти категорию по названию
        found_perf_cat = None
        for cat in categories:
            cat_name_lower = cat['name'].lower()
            if 'performance' in cat_name_lower or 'optimization' in cat_name_lower:
                found_perf_cat = cat['name']
                break
        
        if found_perf_cat:
            all_distributions[found_perf_cat] = performance_mods
            performance_category = found_perf_cat
            print(f"   ⚡ Found performance category by name: '{found_perf_cat}', placed {len(performance_mods)} mods")
        else:
            performance_category = 'Performance & Optimization'
            all_distributions[performance_category] = performance_mods
            print(f"   ⚠️  No performance category found, created fallback '{performance_category}' with {len(performance_mods)} mods")
    else:
        print(f"   ⚠️  DEBUG: Skipped performance placement (category={performance_category}, mods={len(performance_mods)})")
    
    # Формируем список gameplay категорий (ИСКЛЮЧАЕМ библиотечные, graphics и performance)
    gameplay_categories = []
    for cat in categories:
        # Пропускаем технические категории
        # ВАЖНО: Если performance_category совпадает с graphics_category, мы создали отдельную категорию Performance
        # Поэтому проверяем оригинальное название категории, а не performance_category переменную
        cat_name = cat['name']
        if cat_name == library_category:
            continue
        if cat_name == graphics_category and cat_name != performance_category:
            continue
        if cat_name == performance_category and cat_name != graphics_category:
            continue
        # Если категория совпадает и с graphics, и с performance - пропускаем (она уже обработана)
        if cat_name == graphics_category and cat_name == performance_category:
            continue
        gameplay_categories.append(cat)
    
    # Распределяем все gameplay моды через AI
    mods = gameplay_mods
    print(f"   🤖 Distributing {len(mods)} gameplay mods via AI...")
    
    # Форматируем категории для промпта
    categories_text = []
    
    for i, cat in enumerate(gameplay_categories, 1):
        cat_name = cat['name']
        cat_desc = cat.get('description', '')
        cat_caps = cat.get('required_capabilities', []) + cat.get('preferred_capabilities', [])
        
        # Добавляем явное описание для критичных категорий (без хардкода конкретных модов)
        if 'knight' in cat_name.lower() or 'armory' in cat_name.lower():
            cat_desc = cat_desc or "Weapons and armor EQUIPMENT - mods that add new weapons, shields, armor items"
        elif 'combat mastery' in cat_name.lower() or 'combat arts' in cat_name.lower():
            cat_desc = cat_desc or "Combat SYSTEM/MECHANICS - mods that overhaul combat mechanics, combat systems, combat behavior"
        elif 'performance' in cat_name.lower():
            cat_desc = cat_desc or "Performance optimization mods - mods that improve FPS, reduce lag, optimize rendering"
        
        categories_text.append(f"{i}. {cat_name}")
        if cat_desc:
            categories_text.append(f"   Purpose: {cat_desc}")
        if cat_caps:
            categories_text.append(f"   Capabilities: {', '.join(cat_caps[:5])}")
        categories_text.append(f"   Target: ~{cat.get('estimated_mods', 0)} mods")
        categories_text.append("")  # Пустая строка для читаемости
    
    categories_formatted = "\n".join(categories_text)
    
    # Форматируем моды для промпта (батчами по 20 для избежания timeout)
    batch_size = 20  # Уменьшено с 30 для более быстрых ответов AI
    # all_distributions уже создан выше с библиотеками - НЕ перезаписываем!
    
    for batch_idx in range(0, len(mods), batch_size):
        batch = mods[batch_idx:batch_idx + batch_size]
        
        mods_text = []
        for i, mod in enumerate(batch, 1):  # Локальная нумерация внутри батча (1-30)
            mod_info = [f"{i}. {mod.get('name', mod.get('slug', 'Unknown'))}"]
            
            # Summary - КРИТИЧНО: это основной источник информации о функциональности мода
            summary = mod.get('summary', mod.get('description', ''))
            if summary:
                # Увеличиваем лимит summary для более полной информации
                summary_text = summary[:250] if len(summary) > 250 else summary
                mod_info.append(f"   Summary: {summary_text}")
                if len(summary) > 250:
                    mod_info.append(f"   [Summary truncated, full length: {len(summary)} chars]")
            
            # Tags
            tags = mod.get('tags', [])
            if tags:
                mod_info.append(f"   Tags: {', '.join(tags[:5])}")
            
            # Capabilities
            caps = mod.get('capabilities', [])
            if caps:
                cap_prefixes = list(set([c.split('.')[0] for c in caps]))
                mod_info.append(f"   Capabilities: {', '.join(cap_prefixes[:5])}")
            
            # Флаг библиотеки
            if mod.get('_added_as_dependency'):
                mod_info.append(f"   [LIBRARY/DEPENDENCY]")
            
            mods_text.append("\n".join(mod_info))
        
        mods_formatted = "\n\n".join(mods_text)
        
        system_prompt = """You are an expert at organizing Minecraft mods into logical, theme-based categories.

Your task: Assign each mod to the BEST matching category based on PATTERN RECOGNITION:

**ANALYSIS PRIORITY (in order):**

1. **READ THE SUMMARY FIRST AND CAREFULLY** (HIGHEST PRIORITY)
   - The summary describes what the mod actually DOES
   - Look for keywords: "adds", "overhauls", "changes", "improves", "introduces"
   - If summary says "adds new weapons" → equipment category
   - If summary says "overhauls combat system" → combat mechanics category
   - Summary is the PRIMARY source of truth - trust it over everything else

2. **Match summary meaning to category purpose**
   - Read the category's "Purpose" field
   - Does the mod's summary match the category's purpose?
   - Equipment mods (weapons, armor) → equipment categories
   - System mods (combat system, progression) → system/mechanics categories

3. **Mod's capabilities** (confirmation only)
   - Capabilities confirm what the summary says
   - If summary and capabilities conflict, trust the summary
   - Use capabilities to understand technical scope, not primary function

4. **Mod's tags** (secondary confirmation)
   - Tags provide additional context
   - Use tags to confirm what the summary says
   - Don't rely solely on tags - summary is more important

5. **Category's theme and description**
   - Each category has a THEME and PURPOSE (read the "Purpose" field)
   - Match mod's PRIMARY function (from summary) to category's purpose
   - Don't force mods into unrelated categories

**ANALYSIS METHODOLOGY:**

1. **READ THE SUMMARY FIRST** - The summary tells you what the mod actually DOES
   - If summary says "adds new weapons" → equipment category
   - If summary says "overhauls combat system" → combat mechanics category
   - If summary says "adds decorative blocks" → decoration/building category
   - Summary is the PRIMARY source of truth for mod functionality

2. **Match summary meaning to category purpose:**
   - Equipment/items mods (weapons, armor, tools) → "Knight's Arsenal" / "Royal Armory" type categories
   - System/mechanics mods (combat system, progression system) → "Combat Mastery" / "Combat Arts" type categories
   - Building/decoration mods → "Castle Architecture" / "Courtly Decor" type categories
   - Visual/graphics mods → "Enchanted Visuals" / "Atmospheric Lighting" type categories

3. **Use capabilities as confirmation:**
   - Capabilities confirm what the summary says
   - If summary and capabilities conflict, trust the summary (it's more descriptive)

4. **Category purpose matters:**
   - Read each category's "Purpose" field carefully
   - Match mod's PRIMARY function (from summary) to category's purpose
   - Don't force mods into categories that don't match their primary function

**STRICT RULES:**
- ONLY gameplay mods in this batch (libraries already separated)
- **READ EACH MOD'S SUMMARY CAREFULLY** - it describes what the mod actually does
- Match mod's PRIMARY function (from summary) to category's purpose (from description)
- If summary says "adds weapons/armor" → equipment category (Knight's Arsenal, Royal Armory)
- If summary says "overhauls combat system" or "changes combat mechanics" → combat mechanics category (Combat Mastery, Combat Arts)
- If summary says "adds blocks" or "decoration" → building/decoration category
- DO NOT randomly assign mods - always base decision on summary content
- DO NOT put gameplay mods into technical/foundation categories
- Distribute evenly across relevant categories
- If a mod fits multiple categories, choose the PRIMARY purpose based on summary
- If truly unsure, choose closest thematic match based on summary meaning

**VALIDATION:**
- Every mod MUST be assigned to exactly ONE category
- Use EXACT category names from the provided list
- Provide brief, clear reason for each assignment

OUTPUT FORMAT (JSON only):
{
  "assignments": [
    {
      "mod_index": 1,
      "category": "Category Name",
      "reason": "Brief reason based on mod's primary function"
    }
  ]
}
"""

        user_message = f"""USER REQUEST: "{user_prompt}"

CATEGORIES:
{categories_formatted}

MODS TO DISTRIBUTE (batch {batch_idx // batch_size + 1}):
{mods_formatted}

Assign each mod to the best category. Return ONLY valid JSON."""

        # Retry logic для timeout
        max_retries = 2
        response = None
        
        for attempt in range(max_retries):
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
                        'max_tokens': 2000
                    },
                    timeout=90  # Увеличен с 45 до 90 секунд
                )
                break  # Успешно - выходим из retry loop
            except requests.exceptions.Timeout:
                if attempt < max_retries - 1:
                    print(f"   ⏱️  Timeout on attempt {attempt + 1}/{max_retries}, retrying...")
                    continue
                else:
                    print(f"   ❌ All retry attempts failed for batch {batch_idx // batch_size + 1}")
                    response = None
                    break
            except Exception as e:
                print(f"   ❌ Error in batch {batch_idx // batch_size + 1}: {e}")
                response = None
                break
        
        if not response:
            continue
        
        try:
            
            if response.status_code != 200:
                print(f"   ⚠️  AI distribution failed for batch {batch_idx // batch_size + 1}: {response.status_code}")
                continue
            
            result = response.json()
            content = result['choices'][0]['message']['content'].strip()
            
            # Парсим JSON
            content = content.replace('```json', '').replace('```', '').strip()
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            
            if not json_match:
                print(f"   ⚠️  Could not parse JSON for batch {batch_idx // batch_size + 1}")
                continue
            
            assignments = json.loads(json_match.group())
            
            # Применяем assignments
            batch_assigned = 0
            batch_errors = []
            
            for assignment in assignments.get('assignments', []):
                mod_index = assignment.get('mod_index', 0) - 1  # 1-indexed -> 0-indexed
                category_name = assignment.get('category')
                
                # Проверка индекса
                if mod_index < 0 or mod_index >= len(batch):
                    batch_errors.append(f"Invalid index {mod_index + 1} (batch size: {len(batch)})")
                    continue
                
                # Проверка категории (только gameplay категории)
                valid_categories = [cat['name'] for cat in gameplay_categories]
                if category_name not in valid_categories:
                    mod_name = batch[mod_index].get('name', 'Unknown')
                    # Если AI пытается поместить в библиотечную - ошибка
                    batch_errors.append(f"{mod_name} -> '{category_name}' (invalid/library category)")
                    continue
                
                # Распределяем
                mod = batch[mod_index]
                all_distributions[category_name].append(mod)
                batch_assigned += 1
            
            batch_num = batch_idx // batch_size + 1
            total_batches = (len(mods) + batch_size - 1) // batch_size
            
            if batch_errors:
                print(f"   ⚠️  Batch {batch_num}/{total_batches}: {batch_assigned}/{len(batch)} assigned, {len(batch_errors)} errors")
                for error in batch_errors[:3]:  # Показываем первые 3
                    print(f"      - {error}")
                if len(batch_errors) > 3:
                    print(f"      ... and {len(batch_errors) - 3} more errors")
            else:
                print(f"   ✅ Batch {batch_num}/{total_batches}: {batch_assigned}/{len(batch)} mods assigned")
            
        except Exception as e:
            print(f"   ❌ Error in batch {batch_idx // batch_size + 1}: {e}")
            continue
    
    print(f"\n✅ [Mod Distribution] AI distribution complete")
    print(f"   Categories with mods: {len([cat for cat in all_distributions.values() if len(cat) > 0])}")
    
    # ========== VALIDATION & FALLBACK ==========
    print(f"\n🔍 [Validation] Checking distribution quality...")
    
    # Проверка 1: Все ли моды распределены?
    assigned_mods = set()
    for category_mods in all_distributions.values():
        for mod in category_mods:
            mod_id = mod.get('source_id', mod.get('project_id', ''))
            assigned_mods.add(mod_id)
    
    all_mod_ids = set()
    for mod in mods:
        mod_id = mod.get('source_id', mod.get('project_id', ''))
        all_mod_ids.add(mod_id)
    for mod in library_mods:
        mod_id = mod.get('source_id', mod.get('project_id', ''))
        all_mod_ids.add(mod_id)
    for mod in graphics_mods:
        mod_id = mod.get('source_id', mod.get('project_id', ''))
        all_mod_ids.add(mod_id)
    for mod in performance_mods:
        mod_id = mod.get('source_id', mod.get('project_id', ''))
        all_mod_ids.add(mod_id)
    
    unassigned_mods = []
    unassigned_dependencies = []
    
    for mod in mods + library_mods + graphics_mods + performance_mods:
        mod_id = mod.get('source_id', mod.get('project_id', ''))
        if mod_id not in assigned_mods:
            unassigned_mods.append(mod)
            # Отдельно отслеживаем зависимости
            if mod.get('_added_as_dependency', False):
                unassigned_dependencies.append(mod)
    
    if unassigned_mods:
        print(f"   ⚠️  Found {len(unassigned_mods)} unassigned mods")
        
        # КРИТИЧНО: Зависимости должны попасть в библиотечную категорию
        if unassigned_dependencies:
            print(f"      ⚠️  CRITICAL: {len(unassigned_dependencies)} dependencies not assigned!")
            for dep in unassigned_dependencies[:5]:
                dep_name = dep.get('name', dep.get('slug', 'Unknown'))
                print(f"         - {dep_name} (source_id: {dep.get('source_id', 'unknown')[:8]}...)")
            if len(unassigned_dependencies) > 5:
                print(f"         ... and {len(unassigned_dependencies) - 5} more dependencies")
            
            # Автоматически добавляем зависимости в библиотечную категорию
            if library_category:
                all_distributions[library_category].extend(unassigned_dependencies)
                print(f"      ✅ Auto-placed {len(unassigned_dependencies)} dependencies into '{library_category}'")
            else:
                # Если библиотечной категории нет - создаём тематическое название на основе промпта
                # Пытаемся создать тематическое название на основе user_prompt
                prompt_lower = user_prompt.lower()
                if 'medieval' in prompt_lower or 'fantasy' in prompt_lower or 'castle' in prompt_lower:
                    library_category = 'Castle Foundations'
                elif 'tech' in prompt_lower or 'automation' in prompt_lower:
                    library_category = 'Core Systems'
                elif 'adventure' in prompt_lower or 'exploration' in prompt_lower:
                    library_category = 'Explorer\'s Toolkit'
                else:
                    library_category = 'Essential Libraries'  # Более нейтральное, но не "Libraries & APIs"
                all_distributions[library_category] = unassigned_dependencies
                print(f"      ✅ Created '{library_category}' category for {len(unassigned_dependencies)} dependencies")
            
            # Убираем зависимости из unassigned_mods
            unassigned_mods = [m for m in unassigned_mods if not m.get('_added_as_dependency', False)]
        
        # Остальные нераспределённые моды идём в General
        if unassigned_mods:
            # Fallback: создаём категорию General если её нет
            general_category = None
            for cat in categories:
                if 'general' in cat['name'].lower() or 'misc' in cat['name'].lower():
                    general_category = cat['name']
                    break
            
            if not general_category:
                general_category = 'General'
                all_distributions[general_category] = []
                print(f"   ➕ Creating fallback category: '{general_category}'")
            
            all_distributions[general_category].extend(unassigned_mods)
            print(f"   ✅ Placed {len(unassigned_mods)} unassigned mods into '{general_category}'")
    else:
        print(f"   ✅ All mods assigned")
    
    # Проверка 2: Пустые категории
    empty_categories = [cat['name'] for cat in categories if len(all_distributions.get(cat['name'], [])) == 0]
    if empty_categories:
        print(f"   ⚠️  {len(empty_categories)} empty categories: {', '.join(empty_categories[:3])}{'...' if len(empty_categories) > 3 else ''}")
    else:
        print(f"   ✅ No empty categories")
    
    # Проверка 3: Перегруженные категории (20+ модов)
    overloaded_categories = []
    for cat_name, cat_mods in all_distributions.items():
        if len(cat_mods) >= 20:
            overloaded_categories.append((cat_name, len(cat_mods)))
    
    if overloaded_categories:
        print(f"   ⚠️  {len(overloaded_categories)} overloaded categories (20+ mods):")
        for cat_name, count in overloaded_categories[:3]:
            print(f"      - {cat_name}: {count} mods (consider splitting)")
        if len(overloaded_categories) > 3:
            print(f"      ... and {len(overloaded_categories) - 3} more")
    else:
        print(f"   ✅ No overloaded categories (all <20 mods)")
    
    # Проверка 4: Распределение по категориям
    total_mods = len(mods) + len(library_mods) + len(graphics_mods) + len(performance_mods)
    print(f"\n📊 [Distribution Summary]")
    print(f"   Total mods: {total_mods}")
    
    # Сортируем по количеству модов
    sorted_categories = sorted(all_distributions.items(), key=lambda x: len(x[1]), reverse=True)
    
    for cat_name, cat_mods in sorted_categories[:5]:  # Топ-5 категорий
        percentage = (len(cat_mods) / total_mods * 100) if total_mods > 0 else 0
        print(f"   • {cat_name}: {len(cat_mods)} mods ({percentage:.1f}%)")
    
    if len(sorted_categories) > 5:
        remaining_mods = sum(len(mods) for _, mods in sorted_categories[5:])
        remaining_percentage = (remaining_mods / total_mods * 100) if total_mods > 0 else 0
        print(f"   • Other {len(sorted_categories) - 5} categories: {remaining_mods} mods ({remaining_percentage:.1f}%)")
    
    print(f"\n✅ [Mod Distribution] Validation complete")
    
    return dict(all_distributions)
