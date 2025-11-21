"""
Layer 1.5: Architecture Planner
Находит похожие модпаки через semantic search и планирует архитектуру модпака на основе них
"""

import requests
import json
import re
from typing import List, Dict, Optional
from sentence_transformers import SentenceTransformer
from config import DEEPSEEK_API_KEY, DEEPSEEK_INPUT_COST, DEEPSEEK_OUTPUT_COST

# Глобальная модель embeddings (lazy load)
embedding_model = None


def get_embedding_model():
    """Ленивая загрузка модели embeddings"""
    global embedding_model
    if embedding_model is None:
        print("📥 [Architecture Planner] Loading sentence-transformers model...")
        embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
        print("✅ [Architecture Planner] Model loaded")
    return embedding_model


def load_baseline_mods(
    mc_version: str,
    mod_loader: str,
    supabase_url: str,
    supabase_key: str,
    fabric_compat_mode: bool = False
) -> List[Dict]:
    """
    Загружает ВСЕ baseline моды из БД по тегу baseline-mod
    
    Args:
        mc_version: Версия MC (для фильтрации)
        mod_loader: Целевой loader (для фильтрации)
        supabase_url: URL Supabase
        supabase_key: Ключ Supabase
        fabric_compat_mode: Режим Fabric Compatibility
    
    Returns:
        List baseline модов (совместимых с loader/version)
    """
    print(f"\n📌 [Baseline Loader] Loading baseline mods from database...")
    
    baseline_mods = []
    
    try:
        # Загружаем ВСЕ моды с тегом baseline-mod
        # Используем RPC функцию для поиска по тегам (если доступна) или фильтруем на клиенте
        # Попробуем использовать PostgREST оператор для JSONB: tags @> '["baseline-mod"]'::jsonb
        mods_data = []
        response_success = False
        
        try:
            # Загружаем моды и фильтруем на клиенте (RPC функция может не существовать)
            print(f"   🔄 Loading mods for client-side filtering...")
            # Загружаем больше модов чтобы найти baseline (они могут быть не в топе по downloads)
            response = requests.get(
                f'{supabase_url}/rest/v1/mods',
                headers={
                    'apikey': supabase_key,
                    'Authorization': f'Bearer {supabase_key}',
                    'Content-Type': 'application/json',
                    'Prefer': 'count=exact'
                },
                params={
                    'select': 'source_id,name,capabilities,tags,loaders,summary,mc_versions',
                    'limit': 1000,  # Увеличиваем лимит чтобы найти baseline моды
                    'order': 'downloads.desc'  # Сначала популярные, но baseline могут быть и дальше
                },
                timeout=20
            )
            
            # 200 = OK, 206 = Partial Content (когда используется Prefer: count=exact)
            if response.status_code in [200, 206]:
                all_mods = response.json()
                print(f"   📦 Loaded {len(all_mods)} mods from DB")
                # Фильтруем на клиенте: моды с тегом baseline-mod
                mods_data = [
                    mod for mod in all_mods 
                    if mod.get('tags') and isinstance(mod.get('tags'), list) and 'baseline-mod' in mod.get('tags', [])
                ]
                response_success = True
                print(f"   🔍 Found {len(mods_data)} mods with baseline-mod tag after filtering")
            else:
                print(f"   ❌ GET request failed: {response.status_code}")
                print(f"   Response: {response.text[:200]}")
        except Exception as e:
            print(f"   ⚠️  Failed to load baseline mods: {e}")
            import traceback
            traceback.print_exc()
        
        if response_success:
            print(f"   📊 Fetched {len(mods_data)} mods with baseline-mod tag")
            
            loader_filtered_count = 0
            version_filtered_count = 0
            fabric_api_filtered = 0
            ffapi_filtered = 0  # Счётчик для FFAPI модов
            FFAPI_SOURCE_ID = 'Aqlf1Shp'  # Forgified Fabric API
            
            # Загружаем dependencies для всех baseline модов одним запросом
            baseline_source_ids = [mod.get('source_id') for mod in mods_data if mod.get('source_id')]
            mod_dependencies = {}
            
            if baseline_source_ids:
                try:
                    deps_response = requests.get(
                        f'{supabase_url}/rest/v1/mods',
                        headers={
                            'apikey': supabase_key,
                            'Authorization': f'Bearer {supabase_key}',
                        },
                        params={
                            'select': 'source_id,dependencies',
                            'source_id': f'in.({",".join(baseline_source_ids)})'
                        },
                        timeout=10
                    )
                    if deps_response.status_code == 200:
                        for mod_data in deps_response.json():
                            source_id = mod_data.get('source_id')
                            deps = mod_data.get('dependencies', {})
                            if isinstance(deps, str):
                                try:
                                    deps = json.loads(deps)
                                except:
                                    deps = {}
                            mod_dependencies[source_id] = deps
                except Exception as e:
                    print(f"   ⚠️  Failed to load dependencies: {e}")
            
            for mod in mods_data:
                tags = mod.get('tags', [])
                source_id = mod.get('source_id')
                
                # HARD EXCLUSION: Моды с тегом "fabric-api" НИКОГДА не добавляем в forge/neoforge
                if 'fabric-api' in tags and mod_loader in ['forge', 'neoforge']:
                    fabric_api_filtered += 1
                    continue
                
                # ФИЛЬТРАЦИЯ FFAPI: Если fabric_compat_mode=False, пропускаем моды с FFAPI зависимостью
                if not fabric_compat_mode and source_id in mod_dependencies:
                    deps = mod_dependencies[source_id]
                    if isinstance(deps, dict) and FFAPI_SOURCE_ID in deps:
                        dep_info = deps[FFAPI_SOURCE_ID]
                        if dep_info.get('type') == 'required':
                            ffapi_filtered += 1
                            continue
                
                # Проверяем совместимость loader'а
                mod_loaders = mod.get('loaders', [])
                is_compatible = mod_loader in mod_loaders
                
                if not is_compatible and fabric_compat_mode:
                    # Разрешаем fabric моды, кроме уже отфильтрованных fabric-api
                    is_compatible = 'fabric' in mod_loaders
                
                if not is_compatible:
                    loader_filtered_count += 1
                    continue
                
                # Проверяем совместимость версии (если указана)
                mod_versions = mod.get('mc_versions', [])
                if mod_versions and mc_version not in mod_versions:
                    # Проверяем совместимость по мажорной версии (1.21.1 совместима с 1.21.x)
                    major_version = '.'.join(mc_version.split('.')[:2])  # 1.21
                    version_ok = any(major_version in v for v in mod_versions)
                    if not version_ok:
                        version_filtered_count += 1
                        continue
                
                baseline_mods.append({
                    'source_id': mod.get('source_id'),
                    'name': mod.get('name'),
                    'capabilities': mod.get('capabilities', []),
                    'tags': tags,
                    'loaders': mod_loaders,
                    'summary': mod.get('summary', ''),
                    'mc_versions': mod.get('mc_versions', [])
                })
            
            if fabric_api_filtered > 0:
                print(f"   🚫 Excluded {fabric_api_filtered} fabric-api mods (hard exclusion for {mod_loader})")
            if ffapi_filtered > 0:
                print(f"   🚫 Excluded {ffapi_filtered} mods requiring FFAPI (fabric compat mode disabled)")
            if loader_filtered_count > 0:
                print(f"   ⛔ Filtered out {loader_filtered_count} mods (incompatible with {mod_loader})")
            if version_filtered_count > 0:
                print(f"   ⛔ Filtered out {version_filtered_count} mods (incompatible with MC {mc_version})")
        else:
            print(f"   ❌ DB query failed: {response.text[:200]}")
    except Exception as e:
        print(f"   ⚠️  Failed to load baseline mods: {e}")
        import traceback
        traceback.print_exc()
    
    print(f"   ✅ Loaded {len(baseline_mods)} compatible baseline mods")
    if baseline_mods:
        for mod in baseline_mods[:10]:
            print(f"      • {mod['name']}")
        if len(baseline_mods) > 10:
            print(f"      ... and {len(baseline_mods) - 10} more")
    
    return baseline_mods


def find_reference_modpacks(
    user_prompt: str,
    mc_version: str,
    mod_loader: str,
    supabase_url: str,
    supabase_key: str,
    top_n: int = 5
) -> List[Dict]:
    """
    Находит похожие модпаки через semantic search по embedding
    
    Args:
        user_prompt: Запрос пользователя
        mc_version: Версия MC (для контекста, но не фильтруем строго)
        mod_loader: Лоадер (для контекста)
        supabase_url: URL Supabase
        supabase_key: Ключ Supabase
        top_n: Количество reference модпаков
    
    Returns:
        List reference модпаков с их архитектурами
    """
    
    print(f"🔍 [Architecture Planner] Searching for reference modpacks...")
    print(f"   Query: \"{user_prompt[:50]}...\"")
    
    model = get_embedding_model()
    query_embedding = model.encode(user_prompt, show_progress_bar=False).tolist()
    
    try:
        response = requests.post(
            f'{supabase_url}/rest/v1/rpc/search_modpacks_semantic',
            headers={
                'apikey': supabase_key,
                'Authorization': f'Bearer {supabase_key}',
                'Content-Type': 'application/json'
            },
            json={
                'query_embedding': query_embedding,
                'match_count': top_n * 2
            },
            timeout=30
        )
        
        if response.status_code != 200:
            print(f"   ⚠️  Vector search failed: {response.status_code}")
            print(f"   Response: {response.text}")
            return []
        
        modpacks = response.json()
        
    except Exception as e:
        print(f"   ⚠️  Search error: {e}")
        return []
    
    valid_modpacks = []
    
    for modpack in modpacks:
        architecture = modpack.get('architecture')
        if not architecture:
            continue
        
        capabilities = architecture.get('capabilities', [])
        if not capabilities or len(capabilities) < 3:
            continue
        
        providers = architecture.get('providers', {})
        if not providers or len(providers) < 3:
            continue
        
        distance = modpack.get('distance', 0)
        
        valid_modpacks.append({
            'slug': modpack.get('slug'),
            'title': modpack.get('title'),
            'summary': modpack.get('summary', ''),
            'mc_versions': modpack.get('mc_versions', []),
            'loaders': modpack.get('loaders', []),
            'architecture': architecture,
            'distance': distance,
            '_similarity_score': 1.0 / (1.0 + distance)
        })
        
        if len(valid_modpacks) >= top_n:
            break
    
    print(f"   → Found {len(valid_modpacks)} reference modpacks with valid architectures")
    
    for i, modpack in enumerate(valid_modpacks, 1):
        arch = modpack['architecture']
        cap_count = len(arch.get('capabilities', []))
        provider_count = len(arch.get('providers', {}))
        similarity = modpack['_similarity_score']
        
        print(f"   {i}. {modpack['title']} (similarity: {similarity:.3f})")
        print(f"      → {cap_count} capabilities, {provider_count} provider groups")
        print(f"      → Versions: {', '.join(modpack['mc_versions'][:3])}...")
    
    return valid_modpacks


def extract_capability_patterns(
    reference_modpacks: List[Dict],
    baseline_mods: List[Dict]
) -> Dict:
    """
    Извлекает паттерны capabilities из reference модпаков
    И анализирует: какие baseline моды там есть и как они распределены по категориям
    
    Args:
        reference_modpacks: Список reference модпаков с архитектурами
        baseline_mods: Список baseline модов (загруженных из БД)
    
    Returns:
        Dict с агрегированными паттернами и анализом распределения baseline модов
    """
    
    print(f"\n📊 [Architecture Planner] Extracting capability patterns...")
    
    from collections import Counter, defaultdict
    
    all_capabilities = []
    capability_to_providers = {}
    
    # Создаём set source_id baseline модов для быстрого поиска
    baseline_source_ids = {mod['source_id'] for mod in baseline_mods}
    
    # Анализируем распределение baseline модов по категориям в reference modpacks
    baseline_distribution = defaultdict(list)  # capability -> список модпаков где baseline моды с этой capability
    
    for modpack in reference_modpacks:
        architecture = modpack['architecture']
        capabilities = architecture.get('capabilities', [])
        providers = architecture.get('providers', {})
        
        all_capabilities.extend(capabilities)
        
        for cap in capabilities:
            if cap not in capability_to_providers:
                capability_to_providers[cap] = []
            
            cap_providers = providers.get(cap, [])
            capability_to_providers[cap].extend(cap_providers)
            
            # Проверяем: есть ли baseline моды с этой capability в этом модпаке?
            baseline_in_cap = [mod_id for mod_id in cap_providers if mod_id in baseline_source_ids]
            if baseline_in_cap:
                baseline_distribution[cap].append({
                    'modpack': modpack.get('title', 'Unknown'),
                    'baseline_mods': baseline_in_cap
                })
    
    capability_frequency = Counter(all_capabilities)
    top_capabilities = capability_frequency.most_common(20)
    
    print(f"   Top capabilities across {len(reference_modpacks)} reference modpacks:")
    for cap, count in top_capabilities[:10]:
        print(f"   • {cap}: {count}/{len(reference_modpacks)} modpacks")
    
    # Анализируем распределение baseline модов
    print(f"\n🔍 [Architecture Planner] Analyzing baseline mod distribution in reference modpacks...")
    baseline_capabilities = defaultdict(int)
    
    for mod in baseline_mods:
        for cap in mod.get('capabilities', []):
            baseline_capabilities[cap] += 1
    
    top_baseline_caps = sorted(baseline_capabilities.items(), key=lambda x: -x[1])[:10]
    if top_baseline_caps:
        print(f"   Top capabilities in baseline mods:")
        for cap, count in top_baseline_caps:
            print(f"   • {cap}: {count} baseline mods")
    
    # Анализируем: в каких категориях baseline моды чаще всего встречаются в reference modpacks
    baseline_category_patterns = {}
    for cap, modpacks_info in baseline_distribution.items():
        if len(modpacks_info) >= 2:  # Baseline моды с этой capability встречаются в 2+ модпаках
            baseline_category_patterns[cap] = {
                'frequency': len(modpacks_info),
                'modpacks': modpacks_info
            }
    
    if baseline_category_patterns:
        print(f"   📊 Baseline mods frequently appear in these capabilities:")
        for cap, info in sorted(baseline_category_patterns.items(), key=lambda x: -x[1]['frequency'])[:5]:
            print(f"   • {cap}: appears in {info['frequency']} reference modpacks")
    
    return {
        'top_capabilities': [cap for cap, _ in top_capabilities],
        'capability_frequency': dict(capability_frequency),
        'capability_providers': capability_to_providers,
        'baseline_capabilities': dict(baseline_capabilities),
        'baseline_distribution': dict(baseline_distribution),
        'baseline_category_patterns': baseline_category_patterns,
        'total_reference_modpacks': len(reference_modpacks)
    }


def calculate_dynamic_category_count(
    user_prompt: str,
    capability_patterns: Dict,
    max_mods: int,
    reference_modpacks: List[Dict]
) -> int:
    """
    Вычисляет динамическое количество категорий на основе:
    - Разнообразия capabilities
    - Сложности промпта (количество тем)
    - Количества модов
    - Разнообразия reference модпаков
    """
    import math
    import re
    
    # Базовое количество на основе размера модпака (логарифмическая шкала)
    if max_mods <= 15:
        base_categories = 3
    elif max_mods <= 50:
        base_categories = 5
    elif max_mods <= 100:
        base_categories = 8
    else:
        base_categories = 12
    
    # Разнообразие capabilities (уникальные префиксы)
    unique_prefixes = set()
    for cap in capability_patterns.get('top_capabilities', [])[:30]:
        prefix = cap.split('.')[0] if '.' in cap else cap
        unique_prefixes.add(prefix)
    capability_diversity = len(unique_prefixes) / 3  # Каждые 3 уникальных префикса = +1 категория
    
    # Сложность промпта (количество ключевых слов-тем)
    theme_keywords = [
        'medieval', 'fantasy', 'tech', 'magic', 'combat', 'building', 'exploration',
        'automation', 'adventure', 'survival', 'creative', 'pvp', 'rpg', 'quest',
        'dimension', 'biome', 'structure', 'village', 'mob', 'creature', 'weapon',
        'armor', 'shader', 'performance', 'optimization', 'decoration', 'farming'
    ]
    prompt_lower = user_prompt.lower()
    themes_found = sum(1 for keyword in theme_keywords if keyword in prompt_lower)
    prompt_complexity = themes_found / 2  # Каждые 2 темы = +1 категория
    
    # Разнообразие reference модпаков (разные pack_archetype)
    unique_archetypes = set()
    for modpack in reference_modpacks:
        arch = modpack.get('architecture', {})
        meta = arch.get('meta', {})
        archetype = meta.get('pack_archetype', '')
        if archetype:
            unique_archetypes.add(archetype)
    reference_diversity = len(unique_archetypes) / 2
    
    # Итоговое количество категорий
    target_categories = int(base_categories + capability_diversity + prompt_complexity + reference_diversity)
    
    # Ограничения: минимум 3, максимум 20
    target_categories = max(3, min(20, target_categories))
    
    print(f"   📊 Dynamic category calculation:")
    print(f"      Base: {base_categories}, Capability diversity: {capability_diversity:.1f}, Prompt complexity: {prompt_complexity:.1f}, Reference diversity: {reference_diversity:.1f}")
    print(f"      → Target: {target_categories} categories")
    
    return target_categories


def plan_architecture(
    user_prompt: str,
    reference_modpacks: List[Dict],
    capability_patterns: Dict,
    baseline_mods: List[Dict],
    max_mods: int,
    deepseek_key: str = DEEPSEEK_API_KEY
) -> Optional[Dict]:
    """
    Планирует архитектуру модпака на основе reference модпаков
    
    Args:
        user_prompt: Запрос пользователя
        reference_modpacks: Похожие модпаки
        capability_patterns: Паттерны capabilities
        max_mods: Максимум модов
        deepseek_key: API ключ
    
    Returns:
        Dict с запланированной архитектурой
    """
    
    print(f"\n📝 [Architecture Planner] Planning modpack architecture...")
    
    # Вычисляем динамическое количество категорий
    target_category_count = calculate_dynamic_category_count(
        user_prompt=user_prompt,
        capability_patterns=capability_patterns,
        max_mods=max_mods,
        reference_modpacks=reference_modpacks
    )
    
    reference_context = []
    reference_context.append(f"REFERENCE MODPACKS ({len(reference_modpacks)} similar):")
    
    for i, modpack in enumerate(reference_modpacks[:3], 1):
        arch = modpack.get('architecture', {})
        caps = arch.get('capabilities', [])[:10]
        providers = arch.get('providers', {})
        meta = arch.get('meta', {})
        
        reference_context.append(f"{i}. {modpack.get('title', 'Unknown')}")
        if meta.get('pack_archetype'):
            reference_context.append(f"   Archetype: {meta['pack_archetype']}")
        reference_context.append(f"   Capabilities: {', '.join(caps)}")
        
        for cap in caps[:3]:
            mods = providers.get(cap, [])[:2]
            if mods:
                reference_context.append(f"   - {cap}: {', '.join(mods)}")
    
    top_caps = capability_patterns.get('top_capabilities', [])[:20]
    reference_context.append(f"\nCOMMON CAPABILITIES: {', '.join(top_caps)}")
    
    # Добавляем информацию о baseline модах
    if baseline_mods:
        from collections import defaultdict
        
        baseline_caps = capability_patterns.get('baseline_capabilities', {})
        top_baseline_caps = sorted(baseline_caps.items(), key=lambda x: -x[1])[:10]
        
        reference_context.append(f"\nBASELINE MODS ({len(baseline_mods)} mods):")
        reference_context.append("   These are essential mods that will be included in the modpack.")
        reference_context.append("   Categories should accommodate these baseline mods:")
        
        baseline_by_cap = defaultdict(list)
        for mod in baseline_mods:
            for cap in mod.get('capabilities', []):
                baseline_by_cap[cap].append(mod['name'])
        
        for cap, count in top_baseline_caps[:5]:
            mod_names = baseline_by_cap.get(cap, [])[:3]
            if mod_names:
                reference_context.append(f"   • {cap}: {', '.join(mod_names)}")
        
        # Анализируем паттерны распределения baseline модов в reference modpacks
        baseline_patterns = capability_patterns.get('baseline_category_patterns', {})
        if baseline_patterns:
            reference_context.append(f"\n   Baseline mods frequently appear in these capabilities in reference modpacks:")
            for cap, info in sorted(baseline_patterns.items(), key=lambda x: -x[1]['frequency'])[:3]:
                reference_context.append(f"   • {cap}: appears in {info['frequency']} reference modpacks")
    
    reference_text = "\n".join(reference_context)
    
    system_prompt = """You are an expert modpack architect. Plan a modpack architecture based on user's request and reference modpacks.

Your job:
1. Analyze the user's request and identify DISTINCT themes/aspects
2. Look at reference modpacks to understand common capability patterns
3. Design MEANINGFUL categories that group related functionality
4. Each category should have a clear purpose and target specific capabilities

Return ONLY valid JSON:
{
  "categories": [
    {
      "name": "Category Name",
      "description": "What this category provides",
      "required_capabilities": ["capability.name", ...],
      "preferred_capabilities": ["capability.name", ...],
      "target_mods": 10
    }
  ]
}

CATEGORY DESIGN PRINCIPLES:

1. **Scale-appropriate categorization:**
   - Small modpacks (1-15 mods): 2-4 broad categories (e.g., "Core", "Content", "Visuals")
   - Medium modpacks (15-50 mods): 5-8 focused categories (e.g., "Combat", "Building", "World Gen", "Performance")
   - Large modpacks (50-100 mods): 8-12 specialized categories (e.g., "Medieval Combat", "Castle Building", "Village Life", "Fantasy Creatures")
   - Huge modpacks (100+ mods): 12-20 granular categories (split by sub-themes)

2. **Category sizing:**
   - Ideal: 5-10 mods per category (easy to browse)
   - Acceptable: 3-15 mods per category
   - Avoid: Single-mod categories (merge into related category)
   - Avoid: 20+ mod categories (split into sub-categories)

3. **Meaningful grouping:**
   - Categories should reflect USER'S REQUEST themes (not just technical grouping)
   - Each category should have a clear identity and purpose
   - Related capabilities should be in the same category
   - Don't force categories just to reach a number - quality over quantity

4. **Capability matching:**
   - Use capabilities from reference modpacks when relevant
   - required_capabilities: MUST-HAVE for this category (core functionality)
   - preferred_capabilities: NICE-TO-HAVE (related/supporting functionality)
   - Use broad prefixes (e.g., "combat" matches "combat.melee", "combat.ranged", "combat.system")

5. **Target mod distribution:**
   - Sum of target_mods should be ~75-85% of max_mods (leave room for dependencies)
   - Distribute mods proportionally to category importance in user's request
   - Core/essential categories should have higher targets

6. **Category naming - BE CREATIVE AND THEMATIC:**
   - Gameplay categories MUST have evocative, thematic names that match the modpack's atmosphere
   - Examples for medieval/fantasy packs:
     * "Knight's Arsenal" instead of "Combat Mods"
     * "Castle Keep" instead of "Building Blocks"
     * "Mystical Realms" instead of "Fantasy Biomes"
     * "Royal Archives" instead of "Libraries"
     * "Enchanted Visuals" instead of "Graphics"
   - Examples for tech packs:
     * "Engineering Hub" instead of "Tech Mods"
     * "Power Grid" instead of "Energy Systems"
     * "Automation Core" instead of "Machines"
   - Examples for adventure packs:
     * "Explorer's Toolkit" instead of "Adventure Mods"
     * "Shadow Realms" instead of "Dimensions"
     * "Forge of Legends" instead of "Crafting"
   - Technical categories can be creative but should hint at function:
     * Libraries → "Royal Archives", "Core Foundations", "Essential Libraries"
     * Performance → "Performance & Optimization" (keep clear)
     * Graphics → "Enchanted Visuals", "Atmospheric Lighting", "Visual Enhancements"
   - AVOID generic names like "Core Systems", "Gameplay Mods", "Content"
   - Each name should evoke the modpack's unique identity and theme

CRITICAL RULES:
- Focus on creating MEANINGFUL categories that reflect the modpack's theme
- Don't create categories just to reach a specific count
- Each category must have a clear purpose and identity
- Use user's request to guide category names and themes
- BE CREATIVE with ALL category names - use the examples above as inspiration
- DO NOT use generic names like "Combat Mods", "Building Blocks", "Core Systems"
- Every category name should be evocative and thematic, matching the modpack's atmosphere
- For technical categories (libraries, performance) - still be creative but hint at function
- Examples: "Royal Archives" (libraries), "Performance & Optimization" (performance), "Enchanted Visuals" (graphics)"""
    
    # Определяем размер модпака для контекста
    if max_mods <= 15:
        size_category = "Small modpack (1-15 mods)"
    elif max_mods <= 50:
        size_category = "Medium modpack (15-50 mods)"
    elif max_mods <= 100:
        size_category = "Large modpack (50-100 mods)"
    else:
        size_category = "Huge modpack (100+ mods)"
    
    user_message = f"""USER REQUEST: "{user_prompt}"

MODPACK SIZE: {max_mods} mods ({size_category})
TARGET CATEGORIES: {target_category_count} categories (calculated dynamically based on complexity)

{reference_text}

Analyze the request and design {target_category_count} meaningful, CREATIVE categories that reflect the modpack's theme.
Each category should have an evocative, thematic name that matches the modpack's atmosphere.
Use the examples above for inspiration - be creative with names while keeping them meaningful."""
    
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
                'temperature': 0.7,  # Увеличено для креативности в названиях категорий
                'max_tokens': 2000
            },
            timeout=60  # Увеличен до 60 сек из-за длинного системного промпта
        )
        
        if response.status_code != 200:
            print(f"   ⚠️  AI planning failed: {response.status_code}")
            return None
        
        result = response.json()
        content = result['choices'][0]['message']['content'].strip()
        
        usage = result.get('usage', {})
        prompt_tokens = usage.get('prompt_tokens', 0)
        completion_tokens = usage.get('completion_tokens', 0)
        total_tokens = usage.get('total_tokens', 0)
        cost = (prompt_tokens * DEEPSEEK_INPUT_COST / 1_000_000) + (completion_tokens * DEEPSEEK_OUTPUT_COST / 1_000_000)
        
        print(f"📥 [Architecture Planner] Received plan")
        print(f"   📊 Tokens: {total_tokens:,} (prompt: {prompt_tokens:,}, completion: {completion_tokens:,})")
        print(f"   💵 Cost: ${cost:.6f}")
        
        content = content.replace('```json', '').replace('```', '').strip()
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        
        if not json_match:
            print(f"   ⚠️  Could not parse JSON")
            return None
        
        architecture = json.loads(json_match.group())
        
        if 'categories' not in architecture or not architecture['categories']:
            print(f"   ⚠️  No categories in plan")
            return None
        
        print(f"✅ [Architecture Planner] Planned {len(architecture['categories'])} categories:")
        total_target_mods = 0
        for cat in architecture['categories']:
            target = cat.get('target_mods', 0)
            total_target_mods += target
            print(f"   📚 {cat['name']}: {target} mods (target)")
            req_caps = cat.get('required_capabilities', [])
            if req_caps:
                print(f"      Required: {', '.join(req_caps[:5])}")
        print(f"   🎯 Total target: {total_target_mods} mods")
        
        architecture['_tokens'] = {
            'prompt_tokens': prompt_tokens,
            'completion_tokens': completion_tokens,
            'total_tokens': total_tokens,
            'cost_usd': cost
        }
        
        return architecture
        
    except Exception as e:
        print(f"   ❌ [Architecture Planner] Error: {e}")
        return None
