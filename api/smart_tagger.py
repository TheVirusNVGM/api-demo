"""
Smart Mod Tagger - определяет наши кастомные теги для мода
Использует AI для анализа описания мода и подбора подходящих тегов
"""

import json
import os
import requests
from typing import List, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed


def load_tags_system() -> Dict:
    """Загружает систему тегов из tags_system.json"""
    tags_system_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'tags_system.json')
    
    with open(tags_system_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_mod_tags(
    mod_title: str,
    mod_description: str,
    modrinth_categories: List[str],
    deepseek_key: str
) -> List[str]:
    """
    Определяет кастомные теги для мода используя AI
    
    Args:
        mod_title: Название мода
        mod_description: Описание мода
        modrinth_categories: Категории Modrinth (для доп. контекста)
        deepseek_key: API ключ DeepSeek
        
    Returns:
        Список наших кастомных тегов
    """
    
    print(f"🏷️  Analyzing mod: {mod_title}")
    
    # Загружаем систему тегов
    tags_system_data = load_tags_system()
    
    # Собираем все доступные теги
    all_tags = []
    tag_descriptions = {}
    
    for category_name, category_data in tags_system_data.get('categories', {}).items():
        category_tags = category_data.get('tags', [])
        all_tags.extend(category_tags)
        
        # Сохраняем описание категории для контекста
        tag_descriptions[category_name] = category_data.get('description', '')
    
    print(f"   📚 Available tags: {len(all_tags)}")
    
    # Формируем промпт для AI
    system_prompt = f"""You are a Minecraft mod analyzer. Your task is to analyze a mod and assign appropriate tags from our custom tag system.

Our tag system has {len(all_tags)} tags organized into categories:
{', '.join([f'{cat}: {desc}' for cat, desc in tag_descriptions.items()])}

Available tags:
{', '.join(all_tags)}  # All available tags

Your task:
1. Analyze the mod's name, description, and Modrinth categories
2. Select 3-10 most relevant tags from our tag system
3. Tags should be accurate and specific to the mod's functionality
4. Prioritize technical and functional tags over generic ones

Return ONLY a JSON array of tag strings, nothing else.
Example: ["optimization", "render-optimization", "client-side", "fps-boost"]
"""

    user_message = f"""Analyze this Minecraft mod:

Name: {mod_title}
Description: {mod_description[:500]}
Modrinth Categories: {', '.join(modrinth_categories)}

Return appropriate tags from our tag system."""

    try:
        # Запрос к DeepSeek
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
                'temperature': 0.3,  # Низкая температура для точности
                'max_tokens': 500  # Достаточно для массива из 10-15 тегов
            },
            timeout=30
        )
        
        if response.status_code != 200:
            raise Exception(f"DeepSeek API error: {response.status_code}")
        
        result = response.json()
        content = result['choices'][0]['message']['content'].strip()
        
        # Парсим JSON
        content = content.replace('```json', '').replace('```', '').strip()
        
        import re
        json_match = re.search(r'\[.*\]', content, re.DOTALL)
        if not json_match:
            raise Exception("Could not parse JSON array from AI response")
        
        tags = json.loads(json_match.group())
        
        # Фильтруем только существующие теги
        valid_tags = [tag for tag in tags if tag in all_tags]
        
        print(f"   ✅ Found {len(valid_tags)} tags: {', '.join(valid_tags)}")
        
        return valid_tags
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        print(f"   ⚠️  No tags assigned (AI feature requires subscription)")
        
        # Платная фича - без AI не работает
        return []


def batch_get_mod_tags(
    mods: List[Dict],
    deepseek_key: str,
    batch_size: int = 50,
    max_workers: int = 5
) -> Dict[str, List[str]]:
    """
    Получает теги для нескольких модов сразу (пачками по batch_size)
    
    Args:
        mods: Список модов с полями: title, description, categories
        deepseek_key: API ключ
        batch_size: Количество модов в одном запросе (по умолчанию 50)
        max_workers: Максимум параллельных запросов (по умолчанию 5)
        
    Returns:
        Tuple: (Словарь {mod_id: [tags]}, token_usage)
    """
    
    print(f"🏷️  [Batch Tagging] Processing {len(mods)} mods in batches of {batch_size} (max {max_workers} parallel)")
    
    # Загружаем систему тегов
    tags_system_data = load_tags_system()
    
    # Собираем все доступные теги
    all_tags = []
    tag_descriptions = {}
    
    for category_name, category_data in tags_system_data.get('categories', {}).items():
        category_tags = category_data.get('tags', [])
        all_tags.extend(category_tags)
        tag_descriptions[category_name] = category_data.get('description', '')
    
    print(f"   📚 Available tags: {len(all_tags)}")
    
    result = {}
    total_tokens = 0
    total_batches = (len(mods) + batch_size - 1) // batch_size
    
    # Создаем пачки
    batches = []
    for i in range(0, len(mods), batch_size):
        batch = mods[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        batches.append((batch_num, batch))
    
    # Обрабатываем пачками параллельно
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_process_mod_batch, batch, all_tags, tag_descriptions, deepseek_key): (batch_num, batch)
            for batch_num, batch in batches
        }
        
        for future in as_completed(futures):
            batch_num, batch = futures[future]
            try:
                batch_tags, tokens_used = future.result()
                result.update(batch_tags)
                total_tokens += tokens_used
                print(f"   ✅ Batch {batch_num}/{total_batches}: Tagged {len(batch_tags)} mods (~{tokens_used:,} tokens)")
            except Exception as e:
                print(f"   ❌ Batch {batch_num}/{total_batches} failed: {e}")
                # Присваиваем пустые теги для этой пачки
                for mod in batch:
                    mod_id = mod.get('project_id', mod.get('source_id', ''))
                    result[mod_id] = []
    
    # Рассчитываем стоимость (DeepSeek pricing: ~$0.25 per 1M tokens total)
    estimated_cost = (total_tokens * 0.25) / 1_000_000
    
    print(f"\n✅ [Batch Tagging] Complete: Tagged {len(result)}/{len(mods)} mods")
    print(f"   💰 Tokens used: {total_tokens:,} (~${estimated_cost:.6f})")
    
    return result, {
        'total_tokens': total_tokens,
        'estimated_cost': estimated_cost
    }


def _process_mod_batch(
    batch: List[Dict],
    all_tags: List[str],
    tag_descriptions: Dict[str, str],
    deepseek_key: str
) -> tuple[Dict[str, List[str]], int]:
    """
    Обрабатывает одну пачку модов за один AI запрос
    
    Returns:
        Tuple: (Словарь {mod_id: [tags]}, tokens_used)
    """
    
    # Формируем данные о модах для промпта
    mods_info = []
    mod_id_map = {}  # для сопоставления индекса с mod_id
    
    for idx, mod in enumerate(batch):
        mod_id = mod.get('project_id', mod.get('source_id', ''))
        title = mod.get('title', mod.get('name', 'Unknown'))
        description = mod.get('description', '')[:300]  # Ограничиваем описание
        modrinth_cats = mod.get('categories', [])
        
        mod_id_map[idx] = mod_id
        mods_info.append({
            'index': idx,
            'title': title,
            'description': description,
            'modrinth_categories': modrinth_cats
        })
    
    # Формируем промпт
    system_prompt = f"""You are a Minecraft mod analyzer. Analyze multiple mods and assign appropriate tags from our custom tag system.

Our tag system has {len(all_tags)} tags organized into categories:
{', '.join([f'{cat}: {desc}' for cat, desc in list(tag_descriptions.items())[:10]])}

Available tags (use ONLY these):
{', '.join(all_tags)}

Your task:
1. For each mod, analyze its name, description, and Modrinth categories
2. Select 3-10 most relevant tags from our tag system
3. Tags should be accurate and specific to each mod's functionality
4. Prioritize technical and functional tags over generic ones

Return ONLY a JSON object mapping mod index to tag array:
{{
  "0": ["optimization", "render-optimization"],
  "1": ["worldgen", "dimensions"],
  ...
}}"""
    
    user_message = f"""Analyze these {len(batch)} Minecraft mods and assign tags:

{json.dumps(mods_info, ensure_ascii=False, indent=2)}

Return a JSON object mapping index to tags array."""
    
    try:
        # Запрос к DeepSeek
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
                'max_tokens': 2000  # Увеличиваем для пачки модов
            },
            timeout=120  # Увеличиваем timeout для больших пачек
        )
        
        if response.status_code != 200:
            raise Exception(f"DeepSeek API error: {response.status_code}")
        
        result_data = response.json()
        content = result_data['choices'][0]['message']['content'].strip()
        
        # Получаем информацию о токенах
        tokens_used = result_data.get('usage', {}).get('total_tokens', 0)
        
        # Парсим JSON
        content = content.replace('```json', '').replace('```', '').strip()
        
        import re
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if not json_match:
            raise Exception("Could not parse JSON from AI response")
        
        tags_by_index = json.loads(json_match.group())
        
        # Преобразуем индексы обратно в mod_id
        result = {}
        for idx_str, tags in tags_by_index.items():
            idx = int(idx_str)
            if idx in mod_id_map:
                mod_id = mod_id_map[idx]
        # Фильтруем только существующие теги
                valid_tags = [tag for tag in tags if tag in all_tags]
                result[mod_id] = valid_tags
        
        return result, tokens_used
        
    except Exception as e:
        print(f"      ⚠️  AI request failed: {e}")
        raise
