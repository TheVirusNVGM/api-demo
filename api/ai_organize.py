"""
AI Organization Logic
Анализирует моды и раскидывает их по категориям
"""

import requests
import json
import re
from typing import List, Dict


def organize_board(mods: List[Dict], deepseek_key: str) -> Dict:
    """
    Организует моды в категории используя DeepSeek AI
    
    Args:
        mods: Список модов с информацией (name, description, slug)
        deepseek_key: API ключ DeepSeek
    
    Returns:
        Dict с категориями и распределением модов
    """
    
    # Формируем промпт для AI
    mods_text = ""
    for i, mod in enumerate(mods[:200], 1):  # Максимум 200 модов за раз
        name = mod.get('name', mod.get('title', 'Unknown'))
        desc = mod.get('description', '')[:200]  # Обрезаем длинные описания
        slug = mod.get('slug', mod.get('project_id', f'mod-{i}'))
        mods_text += f"{i}. [{slug}] {name}\n   {desc}\n\n"
    
    prompt = f"""Analyze these {len(mods)} Minecraft mods and organize them into logical categories.

MODS TO ORGANIZE:
{mods_text}

Task:
1. Group similar mods together
2. Create 5-12 category boxes based on mod functionality
3. Each category should have 5-30 mods
4. Use clear category names

Available category types:
- Performance & Optimization (FPS, rendering, memory)
- Technology & Machines (automation, engineering, tech mods)
- Magic & Spells (magical content, spells, enchantments)
- Adventure & Exploration (dungeons, structures, dimensions)
- Decoration & Building (blocks, furniture, aesthetics)
- World Generation (biomes, terrain, world mods)
- Utility & QoL (helpful tools, interface improvements)
- Library & API (dependencies, frameworks)
- Combat & Equipment (weapons, armor, fighting)
- Storage & Inventory (chests, backpacks, organization)
- Graphics & Visual (shaders, textures, visual effects)
- Farming & Food (agriculture, cooking, animals)

Return ONLY valid JSON in this format:
{{
  "categories": [
    {{
      "id": "performance",
      "title": "⚡ Performance & Optimization",
      "color1": "#10b981",
      "color2": "#059669",
      "mod_slugs": ["sodium", "lithium", "ferrite-core"]
    }},
    {{
      "id": "tech",
      "title": "⚙️ Technology & Machines",
      "color1": "#3b82f6",
      "color2": "#2563eb",
      "mod_slugs": ["create", "mekanism"]
    }}
  ]
}}

Rules:
- Every mod MUST be assigned to exactly ONE category
- Use descriptive emoji + title for each category
- Choose appropriate colors (hex codes)
- Prioritize grouping by functionality over popularity
"""

    print("📤 Sending to DeepSeek...")
    
    # Отправляем запрос в DeepSeek
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
                'content': prompt
            }],
            'temperature': 0.3,
            'max_tokens': 4000
        },
        timeout=60
    )
    
    if response.status_code != 200:
        raise Exception(f"DeepSeek API error: {response.status_code} - {response.text}")
    
    result = response.json()
    content = result['choices'][0]['message']['content']
    
    print("📥 Received response from DeepSeek")
    
    # Парсим JSON из ответа
    json_match = re.search(r'\{.*\}', content, re.DOTALL)
    if not json_match:
        raise Exception("Could not parse JSON from AI response")
    
    organization = json.loads(json_match.group())
    
    # Валидация: проверяем что все моды распределены
    all_assigned_slugs = set()
    for cat in organization['categories']:
        all_assigned_slugs.update(cat['mod_slugs'])
    
    print(f"✅ Organized: {len(all_assigned_slugs)} mods into {len(organization['categories'])} categories")
    
    return organization


# Цвета для категорий (если AI не предложит свои)
DEFAULT_COLORS = {
    'performance': ('#10b981', '#059669'),
    'tech': ('#3b82f6', '#2563eb'),
    'magic': ('#8b5cf6', '#7c3aed'),
    'adventure': ('#f59e0b', '#d97706'),
    'decoration': ('#ec4899', '#db2777'),
    'worldgen': ('#14b8a6', '#0d9488'),
    'utility': ('#6366f1', '#4f46e5'),
    'library': ('#64748b', '#475569'),
    'combat': ('#ef4444', '#dc2626'),
    'storage': ('#84cc16', '#65a30d'),
    'graphics': ('#f97316', '#ea580c'),
    'farming': ('#22c55e', '#16a34a'),
}