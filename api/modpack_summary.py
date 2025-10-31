"""
Modpack Summary Generator
Generates AI-powered summaries for modpacks including categories descriptions
"""

import json
from openai import OpenAI
from typing import List, Dict, Any


def generate_modpack_summary(
    prompt: str,
    categories: List[Dict[str, Any]],
    mods: List[Dict[str, Any]],
    mc_version: str,
    mod_loader: str,
    deepseek_key: str
) -> Dict[str, Any]:
    """
    Генерирует краткое описание сборки с объяснением категорий
    
    Args:
        prompt: Исходный промпт пользователя
        categories: Список категорий с модами
        mods: Список всех модов
        mc_version: Версия Minecraft
        mod_loader: Загрузчик модов
        deepseek_key: API ключ DeepSeek
    
    Returns:
        {
            'title': 'Название сборки',
            'description': 'Краткое описание сборки',
            'category_descriptions': [
                {
                    'category': 'Performance',
                    'description': 'Описание что в этой категории и зачем'
                },
                ...
            ],
            'key_features': ['фича 1', 'фича 2', ...],
            'stats': {
                'total_mods': 50,
                'dependencies': 15,
                'categories': 5
            },
            'tokens_used': 1234,
            'cost_usd': 0.0123
        }
    """
    
    print("=" * 80)
    print("📝 MODPACK SUMMARY GENERATOR")
    print("=" * 80)
    
    # Подготовка данных для AI
    # Создаём маппинг category_id -> category name
    category_map = {cat['id']: cat['title'] for cat in categories}
    
    # Группируем моды по категориям через source_id -> category_id
    from collections import defaultdict
    mods_by_category = defaultdict(list)
    
    # Проходимся по всем модам из result['mods']
    for mod in mods:
        mod_name = mod.get('name', 'Unknown')
        # Нужно найти категорию для этого мода - ищем по всем категориям
        # TODO: Более эффективный способ - использовать category_name из самого мода
        # Пока просто группируем все моды
        mods_by_category['all'].append(mod_name)
    
    category_info = []
    for cat in categories:
        cat_title = cat['title']
        # Получаем все моды которые должны быть в этой категории
        # Ищем моды по category_name (для Fabric Fix, Performance, и т.д.)
        cat_mods_names = []
        for mod in mods:
            mod_categories = mod.get('tags', [])  # Или categories
            if not mod_categories:
                mod_categories = mod.get('categories', [])
            
            # Проверяем соответствие категории (нечёткое совпадение)
            # TODO: Более точный маппинг
            cat_lower = cat_title.lower()
            if any(cat_lower in str(tag).lower() or str(tag).lower() in cat_lower for tag in mod_categories):
                cat_mods_names.append(mod.get('name', 'Unknown'))
        
        # Если не нашли модов через теги, просто говорим что есть категория
        if not cat_mods_names:
            cat_mods_names = [f"Mods in {cat_title}"]
        
        # Берём только первые 10
        sample_names = cat_mods_names[:10]
        if len(cat_mods_names) > 10:
            sample_names.append(f"...and {len(cat_mods_names) - 10} more")
        
        category_info.append({
            'name': cat_title,
            'mods_count': len(cat_mods_names),
            'sample_mods': sample_names
        })
    
    # Подсчёт статистики
    dependencies_count = len([m for m in mods if m.get('_added_as_dependency', False)])
    gameplay_mods_count = len(mods) - dependencies_count
    
    # Промпт для AI
    system_prompt = """You are a Minecraft modpack expert. Generate a concise, informative summary for a modpack.

Your response MUST be a valid JSON object with this exact structure:
{
    "title": "Short catchy title (2-4 words)",
    "description": "Brief description of the modpack purpose (1-2 sentences)",
    "category_descriptions": [
        {
            "category": "Category Name",
            "description": "What mods in this category do and why they're included (1 sentence)"
        }
    ],
    "key_features": ["Feature 1", "Feature 2", "Feature 3"]
}

Keep it concise and focused. Avoid listing individual mods - describe what the CATEGORY does overall."""

    user_prompt = f"""Generate a summary for this modpack:

**User Request:** {prompt}

**Statistics:**
- Total mods: {len(mods)}
- Gameplay mods: {gameplay_mods_count}
- Dependencies/Libraries: {dependencies_count}
- Categories: {len(categories)}

**Categories with mods:**
{json.dumps(category_info, indent=2)}

Generate a JSON summary that explains:
1. A short, catchy title for this modpack
2. Brief description of what this modpack is about
3. For EACH category - explain what mods in it do and why they're useful
4. 3-5 key features/benefits of this modpack (what it fixes, improves, adds)

Remember: Focus on CATEGORIES and overall benefits, not individual mods.
Response must be valid JSON matching the schema."""

    try:
        client = OpenAI(
            api_key=deepseek_key,
            base_url="https://api.deepseek.com"
        )
        
        print(f"🤖 Calling DeepSeek AI for summary generation...")
        print(f"   📊 Categories: {len(categories)}")
        print(f"   📦 Total mods: {len(mods)}")
        
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7,
            max_tokens=2000,
            response_format={"type": "json_object"}
        )
        
        # Извлекаем токены и стоимость
        tokens_used = response.usage.total_tokens
        cost_usd = (tokens_used / 1_000_000) * 0.27  # DeepSeek pricing
        
        print(f"✅ AI response received")
        print(f"   💰 Tokens: {tokens_used}, Cost: ${cost_usd:.6f}")
        
        # Парсим JSON ответ
        summary_data = json.loads(response.choices[0].message.content)
        
        # Добавляем статистику
        summary_data['stats'] = {
            'total_mods': len(mods),
            'gameplay_mods': gameplay_mods_count,
            'dependencies': dependencies_count,
            'categories': len(categories)
        }
        
        summary_data['tokens_used'] = tokens_used
        summary_data['cost_usd'] = cost_usd
        
        print()
        print(f"📝 Generated Summary:")
        print(f"   Title: {summary_data.get('title', 'N/A')}")
        print(f"   Categories described: {len(summary_data.get('category_descriptions', []))}")
        print(f"   Key features: {len(summary_data.get('key_features', []))}")
        print()
        
        return summary_data
        
    except Exception as e:
        print(f"❌ Error generating summary: {e}")
        import traceback
        traceback.print_exc()
        
        # Fallback - базовая сводка без AI
        return {
            'title': 'AI-Generated Modpack',
            'description': f'A modpack with {len(mods)} mods across {len(categories)} categories.',
            'category_descriptions': [
                {
                    'category': cat['title'],
                    'description': f'Contains {len([m for m in mods if m.get("category_id") == cat["id"]])} mods.'
                }
                for cat in categories
            ],
            'key_features': [
                f'{len(mods)} carefully selected mods',
                f'{len(categories)} organized categories',
                'Optimized for compatibility'
            ],
            'stats': {
                'total_mods': len(mods),
                'gameplay_mods': gameplay_mods_count,
                'dependencies': dependencies_count,
                'categories': len(categories)
            },
            'tokens_used': 0,
            'cost_usd': 0.0,
            'error': str(e)
        }
