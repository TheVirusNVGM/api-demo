"""
AI Auto-Sort - автоматическая категоризация модов на доске
Использует DeepSeek для умной группировки модов по категориям
"""

import json
import requests
from typing import List, Dict
from collections import defaultdict


def auto_sort_mods(
    board_mods: List[Dict],
    tags_system: List[str],
    max_categories: int = 10,
    creativity: float = 0.5,
    user_prompt: str = "",
    deepseek_key: str = ""
) -> Dict:
    """
    Автоматически сортирует моды по категориям используя AI
    
    Args:
        board_mods: Список модов на доске с их описаниями
        tags_system: Список доступных тегов из tags_system.json
        max_categories: Максимальное количество категорий (1-20)
        creativity: Креативность группировки 0-10 (0=строго по тегам, 10=очень креативно)
        user_prompt: Опциональный промпт пользователя для кастомизации
        deepseek_key: API ключ DeepSeek
    
    Returns:
        Dict с категориями и распределением модов
    """
    
    print("=" * 80)
    print("🎨 [AI Auto-Sort] Starting automatic categorization...")
    print("=" * 80)
    print(f"   📦 Mods to sort: {len(board_mods)}")
    print(f"   🏷️  Available tags: {len(tags_system)}")
    print(f"   📁 Max categories: {max_categories}")
    print(f"   🎨 Creativity level: {creativity}/10")
    if user_prompt:
        print(f"   💬 User prompt: {user_prompt}")
    
    # Подготовка данных для AI - используем description (Modrinth) как основной источник информации
    mods_info = []
    for mod in board_mods:
        mod_name = mod.get("name", mod.get("title", "Unknown"))
        mod_description = mod.get("description", "")  # Описание с Modrinth
        mod_tags = mod.get("tags", [])  # Теги Modrinth (если есть)
        mod_source_id = mod.get("source_id", mod.get("project_id", ""))
        
        # Формируем полную информацию о моде
        mod_data = {
            "name": mod_name,
            "source_id": mod_source_id
        }
        
        # Description - КРИТИЧНО: это основной источник информации о функциональности мода (с Modrinth)
        if mod_description:
            # Увеличиваем лимит description для более полной информации
            mod_data["description"] = mod_description[:400] if len(mod_description) > 400 else mod_description
            if len(mod_description) > 400:
                mod_data["description_full_length"] = len(mod_description)
        
        # Теги Modrinth (если есть) - используем для дополнительного контекста
        if mod_tags:
            mod_data["modrinth_tags"] = mod_tags[:10]  # Ограничиваем количество тегов
        
        mods_info.append(mod_data)
    
    # Температура для DeepSeek (0-2, где 2 = максимальная креативность)
    # Маппим пользовательскую шкалу 0-10 в 0-2, но увеличиваем базовую температуру для креативности
    ai_temperature = min(1.2 + (creativity / 10.0) * 0.8, 2.0)  # От 1.2 до 2.0
    
    # Формируем промпт для AI с акцентом на креативность и description (Modrinth)
    system_prompt = f"""You are an expert at organizing Minecraft mods into logical, theme-based categories with CREATIVE and EVOCATIVE names.

Your task: Assign each mod to the BEST matching category based on MOD FUNCTIONALITY (from description) and Modrinth tags.

**ANALYSIS PRIORITY (in order):**

1. **READ THE DESCRIPTION FIRST AND CAREFULLY** (HIGHEST PRIORITY)
   - The description (from Modrinth) describes what the mod actually DOES
   - Look for keywords: "adds", "overhauls", "changes", "improves", "introduces", "provides"
   - If description says "adds new weapons" → equipment category
   - If description says "overhauls combat system" → combat mechanics category
   - Description is the PRIMARY source of truth - trust it over everything else

2. **Match description meaning to category purpose**
   - Read what the mod actually does from description
   - Equipment mods (weapons, armor, tools) → equipment categories
   - System mods (combat system, progression, mechanics) → system/mechanics categories
   - Building/decoration mods → building/decoration categories
   - Visual/graphics mods → graphics/visual categories
   - Performance mods (FPS, optimization) → performance categories
   - Library/API mods → library categories

3. **Modrinth tags** (confirmation and context)
   - Modrinth tags provide additional context about mod type
   - Common Modrinth tags: "adventure", "magic", "technology", "decoration", "optimization", "library", "api"
   - Use tags to confirm what the description says
   - Don't rely solely on tags - description is more important

**CREATIVE CATEGORY NAMING:**

- BE CREATIVE and THEMATIC with category names - avoid generic names
- DO NOT use generic names like "Combat Mods", "Building Blocks", "Core Systems"
- Every category name should be evocative and thematic
- Examples for different pack types:
  * Medieval/Fantasy: "Knight's Arsenal", "Royal Armory", "Castle Foundations", "Enchanted Visuals"
  * Tech: "Engineering Hub", "Power Grid", "Core Systems"
  * Adventure: "Explorer's Toolkit", "Shadow Realms"
- Look at mod descriptions to understand functionality, then create evocative names
- Category names should match the overall theme of the modpack (if user prompt provided)

**CATEGORIZATION RULES:**

1. Each mod should belong to exactly ONE category
2. Create {max_categories} or fewer categories
3. Try to balance category sizes (5-15 mods per category is ideal)
4. If a category would have 20+ mods → SPLIT it into 2-3 sub-categories with creative names
5. Separate libraries (API, dependency mods) from gameplay mods
   - Look for keywords: "library", "api", "framework", "dependency" in description or tags
6. Separate performance mods from graphics mods
   - Performance: "optimization", "fps", "performance", "lag", "memory"
   - Graphics: "shader", "lighting", "visual", "rendering", "texture"
7. Group mods by their PRIMARY purpose based on description

{"User's additional instructions: " + user_prompt if user_prompt else ""}

Return ONLY valid JSON in this format:
{{
  "categories": [
    {{
      "name": "Knight's Arsenal",
      "description": "Weapons and armor equipment - mods that add new weapons, shields, armor items",
      "mods": ["mod_id_1", "mod_id_2"]
    }}
  ]
}}"""

    user_message = f"""Categorize these {len(mods_info)} mods into creative, thematic categories:

{json.dumps(mods_info, indent=2, ensure_ascii=False)}

**IMPORTANT INSTRUCTIONS:**
1. Read each mod's DESCRIPTION carefully - it describes what the mod actually does (from Modrinth)
2. Create CREATIVE and THEMATIC category names (not generic ones)
3. Group mods by their PRIMARY function based on description content
4. Use Modrinth tags (if provided) as additional context, but trust description more
5. Separate libraries (API, dependency mods) from gameplay mods
6. Separate performance mods from graphics mods
7. Create up to {max_categories} categories
8. If a category would have 20+ mods → SPLIT it into 2-3 sub-categories

Return JSON only."""

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
                'temperature': ai_temperature,
                'max_tokens': 4000
            },
            timeout=60
        )
        
        if response.status_code != 200:
            raise Exception(f"DeepSeek API error: {response.status_code} - {response.text}")
        
        result = response.json()
        content = result['choices'][0]['message']['content'].strip()
        
        # Извлекаем информацию о токенах
        usage = result.get('usage', {})
        prompt_tokens = usage.get('prompt_tokens', 0)
        completion_tokens = usage.get('completion_tokens', 0)
        total_tokens = usage.get('total_tokens', 0)
        
        print("\n" + "=" * 80)
        print("💰 [Token Usage]")
        print("=" * 80)
        print(f"   📤 Prompt tokens: {prompt_tokens:,}")
        print(f"   📥 Completion tokens: {completion_tokens:,}")
        print(f"   💎 Total tokens: {total_tokens:,}")
        
        # Примерная стоимость (DeepSeek: ~$0.25 за 1M tokens total)
        total_cost = (total_tokens / 1_000_000) * 0.25
        
        print(f"   💵 Estimated cost: ${total_cost:.6f}")
        print("=" * 80 + "\n")
        
        # Парсим JSON из ответа
        content = content.replace('```json', '').replace('```', '').strip()
        
        import re
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if not json_match:
            raise Exception("Could not parse JSON from AI response")
        
        categorization = json.loads(json_match.group())
        
        print(f"✅ [AI Auto-Sort] Created {len(categorization['categories'])} categories")
        
        # Создаём mapping source_id -> category
        mod_to_category = {}
        for category in categorization['categories']:
            for mod_id in category['mods']:
                mod_to_category[mod_id] = category['name']
        
        # Проверяем какие моды остались без категории
        categorized_mod_ids = set(mod_to_category.keys())
        all_mod_ids = [mod.get('source_id', mod.get('project_id', '')) for mod in board_mods]
        uncategorized_mod_ids = [mod_id for mod_id in all_mod_ids if mod_id not in categorized_mod_ids]
        
        # Если есть некатегоризированные моды, создаём категорию "Other"
        if uncategorized_mod_ids:
            other_category = {
                'name': 'Other',
                'description': 'Mods that could not be categorized',
                'mods': uncategorized_mod_ids
            }
            categorization['categories'].append(other_category)
            
            # Добавляем в mapping
            for mod_id in uncategorized_mod_ids:
                mod_to_category[mod_id] = 'Other'
            
            print(f"   📁 Created 'Other' category for {len(uncategorized_mod_ids)} uncategorized mods")
        
        # Статистика
        categorized_count = len(mod_to_category)
        uncategorized_count = len(board_mods) - categorized_count
        
        print(f"   📊 Categorized: {categorized_count}/{len(board_mods)} mods")
        
        # Выводим созданные категории
        for cat in categorization['categories']:
            print(f"   📁 {cat['name']}: {len(cat['mods'])} mods")
        
        return {
            'success': True,
            'categories': categorization['categories'],
            'mod_to_category': mod_to_category,
            'stats': {
                'total_mods': len(board_mods),
                'categorized': categorized_count,
                'uncategorized': uncategorized_count,
                'categories_created': len(categorization['categories'])
            },
            'token_usage': {
                'prompt_tokens': prompt_tokens,
                'completion_tokens': completion_tokens,
                'total_tokens': total_tokens,
                'estimated_cost': total_cost
            }
        }
        
    except Exception as e:
        print(f"❌ [AI Auto-Sort] Error: {e}")
        import traceback
        traceback.print_exc()
        
        # Fallback: простая категоризация по тегам
        print("⚠️  [AI Auto-Sort] Falling back to tag-based categorization...")
        return fallback_categorization(board_mods, max_categories)


def fallback_categorization(board_mods: List[Dict], max_categories: int) -> Dict:
    """
    Простая категоризация по тегам если AI не сработал
    """
    # Группируем по первому тегу
    tag_groups = defaultdict(list)
    
    for mod in board_mods:
        tags = mod.get('tags', [])
        if tags:
            primary_tag = tags[0]
            tag_groups[primary_tag].append(mod.get('source_id', mod.get('project_id', '')))
        else:
            tag_groups['Other'].append(mod.get('source_id', mod.get('project_id', '')))
    
    # Берём топ N категорий по размеру
    sorted_groups = sorted(tag_groups.items(), key=lambda x: len(x[1]), reverse=True)
    top_groups = sorted_groups[:max_categories]
    
    categories = []
    mod_to_category = {}
    
    for tag, mod_ids in top_groups:
        categories.append({
            'name': tag.replace('-', ' ').title(),
            'description': f'Mods tagged as {tag}',
            'mods': mod_ids
        })
        for mod_id in mod_ids:
            mod_to_category[mod_id] = tag.replace('-', ' ').title()
    
    return {
        'success': True,
        'categories': categories,
        'mod_to_category': mod_to_category,
        'stats': {
            'total_mods': len(board_mods),
            'categorized': len(mod_to_category),
            'uncategorized': len(board_mods) - len(mod_to_category),
            'categories_created': len(categories)
        },
        'fallback': True
    }
