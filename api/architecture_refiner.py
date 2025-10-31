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

def load_capabilities_reference():
    global CAPS_REFERENCE
    if CAPS_REFERENCE is None:
        caps_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'capabilities_reference.json')
        with open(caps_path, 'r', encoding='utf-8') as f:
            CAPS_REFERENCE = json.load(f)
    return CAPS_REFERENCE


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

1. **Preserve theme and structure:**
   - Keep the initial category themes/names where appropriate
   - Expand naturally from the skeleton (don't throw it away)
   - Maintain the modpack's core identity from user's request

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
   - Avoid: 20+ mod categories (too cluttered)
   - Avoid: 1-2 mod categories (merge with related category)

5. **Use actual capabilities:**
   - Look at what capabilities the mods ACTUALLY have
   - Group mods with related capability prefixes
   - Don't force mods into wrong categories

6. **Creative naming:**
   - Category names should reflect the modpack's THEME
   - Use evocative, thematic names (not just technical terms)
   - Example: "Enchanted Armory" instead of "Combat Mods"
   - Example: "Castle Foundations" instead of "Building Mods"

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

RULES:
- Create enough categories so each has 5-10 mods ideally
- Be creative and thematic with names
- Split overloaded categories logically
- Merge tiny categories into related ones
- Separate libraries from gameplay mods
"""

    user_message = f"""USER REQUEST: "{user_prompt}"

INITIAL ARCHITECTURE (skeleton):
{initial_categories_text}

ACTUAL MODS DISTRIBUTION:
{mod_distribution_text}

CAPABILITY ANALYSIS:
{capability_analysis_text}

Total mods: {len(mods)} ({mod_analysis['gameplay_count']} gameplay + {mod_analysis['library_count']} libraries)

Refine the architecture to organize these mods effectively. Create enough categories so each has 5-10 mods ideally.
Return ONLY valid JSON."""

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
                'temperature': 0.4,  # Немного выше для креативности в названиях
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
    
    # Форматируем
    lines = []
    for cat_name in sorted(distribution.keys(), key=lambda x: -len(distribution[x])):
        mods_in_cat = distribution[cat_name]
        lines.append(f"{cat_name}: {len(mods_in_cat)} mods")
        if len(mods_in_cat) <= 5:
            for mod in mods_in_cat:
                lines.append(f"  - {mod}")
        else:
            for mod in mods_in_cat[:3]:
                lines.append(f"  - {mod}")
            lines.append(f"  ... and {len(mods_in_cat) - 3} more")
    
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
    
    # Debug: соберём причины классификации
    debug_classifications = []
    
    # Integration моды которые являются tech/energy мостами, а не библиотеками
    TECH_INTEGRATION_KEYWORDS = {
        'energy', 'electricity', 'power', 'voltage', 'joules', 'forge energy', 'rf', 'fe converter'
    }
    
    for mod in mods:
        is_lib = False
        mod_slug = mod.get('slug', 'unknown')
        classification_reason = None
        mod_caps = mod.get('capabilities', [])
        mod_name_lower = mod.get('name', '').lower()
        mod_summary_lower = mod.get('summary', '').lower()
        
        # КРИТЕРИЙ 1 (ПРИОРИТЕТ): Явно помечен как dependency
        if mod.get('_added_as_dependency', False):
            # Проверка: это чистая библиотека, gameplay, performance или graphics мод?
            mod_caps_set = set(mod_caps)
            gameplay_intersection = mod_caps_set & gameplay_caps
            performance_intersection = mod_caps_set & performance_caps
            graphics_intersection = mod_caps_set & graphics_caps_strict
            
            # Если dependency имеет gameplay capabilities → это gameplay мод (farmers-delight, mekanism)
            if gameplay_intersection:
                gameplay_mods.append(mod)
                debug_classifications.append(f"❌ {mod_slug} → GAMEPLAY (dependency with gameplay caps: {list(gameplay_intersection)[:2]})")
                continue
            
            # Если dependency имеет performance capabilities → PERFORMANCE (sodium)
            if performance_intersection:
                performance_mods.append(mod)
                debug_classifications.append(f"⚡ {mod_slug} → PERFORMANCE (dependency with perf caps: {list(performance_intersection)[:2]})")
                continue
            
            # Если dependency имеет graphics capabilities → GRAPHICS
            if graphics_intersection:
                graphics_mods.append(mod)
                debug_classifications.append(f"🎨 {mod_slug} → GRAPHICS (dependency with graphics caps: {list(graphics_intersection)[:2]})")
                continue
            
            # Иначе → чистая библиотека
            library_mods.append(mod)
            debug_classifications.append(f"✅ {mod_slug} → LIBRARY (_added_as_dependency=True)")
            continue
        
        # КРИТЕРИЙ 2 (ПРИОРИТЕТ): Capabilities-based classification
        mod_caps_set = set(mod_caps)
        
        # 2a. Library capabilities (compatibility) — с проверкой контекста
        lib_intersection = mod_caps_set & library_caps
        if lib_intersection:
            # Проверка 1: tech/energy integration моды
            is_tech_integration = any(
                keyword in mod_name_lower or keyword in mod_summary_lower 
                for keyword in TECH_INTEGRATION_KEYWORDS
            )
            
            if is_tech_integration and 'compatibility.integration' in lib_intersection:
                gameplay_mods.append(mod)
                debug_classifications.append(f"❌ {mod_slug} → GAMEPLAY (tech integration, not library)")
                continue
            
            # Проверка 2: compatibility мод с контентом (рецепты, итемы, блоки)
            content_keywords = [
                'recipe', 'recipes', 'item', 'items', 'block', 'blocks', 'food', 'foods',
                'add', 'adds', 'new', 'craft', 'crafting'
            ]
            has_content = any(keyword in mod_summary_lower for keyword in content_keywords)
            
            if 'compatibility.integration' in lib_intersection and has_content:
                # Это compatibility мод с gameplay контентом (Vampire's Delight)
                gameplay_mods.append(mod)
                debug_classifications.append(f"❌ {mod_slug} → GAMEPLAY (compat with content)")
                continue
            
            # Чистая библиотека
            library_mods.append(mod)
            debug_classifications.append(f"✅ {mod_slug} → LIBRARY (caps: {list(lib_intersection)[:2]})")
            continue
        
        # 2b. Graphics & Shaders capabilities → Check if pure graphics or gameplay with visuals
        # Строгая проверка: должны быть строгие graphics caps (НЕ только visual.effects)
        graphics_strict_intersection = mod_caps_set & graphics_caps_strict
        
        # Gameplay tags from tags_system.json (items-equipment, blocks, gameplay, world-generation, mobs)
        gameplay_tags_keywords = [
            # items-equipment
            'weapons', 'swords', 'bows', 'crossbows', 'guns', 'armor', 'helmets', 'chestplates', 'shields',
            'tools', 'pickaxes', 'axes', 'accessories', 'trinkets', 'backpacks',
            # blocks (БЕЗ lighting-blocks - это гибридные моды с lighting.system capability)
            'building-blocks', 'decorative-blocks', 'furniture',
            # gameplay
            'combat', 'pvp', 'pve', 'boss-fights', 'dungeons', 'quests', 'progression-system',
            # world-generation
            'biomes', 'structures', 'villages', 'dungeons-gen', 'castles', 'cities',
            # mobs
            'hostile-mobs', 'passive-mobs', 'boss-mobs', 'tameable-mobs'
        ]
        
        # Особый случай: render.pipeline может быть и в performance, и в graphics
        if 'render.pipeline' in mod_caps_set:
            # Если есть другие graphics caps → проверяем контекст
            if graphics_strict_intersection - {'render.pipeline'}:
                # Проверяем: это чистая графика или gameplay с визуалом?
                gameplay_intersection = mod_caps_set & gameplay_caps
                mod_tags = set(mod.get('tags', []))
                has_gameplay_tags = any(tag in mod_tags for tag in gameplay_tags_keywords)
                
                # Проверка summary на gameplay keywords
                summary = mod.get('summary', '').lower()
                gameplay_keywords_in_summary = [
                    'mob', 'mobs', 'creature', 'creatures', 'beast', 'beasts', 'monster', 'monsters',
                    'entity', 'entities', 'animal', 'animals', 'boss', 'bosses',
                    'weapon', 'weapons', 'armor', 'armour', 'sword', 'bow', 'shield',
                    'block', 'blocks', 'item', 'items', 'craft', 'crafting',
                    'dungeon', 'dungeons', 'structure', 'structures', 'biome', 'biomes',
                    'adds', 'new mobs', 'new creatures', 'new items', 'new blocks'
                ]
                has_gameplay_summary = any(keyword in summary for keyword in gameplay_keywords_in_summary)
                
                if gameplay_intersection or has_gameplay_tags or has_gameplay_summary:
                    gameplay_mods.append(mod)
                    if gameplay_intersection:
                        reason = 'gameplay caps'
                    elif has_gameplay_tags:
                        reason = f'gameplay tags: {list(mod_tags & set(gameplay_tags_keywords))[:2]}'
                    else:
                        found_keywords = [kw for kw in gameplay_keywords_in_summary if kw in summary]
                        reason = f'gameplay summary: {found_keywords[:2]}'
                    debug_classifications.append(f"❌ {mod_slug} → GAMEPLAY (graphics + {reason})")
                else:
                    graphics_mods.append(mod)
                    debug_classifications.append(f"🎨 {mod_slug} → GRAPHICS (caps: {list(graphics_strict_intersection)[:2]})")
                continue
            # Если есть performance caps → PERFORMANCE (это Sodium)
            elif mod_caps_set & performance_caps:
                performance_mods.append(mod)
                perf_caps = list(mod_caps_set & performance_caps)
                debug_classifications.append(f"⚡ {mod_slug} → PERFORMANCE (caps: {perf_caps[:2] + ['render.pipeline']})")
                continue
            # Только render.pipeline без других caps → GRAPHICS (fallback)
            else:
                graphics_mods.append(mod)
                debug_classifications.append(f"🎨 {mod_slug} → GRAPHICS (caps: ['render.pipeline'])")
                continue
        
        # Другие строгие graphics capabilities (shaders, sky, lighting, particles)
        if graphics_strict_intersection:
            # Проверяем контекст: чистая графика или gameplay с визуалом?
            gameplay_intersection = mod_caps_set & gameplay_caps
            mod_tags = set(mod.get('tags', []))
            has_gameplay_tags = any(tag in mod_tags for tag in gameplay_tags_keywords)
            
            # Проверка summary на gameplay keywords (mobs, creatures, items, blocks, etc.)
            summary = mod.get('summary', '').lower()
            
            # ВАЖНО: Исключаем graphics контекст (shader/lighting/rendering моды)
            graphics_context_keywords = [
                'shader', 'shaders', 'lighting', 'light', 'lights', 'shadow', 'shadows',
                'render', 'rendering', 'smooth lighting', 'dynamic light', 'iris', 'sodium',
                'flywheel', 'smooth shading', 'path block', 'visual effect'
            ]
            has_graphics_context = any(keyword in summary for keyword in graphics_context_keywords)
            
            gameplay_keywords_in_summary = [
                'mob', 'mobs', 'creature', 'creatures', 'beast', 'beasts', 'monster', 'monsters',
                'entity', 'entities', 'animal', 'animals', 'boss', 'bosses',
                'weapon', 'weapons', 'armor', 'armour', 'sword', 'bow', 'shield',
                'craft', 'crafting',
                'dungeon', 'dungeons', 'structure', 'structures', 'biome', 'biomes',
                'adds new', 'new mobs', 'new creatures', 'new items', 'new weapons'
            ]
            has_gameplay_summary = any(keyword in summary for keyword in gameplay_keywords_in_summary)
            
            # Если это graphics контекст (shader/lighting) → GRAPHICS независимо от упоминания blocks
            if has_graphics_context:
                graphics_mods.append(mod)
                debug_classifications.append(f"🎨 {mod_slug} → GRAPHICS (shader/lighting context)")
                continue
            
            if gameplay_intersection or has_gameplay_tags or has_gameplay_summary:
                gameplay_mods.append(mod)
                if gameplay_intersection:
                    reason = 'gameplay caps'
                elif has_gameplay_tags:
                    reason = f'gameplay tags: {list(mod_tags & set(gameplay_tags_keywords))[:2]}'
                else:
                    # Найдём какие ключевые слова нашлись
                    found_keywords = [kw for kw in gameplay_keywords_in_summary if kw in summary]
                    reason = f'gameplay summary: {found_keywords[:2]}'
                debug_classifications.append(f"❌ {mod_slug} → GAMEPLAY (graphics + {reason})")
            else:
                graphics_mods.append(mod)
                debug_classifications.append(f"🎨 {mod_slug} → GRAPHICS (caps: {list(graphics_strict_intersection)[:2]})")
            continue
        
        # 2c. Performance capabilities → PERFORMANCE category (lithium, modernfix)
        perf_intersection = mod_caps_set & performance_caps
        if perf_intersection:
            performance_mods.append(mod)
            debug_classifications.append(f"⚡ {mod_slug} → PERFORMANCE (caps: {list(perf_intersection)[:2]})")
            continue
        
        # 2d. UI capabilities → проверяем контекст
        ui_intersection = mod_caps_set & ui_caps
        if ui_intersection:
            # Проверка: это UI library (рецепты/утилиты) или gameplay UI (HUD/inventory)?
            # UI library должны иметь api.exposed или dependency.library
            has_library_caps = bool(mod_caps_set & library_caps)
            
            if has_library_caps:
                # UI + library caps = UI library (REI, JEI)
                library_mods.append(mod)
                debug_classifications.append(f"✅ {mod_slug} → LIBRARY (UI + library caps)")
                continue
            
            # Обычные UI моды (инвентарь, HUD) → GAMEPLAY
            gameplay_mods.append(mod)
            debug_classifications.append(f"❌ {mod_slug} → GAMEPLAY (ui caps: {list(ui_intersection)[:2]})")
            continue
        
        # 2e. Gameplay capabilities → GAMEPLAY
        gameplay_intersection = mod_caps_set & gameplay_caps
        if gameplay_intersection:
            gameplay_mods.append(mod)
            debug_classifications.append(f"❌ {mod_slug} → GAMEPLAY (caps: {list(gameplay_intersection)[:2]})")
            continue
        
        # FALLBACK: No recognized capabilities → GAMEPLAY
        gameplay_mods.append(mod)
        debug_classifications.append(f"❌ {mod_slug} → GAMEPLAY (no recognized caps)")
    
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
        
        # Graphics category: graphics capabilities (strict)
        if cat_caps & graphics_caps_strict and not graphics_category:
            graphics_category = cat['name']
            print(f"   🔍 Found graphics category by capabilities: '{graphics_category}'")
        
        # Performance category: performance capabilities
        if cat_caps & performance_caps and not performance_category:
            performance_category = cat['name']
            print(f"   🔍 Found performance category by capabilities: '{performance_category}'")
    
    # Размещаем моды в найденные категории
    all_distributions = defaultdict(list)
    
    # Библиотеки
    if library_category and library_mods:
        all_distributions[library_category] = library_mods
        print(f"   📚 Placed {len(library_mods)} libraries into '{library_category}'")
    elif library_mods:
        library_category = 'Libraries & APIs'
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
    if performance_category and performance_mods:
        all_distributions[performance_category] = performance_mods
        print(f"   ⚡ Placed {len(performance_mods)} performance mods into '{performance_category}'")
    elif performance_mods:
        performance_category = 'Performance & Optimization'
        all_distributions[performance_category] = performance_mods
        print(f"   ⚠️  No performance category found, created fallback '{performance_category}'")
    else:
        print(f"   ⚠️  DEBUG: Skipped performance placement (category={performance_category}, mods={len(performance_mods)})")
    
    # Формируем список gameplay категорий (ИСКЛЮЧАЕМ библиотечные, graphics и performance)
    gameplay_categories = []
    for cat in categories:
        # Пропускаем технические категории
        if cat['name'] in [library_category, graphics_category, performance_category]:
            continue
        gameplay_categories.append(cat)
    
    # Распределяем все gameplay моды через AI
    mods = gameplay_mods
    print(f"   🤖 Distributing {len(mods)} gameplay mods via AI...")
    
    # Форматируем категории для промпта
    categories_text = []
    
    for i, cat in enumerate(gameplay_categories, 1):
        categories_text.append(f"{i}. {cat['name']} (target: ~{cat.get('estimated_mods', 0)} mods)")
        categories_text.append(f"   Description: {cat.get('description', '')}")
        req_caps = cat.get('required_capabilities', [])
        if req_caps:
            categories_text.append(f"   Capabilities: {', '.join(req_caps[:5])}")
    
    categories_formatted = "\n".join(categories_text)
    
    # Форматируем моды для промпта (батчами по 20 для избежания timeout)
    batch_size = 20  # Уменьшено с 30 для более быстрых ответов AI
    # all_distributions уже создан выше с библиотеками - НЕ перезаписываем!
    
    for batch_idx in range(0, len(mods), batch_size):
        batch = mods[batch_idx:batch_idx + batch_size]
        
        mods_text = []
        for i, mod in enumerate(batch, 1):  # Локальная нумерация внутри батча (1-30)
            mod_info = [f"{i}. {mod.get('name', mod.get('slug', 'Unknown'))}"]
            
            # Summary
            summary = mod.get('summary', mod.get('description', ''))[:150]
            if summary:
                mod_info.append(f"   Summary: {summary}")
            
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
1. **Mod's PRIMARY functionality** (from summary/description)
   - What does this mod actually DO?
   - What problem does it solve or feature does it add?

2. **Mod's tags** (categorization hints)
   - Tags reveal the mod's type (combat, decoration, tech, etc.)
   - Use tags to confirm what the summary says

3. **Mod's capabilities** (technical features)
   - Capabilities are prefixes like "combat.", "worldgen.", "decoration."
   - Match capability PREFIXES to category themes
   - Example: "combat.melee" mod → Combat-themed category

4. **Category's theme and description**
   - Each category has a THEME and PURPOSE
   - Match mod's functionality to category's theme
   - Don't force mods into unrelated categories

**PATTERN MATCHING EXAMPLES:**

✅ CORRECT:
- "Sword mod with new weapons" + tags:[weapon] + caps:[combat] → "Knightly Armory" (equipment)
- "Combat system overhaul" + caps:[combat.system] → "Combat Arts" (mechanics/skills)
- "Decorative blocks for castles" + tags:[decoration, building] → "Castle Architecture"
- "Shaders for lighting" + tags:[visual, graphics] → "Enchanted Visuals"
- "Biome overhaul" + capabilities:[worldgen.biome] → "Fantasy Realms" / "Medieval Lands"
- "Tech machines & automation" + caps:[tech.machines] → "Courtly Interface" / "Artisan Crafting"
- "REI/JEI recipe viewer" + tags:[utility] + caps:[ui] → DO NOT distribute (already library)

❌ INCORRECT:
- Weapons/armor mod → "Combat Arts" (wrong: that's for skills/mechanics, use "Knightly Armory")
- Tech mod → "Medieval Settlements" (wrong: tech is crafting/automation, not villages)
- Recipe viewer (REI) → Any gameplay category (wrong: it's UI utility, should be library)
- Random mod → First category in list (wrong: lazy matching)

**STRICT RULES:**
- ONLY gameplay mods in this batch (libraries already separated)
- Match by ACTUAL FUNCTIONALITY and THEME
- DO NOT randomly assign mods
- DO NOT put gameplay mods into technical/foundation categories
- Distribute evenly across relevant categories
- If a mod fits multiple categories, choose the PRIMARY purpose
- If truly unsure, choose closest thematic match

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
    for mod in mods + library_mods + graphics_mods + performance_mods:
        mod_id = mod.get('source_id', mod.get('project_id', ''))
        if mod_id not in assigned_mods:
            unassigned_mods.append(mod)
    
    if unassigned_mods:
        print(f"   ⚠️  Found {len(unassigned_mods)} unassigned mods")
        
        # Fallback: создаём категорию General если её нет
        general_category = None
        for cat in categories:
            if 'general' in cat['name'].lower() or 'misc' in cat['name'].lower():
                general_category = cat['name']
                break
        
        if not general_category:
            general_category = 'General'
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
