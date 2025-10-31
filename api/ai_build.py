"""
AI Build Logic
Собирает модпак на основе промпта пользователя
"""

import requests
import json
import re
from typing import List, Dict
from sentence_transformers import SentenceTransformer

# Глобальная модель (загружается один раз)
embedding_model = None


def get_embedding_model():
    """Ленивая загрузка модели embeddings"""
    global embedding_model
    if embedding_model is None:
        print("📥 Loading sentence-transformers model...")
        embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
        print("✅ Model loaded")
    return embedding_model


def build_modpack(
    prompt: str,
    mc_version: str,
    mod_loader: str,
    current_mods: List[str],  # Список project_id модов на доске
    max_mods: int,
    fabric_compat_mode: bool = False,  # Добавлен для совместимости
    deepseek_key: str = None,
    supabase_url: str = None,
    supabase_key: str = None
) -> Dict:
    """
    Собирает модпак используя AI
    
    Args:
        prompt: Запрос пользователя ("собери модпак для PvP")
        mc_version: Версия Minecraft
        mod_loader: Загрузчик (fabric/forge/neoforge)
        current_mods: Моды уже на доске
        max_mods: Максимум модов для добавления
        deepseek_key: API ключ DeepSeek
        supabase_url: URL Supabase
        supabase_key: Ключ Supabase
    
    Returns:
        Dict с выбранными модами и объяснениями
    """
    
    # 1. Генерируем embedding для промпта
    print("🧠 Generating query embedding...")
    model = get_embedding_model()
    query_embedding = model.encode(prompt).tolist()
    
    # 2. Векторный поиск в Supabase
    print("🔍 Searching for candidate mods...")
    
    response = requests.post(
        f'{supabase_url}/rest/v1/rpc/search_mods_semantic',
        headers={
            'apikey': supabase_key,
            'Authorization': f'Bearer {supabase_key}',
            'Content-Type': 'application/json'
        },
        json={
            'query_embedding': query_embedding,
            'match_count': 300  # Увеличиваем для лучшего покрытия
        }
    )
    
    if response.status_code != 200:
        raise Exception(f"Supabase error: {response.status_code} - {response.text}")
    
    candidates = response.json()
    print(f"✅ Found {len(candidates)} candidate mods")
    
    # Дебаг: показываем первые 10 кандидатов
    if candidates:
        print("🔍 Top 10 semantic search results:")
        for i, mod in enumerate(candidates[:10], 1):
            print(f"   {i}. {mod.get('name')} ({mod.get('slug')}) - {mod.get('loaders', [])}")
    
    # 3. Умная фильтрация с учётом Fabric Compat Mode
    # Fabric Compat Mode может быть включён пользователем
    has_fabric_compat = fabric_compat_mode
    
    if has_fabric_compat:
        print("🔧 Fabric Compat Mode: ENABLED (user toggled)")
        print("   Accepting both fabric AND neoforge/forge mods")
    
    filtered_candidates = []
    for mod in candidates:
        mod_versions = mod.get('mc_versions', [])
        mod_loaders = mod.get('loaders', [])
        
        version_ok = mc_version in mod_versions if mod_versions else True
        
        # Логика фильтрации loader
        if has_fabric_compat:
            # FabricFix активен - принимаем и fabric и neoforge/forge
            loader_ok = any(loader in mod_loaders for loader in ['fabric', 'neoforge', 'forge']) if mod_loaders else True
            
            # Помечаем приоритет для NeoForge версий
            if version_ok and loader_ok:
                mod['_prefers_neoforge'] = 'neoforge' in mod_loaders or 'forge' in mod_loaders
        else:
            # Обычный режим - только соответствующий loader
            loader_ok = mod_loader in mod_loaders if mod_loaders else True
        
        if version_ok and loader_ok:
            filtered_candidates.append(mod)
    
    # Сортируем: сначала NeoForge моды, потом Fabric
    if has_fabric_compat:
        filtered_candidates.sort(key=lambda m: (not m.get('_prefers_neoforge', False), -m.get('downloads', 0)))
    
    print(f"✅ After filtering: {len(filtered_candidates)} compatible mods")
    
    # Логируем, если мало кандидатов
    if len(filtered_candidates) < 20:
        print(f"⚠️  WARNING: Only {len(filtered_candidates)} compatible mods found!")
        print(f"   Filters: mc_version={mc_version}, mod_loader={mod_loader}, has_fabric_compat={has_fabric_compat}")
        if candidates:
            sample = candidates[0]
            print(f"   Sample mod versions: {sample.get('mc_versions', [])}")
            print(f"   Sample mod loaders: {sample.get('loaders', [])}")
    
    # 4. Формируем промпт для DeepSeek
    current_mods_text = ""
    if current_mods:
        current_mods_text = f"CURRENT MODS ON BOARD ({len(current_mods)} mods):\n"
        # current_mods - это список project_id
        for mod_id in current_mods[:50]:  # Максимум 50 для контекста
            current_mods_text += f"- {mod_id}\n"
        current_mods_text += "\n"
    
    candidates_text = "CANDIDATE MODS (choose from these):\n"
    for i, mod in enumerate(filtered_candidates[:100], 1):
        candidates_text += f"{i}. [{mod['slug']}] {mod['name']}\n"
        candidates_text += f"   {mod.get('description', '')[:150]}\n"
        candidates_text += f"   Categories: {', '.join(mod.get('categories', []))}\n"
        candidates_text += f"   Downloads: {mod.get('downloads', 0):,}\n\n"
    
    prompt_text = f"""You are an expert Minecraft modpack builder. Your task is to PRECISELY follow user's request.

{current_mods_text}

USER REQUEST: "{prompt}"
Version: {mc_version}, Loader: {mod_loader}
Max mods to add: {max_mods}

{candidates_text}

CRITICAL RULES:
1. If user asks for SPECIFIC mods by name (e.g., "add sodium and iris", "добавь содиум и ирис"):
   - Find EXACT matches in candidates list by name
   - ONLY select those specific mods
   - DO NOT add any extra mods
   - Common mod names: Sodium=sodium, Iris=iris, JEI=jei, Jade=jade, REI=rei

2. If user asks for a NUMBER of mods (e.g., "add 2 mods", "add 5 performance mods"):
   - Select EXACTLY that number
   - DO NOT exceed the requested count

3. If user asks for a CATEGORY (e.g., "optimization mods", "building mods"):
   - Select up to {max_mods} mods from that category
   - Focus on the most popular and stable

4. General guidelines:
   - Check current mods to avoid duplicates
   - Don't add dependencies unless explicitly needed
   - Prefer exact name matches over similar mods

RETURN ONLY VALID JSON:
{{
  "mods": [
    {{
      "slug": "mod-slug-from-candidates",
      "reason": "Brief reason (e.g., 'Requested by user', 'Popular optimization mod')"
    }}
  ],
  "explanation": "Short summary of what was added and why"
}}

EXAMPLES:
- Request: "add sodium" → Select ONLY sodium mod
- Request: "add 3 optimization mods" → Select EXACTLY 3 optimization mods
- Request: "building mods" → Select various building-related mods (up to max_mods)
"""

    print("📤 Sending to DeepSeek for final selection...")
    
    # 5. Отправляем в DeepSeek
    response = requests.post(
        'https://api.deepseek.com/v1/chat/completions',
        headers={
            'Authorization': f'Bearer {deepseek_key}',
            'Content-Type': 'application/json'
        },
        json={
            'model': 'deepseek-chat',
            'messages': [{
                'role': 'user',
                'content': prompt_text
            }],
            'temperature': 0.2,  # Низкая температура для точности
            'max_tokens': 4000
        },
        timeout=60
    )
    
    if response.status_code != 200:
        raise Exception(f"DeepSeek API error: {response.status_code} - {response.text}")
    
    result = response.json()
    content = result['choices'][0]['message']['content']
    
    print("📥 Received response from DeepSeek")
    
    # 6. Парсим JSON
    json_match = re.search(r'\{.*\}', content, re.DOTALL)
    if not json_match:
        raise Exception("Could not parse JSON from AI response")
    
    selection = json.loads(json_match.group())
    
    # 7. Обогащаем данные из кандидатов
    selected_mods = []
    candidates_dict = {m['slug']: m for m in filtered_candidates}
    
    for mod_selection in selection['mods']:
        slug = mod_selection['slug']
        if slug in candidates_dict:
            mod_data = candidates_dict[slug].copy()
            mod_data['ai_reason'] = mod_selection['reason']
            selected_mods.append(mod_data)
    
    print(f"✅ Selected {len(selected_mods)} mods")
    
    return {
        'mods': selected_mods,
        'explanation': selection.get('explanation', ''),
        'prompt': prompt,
        'mc_version': mc_version,
        'mod_loader': mod_loader
    }