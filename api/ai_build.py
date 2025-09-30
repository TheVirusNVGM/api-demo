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
    current_mods: List[Dict],
    max_mods: int,
    deepseek_key: str,
    supabase_url: str,
    supabase_key: str
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
            'match_count': 100  # Берём больше кандидатов
        }
    )
    
    if response.status_code != 200:
        raise Exception(f"Supabase error: {response.status_code} - {response.text}")
    
    candidates = response.json()
    print(f"✅ Found {len(candidates)} candidate mods")
    
    # 3. Фильтруем по версии и лоадеру
    filtered_candidates = []
    for mod in candidates:
        # Проверяем совместимость
        mod_versions = mod.get('mc_versions', [])
        mod_loaders = mod.get('loaders', [])
        
        version_ok = mc_version in mod_versions if mod_versions else True
        loader_ok = mod_loader in mod_loaders if mod_loaders else True
        
        if version_ok and loader_ok:
            filtered_candidates.append(mod)
    
    print(f"✅ After filtering: {len(filtered_candidates)} compatible mods")
    
    # 4. Формируем промпт для DeepSeek
    current_mods_text = ""
    if current_mods:
        current_mods_text = "CURRENT MODS ON BOARD:\n"
        for mod in current_mods[:50]:  # Максимум 50 для контекста
            name = mod.get('name', mod.get('title', 'Unknown'))
            current_mods_text += f"- {name}\n"
        current_mods_text += "\n"
    
    candidates_text = "CANDIDATE MODS (choose from these):\n"
    for i, mod in enumerate(filtered_candidates[:100], 1):
        candidates_text += f"{i}. [{mod['slug']}] {mod['name']}\n"
        candidates_text += f"   {mod.get('description', '')[:150]}\n"
        candidates_text += f"   Categories: {', '.join(mod.get('categories', []))}\n"
        candidates_text += f"   Downloads: {mod.get('downloads', 0):,}\n\n"
    
    prompt_text = f"""You are an expert Minecraft modpack builder. Build a modpack based on user request.

{current_mods_text}

USER REQUEST: "{prompt}"
Version: {mc_version}, Loader: {mod_loader}
Max mods to add: {max_mods}

{candidates_text}

Task:
1. Analyze user request and current mods
2. Select {max_mods} BEST mods from candidates that:
   - Match user's request
   - Don't duplicate existing functionality
   - Are compatible with each other
   - Include necessary dependencies (like Fabric API)
3. For each mod explain WHY you selected it

Return ONLY valid JSON:
{{
  "mods": [
    {{
      "slug": "mod-slug",
      "reason": "Why this mod was selected"
    }}
  ],
  "explanation": "Overall strategy and theme"
}}

Be smart:
- If user has optimization mods, don't add more
- Include dependencies automatically
- Prefer popular, stable mods
- Balance content vs performance
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
            'temperature': 0.4,
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