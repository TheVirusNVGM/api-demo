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
    supabase_url: str, 
    supabase_key: str, 
    mod_loader: str,
    fabric_compat_mode: bool = False
) -> Dict:
    """
    Извлекает паттерны capabilities И baseline моды из reference модпаков
    
    Args:
        reference_modpacks: Список reference модпаков с архитектурами
        supabase_url: URL Supabase
        supabase_key: Ключ Supabase
        mod_loader: Целевой loader (для фильтрации baseline модов)
        fabric_compat_mode: Режим Fabric Compatibility (разрешает fabric моды на forge/neoforge)
    
    Returns:
        Dict с агрегированными паттернами и baseline модами
    """
    
    print(f"\n📊 [Architecture Planner] Extracting capability patterns...")
    
    from collections import Counter
    
    all_capabilities = []
    capability_to_providers = {}
    
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
    
    capability_frequency = Counter(all_capabilities)
    top_capabilities = capability_frequency.most_common(20)
    
    print(f"   Top capabilities across {len(reference_modpacks)} reference modpacks:")
    for cap, count in top_capabilities[:10]:
        print(f"   • {cap}: {count}/{len(reference_modpacks)} modpacks")
    
    # Извлекаем baseline моды из providers
    print(f"\n📌 [Architecture Planner] Extracting baseline mods...")
    all_mod_ids = set()
    for modpack in reference_modpacks:
        providers = modpack['architecture'].get('providers', {})
        for mod_list in providers.values():
            all_mod_ids.update(mod_list)
    
    print(f"   📦 Collected {len(all_mod_ids)} unique mod IDs from providers")
    if all_mod_ids:
        print(f"   🔍 Sample IDs: {list(all_mod_ids)[:5]}")
    
    # Фетчим моды из БД чтобы проверить тег baseline-mod
    baseline_mods = []
    if all_mod_ids:
        try:
            mod_ids_list = list(all_mod_ids)[:200]  # Увеличим лимит до 200
            
            # Используем прямой POST-запрос с фильтром source_id.in.()
            response = requests.get(
                f'{supabase_url}/rest/v1/mods',
                headers={
                    'apikey': supabase_key,
                    'Authorization': f'Bearer {supabase_key}',
                    'Content-Type': 'application/json'
                },
                params={
                    'source_id': f'in.({','.join(mod_ids_list)})',
                    'select': 'source_id,name,capabilities,tags,loaders'
                },
                timeout=15
            )
            
            print(f"   📡 DB Response: {response.status_code}")
            
            if response.status_code == 200:
                mods_data = response.json()
                print(f"   📊 Fetched {len(mods_data)} mods from DB")
                
                baseline_count = 0
                loader_filtered_count = 0
                fabric_api_filtered = 0
                
                for mod in mods_data:
                    tags = mod.get('tags', [])
                    if 'baseline-mod' in tags:
                        baseline_count += 1
                        
                        # HARD EXCLUSION: Моды с тегом "fabric-api" НИКОГДА не добавляем в forge/neoforge
                        if 'fabric-api' in tags and mod_loader in ['forge', 'neoforge']:
                            fabric_api_filtered += 1
                            continue
                        
                        # Проверяем совместимость loader'а
                        mod_loaders = mod.get('loaders', [])
                        
                        # Если fabric_compat_mode включен, разрешаем fabric моды на forge/neoforge
                        is_compatible = mod_loader in mod_loaders
                        if not is_compatible and fabric_compat_mode:
                            # Разрешаем fabric моды, кроме уже отфильтрованных fabric-api
                            is_compatible = 'fabric' in mod_loaders
                        
                        if is_compatible:
                            baseline_mods.append({
                                'source_id': mod.get('source_id'),
                                'name': mod.get('name'),
                                'capabilities': mod.get('capabilities', []),
                                'tags': tags,
                                'loaders': mod_loaders
                            })
                        else:
                            loader_filtered_count += 1
                
                print(f"   🏷️  Mods with baseline-mod tag: {baseline_count}/{len(mods_data)}")
                if fabric_api_filtered > 0:
                    print(f"   🚫 Excluded {fabric_api_filtered} fabric-api mods (hard exclusion for {mod_loader})")
                if loader_filtered_count > 0:
                    print(f"   ⛔ Filtered out {loader_filtered_count} mods (incompatible with {mod_loader})")
            else:
                print(f"   ❌ DB query failed: {response.text[:200]}")
        except Exception as e:
            print(f"   ⚠️  Failed to fetch baseline mods: {e}")
            import traceback
            traceback.print_exc()
    
    print(f"   ✅ Found {len(baseline_mods)} baseline mods from reference modpacks")
    if baseline_mods:
        for mod in baseline_mods[:10]:
            print(f"      • {mod['name']}")
        if len(baseline_mods) > 10:
            print(f"      ... and {len(baseline_mods) - 10} more")
    
    return {
        'top_capabilities': [cap for cap, _ in top_capabilities],
        'capability_frequency': dict(capability_frequency),
        'capability_providers': capability_to_providers,
        'baseline_mods': baseline_mods,
        'total_reference_modpacks': len(reference_modpacks)
    }


def plan_architecture(
    user_prompt: str,
    reference_modpacks: List[Dict],
    capability_patterns: Dict,
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
    
    reference_context = []
    reference_context.append(f"REFERENCE MODPACKS ({len(reference_modpacks)} similar):")
    
    for i, modpack in enumerate(reference_modpacks[:3], 1):
        arch = modpack['architecture']
        caps = arch.get('capabilities', [])[:10]
        providers = arch.get('providers', {})
        
        reference_context.append(f"{i}. {modpack['title']}")
        reference_context.append(f"   Capabilities: {', '.join(caps)}")
        
        for cap in caps[:3]:
            mods = providers.get(cap, [])[:2]
            if mods:
                reference_context.append(f"   - {cap}: {', '.join(mods)}")
    
    top_caps = capability_patterns['top_capabilities'][:20]
    reference_context.append(f"\nCOMMON CAPABILITIES: {', '.join(top_caps)}")
    
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

6. **Category naming:**
   - BE CREATIVE with gameplay category names (e.g., "Medieval Combat", "Castle Architecture", "Mystical Creatures")
   - Use DESCRIPTIVE names for technical categories:
     * Libraries/APIs/Compatibility → "Libraries & APIs" or "Core Libraries" (NOT "Castle Foundations", "Core Systems")
     * Performance/Optimization → "Performance & Optimization" (NOT "Engine Tuning", "Speed Enhancements")
     * Graphics/Shaders → "Graphics & Shaders" or "Visual Enhancements" (OK to be creative here)
   - Technical categories should be immediately recognizable by their function
   - Gameplay categories can and should have creative, thematic names

RULES:
- Focus on creating MEANINGFUL categories that reflect the modpack's theme
- Don't create categories just to reach a specific count
- Each category must have a clear purpose and identity
- Use user's request to guide category names and themes
- Be creative with gameplay categories, but keep technical categories clear and descriptive"""
    
    # Определяем размер модпака для контекста
    if max_mods <= 15:
        size_category = "Small modpack (1-15 mods)"
        recommended_categories = "2-4 broad categories"
    elif max_mods <= 50:
        size_category = "Medium modpack (15-50 mods)"
        recommended_categories = "5-8 focused categories"
    elif max_mods <= 100:
        size_category = "Large modpack (50-100 mods)"
        recommended_categories = "8-12 specialized categories"
    else:
        size_category = "Huge modpack (100+ mods)"
        recommended_categories = "12-20 granular categories"
    
    user_message = f"""USER REQUEST: "{user_prompt}"

MODPACK SIZE: {max_mods} mods ({size_category})
RECOMMENDED: {recommended_categories}

{reference_text}

Analyze the request and design meaningful categories that reflect the modpack's theme.
Each category should group related mods with clear purpose."""
    
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
                'temperature': 0.3,
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
