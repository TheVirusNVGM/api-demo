"""
Smart Categorizer - умная категоризация модов для Minecraft сборок

Принимает список модов с метаданными (name, summary, tags)
Использует Deepseek API для анализа и группировки модов по логическим категориям
Возвращает структурированный результат с категориями
"""

import os
import json
from openai import OpenAI
from typing import List, Dict, Optional


class SmartCategorizer:
    """
    Категоризатор модов на основе AI анализа
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Инициализация клиента Deepseek
        
        Args:
            api_key: API ключ Deepseek (если None, берётся из переменной окружения)
        """
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise ValueError("DEEPSEEK_API_KEY не найден в переменных окружения")
        
        self.client = OpenAI(
            api_key=self.api_key,
            base_url="https://api.deepseek.com"
        )
        
        # Стандартные категории для модов (можно расширять)
        self.standard_categories = [
            "Performance Optimization",
            "Graphics & Visual",
            "Utility & Tools",
            "Library & API",
            "World Generation",
            "Gameplay Enhancement",
            "Combat & Weapons",
            "Technology & Automation",
            "Magic & Spells",
            "Building & Decoration",
            "Food & Farming",
            "Transportation",
            "Adventure & Exploration",
            "Multiplayer & Social",
            "Quality of Life"
        ]
    
    def categorize_mods(self, mods: List[Dict], custom_categories: Optional[List[str]] = None) -> List[Dict]:
        """
        Категоризирует список модов
        
        Args:
            mods: Список модов с полями:
                - name: название мода
                - summary: краткое описание
                - capabilities: список capabilities (приоритет)
                - tags: список тегов (опционально)
            custom_categories: Пользовательские категории (если None, используются стандартные)
        
        Returns:
            Список модов с добавленным полем category
            Пример: [{"name": "Sodium", "category": "Performance Optimization", ...}]
        """
        if not mods:
            return []
        
        categories = custom_categories or self.standard_categories
        
        # Формируем промпт для AI
        prompt = self._build_categorization_prompt(mods, categories)
        
        try:
            # Отправляем запрос в Deepseek
            response = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert in Minecraft modding ecosystem. Your task is to categorize mods into logical groups based on their functionality and purpose."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.3,  # Низкая температура для более консистентных результатов
                max_tokens=2000
            )
            
            # Парсим ответ
            result_text = response.choices[0].message.content
            categorized_mods = self._parse_categorization_result(result_text, mods)
            
            return categorized_mods
            
        except Exception as e:
            print(f"❌ Ошибка при категоризации модов: {e}")
            # Fallback: возвращаем моды с категорией "Uncategorized"
            return [{**mod, "category": "Uncategorized"} for mod in mods]
    
    def _build_categorization_prompt(self, mods: List[Dict], categories: List[str]) -> str:
        """
        Создаёт промпт для AI
        """
        # Формируем список модов для анализа
        mods_text = ""
        for i, mod in enumerate(mods, 1):
            capabilities = mod.get("capabilities", [])
            tags = mod.get("tags", [])
            
            # Capabilities - главный сигнал
            capabilities_str = ", ".join(capabilities) if capabilities else "no capabilities"
            tags_str = ", ".join(tags) if tags else "no tags"
            
            mods_text += f"{i}. {mod['name']}\n"
            mods_text += f"   Summary: {mod.get('summary', 'No description')}\n"
            mods_text += f"   Capabilities: {capabilities_str}\n"
            mods_text += f"   Tags: {tags_str}\n\n"
        
        # Формируем список категорий
        categories_text = "\n".join([f"- {cat}" for cat in categories])
        
        prompt = f"""Analyze the following Minecraft mods and assign each one to the most appropriate category.

AVAILABLE CATEGORIES:
{categories_text}

MODS TO CATEGORIZE:
{mods_text}

Please respond in JSON format with an array of objects:
[
  {{"name": "ModName", "category": "CategoryName"}},
  ...
]

Important rules:
1. Each mod must be assigned to exactly ONE category
2. Use CAPABILITIES as the PRIMARY signal for categorization (capabilities define what the mod does)
3. Use tags and summary as SECONDARY signals if capabilities are missing or unclear
4. Choose the MOST appropriate category based on the mod's primary function
5. Use EXACT category names from the list above
6. If a mod doesn't fit any category well, choose the closest match
7. Return ONLY the JSON array, no additional text
"""
        return prompt
    
    def _parse_categorization_result(self, result_text: str, original_mods: List[Dict]) -> List[Dict]:
        """
        Парсит ответ от AI и совмещает с оригинальными данными модов
        """
        try:
            # Извлекаем JSON из ответа (может быть обёрнут в markdown)
            json_start = result_text.find('[')
            json_end = result_text.rfind(']') + 1
            
            if json_start == -1 or json_end == 0:
                raise ValueError("JSON не найден в ответе")
            
            json_text = result_text[json_start:json_end]
            categorization = json.loads(json_text)
            
            # Создаём словарь название -> категория
            category_map = {item['name']: item['category'] for item in categorization}
            
            # Добавляем категории к оригинальным модам
            result = []
            for mod in original_mods:
                mod_copy = mod.copy()
                mod_copy['category'] = category_map.get(mod['name'], 'Uncategorized')
                result.append(mod_copy)
            
            return result
            
        except Exception as e:
            print(f"❌ Ошибка парсинга результата: {e}")
            print(f"Ответ AI: {result_text}")
            # Fallback
            return [{**mod, "category": "Uncategorized"} for mod in original_mods]
    
    def group_by_category(self, categorized_mods: List[Dict]) -> Dict[str, List[Dict]]:
        """
        Группирует категоризированные моды по категориям
        
        Returns:
            Словарь {category_name: [list of mods]}
        """
        grouped = {}
        for mod in categorized_mods:
            category = mod.get('category', 'Uncategorized')
            if category not in grouped:
                grouped[category] = []
            grouped[category].append(mod)
        
        return grouped


# Convenience функция для быстрого использования
def categorize_mods(mods: List[Dict], api_key: Optional[str] = None) -> List[Dict]:
    """
    Быстрая функция для категоризации модов
    
    Args:
        mods: Список модов с name, summary, capabilities, tags
        api_key: API ключ (опционально)
    
    Returns:
        Список модов с добавленным полем category
    """
    categorizer = SmartCategorizer(api_key=api_key)
    return categorizer.categorize_mods(mods)


# Тестовый запуск (не используется - вызывается из API)
if __name__ == "__main__":
    print("⚠️  Smart Categorizer предназначен для использования через API")
    print("   Запустите API сервер: python api/index.py")
    print("   Или используйте endpoint: POST /api/ai/build-board")
