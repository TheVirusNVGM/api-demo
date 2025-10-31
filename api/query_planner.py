"""
Layer 0: Query Planner
Анализирует запрос пользователя и создаёт структурированный план поиска
"""

import requests
import json
import re
from typing import Dict, List, Optional
from config import DEEPSEEK_INPUT_COST, DEEPSEEK_OUTPUT_COST


def create_search_plan(
    user_prompt: str,
    mc_version: str,
    mod_loader: str,
    current_mods: List[str],
    max_mods: int,
    deepseek_key: str,
    fabric_compat_mode: bool = False
) -> Dict:
    """
    Создаёт структурированный план поиска используя DeepSeek
    
    Args:
        user_prompt: Запрос пользователя
        mc_version: Версия Minecraft
        mod_loader: Загрузчик (fabric/neoforge/forge)
        current_mods: Project IDs модов уже на доске
        max_mods: Максимум модов для добавления
        deepseek_key: API ключ DeepSeek
        fabric_compat_mode: Включен ли Fabric Compatibility Mode
    
    Returns:
        Dict со структурированным планом поиска
    """
    
    print("🧠 [Query Planner] Analyzing user request...")
    
    # Формируем промпт для Query Planner
    system_context = f"""You are an expert Query Planner for a Minecraft modpack builder system.

SYSTEM CONTEXT:
- Minecraft Version: {mc_version}
- Mod Loader: {mod_loader}
- Fabric Compat Mode: {'ENABLED' if fabric_compat_mode else 'DISABLED'}
- Current mods on board: {len(current_mods)}
- Max mods to add: {max_mods}

IMPORTANT LOADER-SPECIFIC KNOWLEDGE:
- For NeoForge 1.21.1: Sodium, Lithium, and Iris are AVAILABLE (use these, not Embeddium/Rubidium)
- For NeoForge 1.20.1: Use Embeddium/Rubidium instead of Sodium
- Key performance mods for NeoForge: sodium, lithium, modernfix, noisium, entityculling, iris, dynamic-fps
- Always use exact mod names that are available for the target loader

DATABASE STRUCTURE:
- We have a vector database with mod embeddings (semantic search)
- We support keyword search (lexical matching)
- We have tag/category filters
- Available categories: optimization, library, utility, decoration, technology, adventure, magic, food, storage, worldgen, mobs, etc.

YOUR TASK:
Analyze the user's request and create an OPTIMAL SEARCH PLAN in JSON format.

The search plan should include:
1. **request_type**: Type of request (for routing logic)
   - "simple_add": User wants specific mods by name (1-10 mods)
   - "themed_pack": User wants a themed modpack (20+ mods with style/theme)
   - "performance": User wants optimization/performance mods only
   
2. **use_architecture_matcher**: Boolean flag
   - true: Use Architecture Matcher to find reference modpack patterns (for themed_pack)
   - false: Skip Architecture Matcher (for simple_add or performance)
   
3. **search_queries**: List of queries to execute
   - "semantic" queries for vector/embedding search (conceptual matching)
   - "keyword" queries for exact term matching
   - Each query has a weight (0.0-1.0) that determines its importance
   
4. **filters**: Constraints to apply
   - exclude_project_ids: Mods already on board
   - min_downloads: Minimum download threshold
   - categories: Required or preferred categories
   
5. **diversity**: Rules to ensure variety
   - max_per_category: Limit mods per category
   - ensure_variety: Boolean flag
   
6. **target_count**: How many candidate mods to fetch (usually 1.5-2x max_mods)

IMPORTANT RULES FOR REQUEST TYPE:
- request_type="simple_add" if:
  * User mentions 1-10 specific mod names ("add sodium", "give me iris and lithium")
  * Request is very short and concrete
  * No theme/style mentioned
  → use_architecture_matcher=false

- request_type="themed_pack" if:
  * User describes a theme/style ("RPG", "cyberpunk", "medieval", "survival")
  * Requests 20+ mods or says "modpack"
  * Describes gameplay style or aesthetic
  → use_architecture_matcher=true

- request_type="performance" if:
  * User only asks for optimization/performance/FPS mods
  * No other themes mentioned
  → use_architecture_matcher=false

SEARCH STRATEGY RULES:
- If user asks for SPECIFIC mods by name → use keyword queries with high weight
- If user asks for a THEME/STYLE → use semantic queries with high weight
- If user asks for performance → prioritize "optimization" category
- If user mentions specific gameplay (PvP, survival, building) → semantic + category filters
- Always exclude current_mods to avoid duplicates

CRITICAL FILTERING RULES:
- Use "categories_include" ONLY for pure single-category requests (e.g., "give me only optimization mods")
- Use "categories_prefer" for mixed requests where category is important but not exclusive
- NEVER use "categories_include" if the request has multiple themes/aspects
- Example: "cyberpunk with performance" → use "categories_prefer" NOT "categories_include"
- Example: "only optimization mods for low-end PC" → use "categories_include"
"""

    user_message = f"""USER REQUEST: "{user_prompt}"

Current mods already added: {current_mods[:10] if current_mods else 'None'}

Create an optimal search plan to find the best mods for this request.

RETURN ONLY VALID JSON (no markdown, no explanations):
{{
  "request_type": "simple_add|themed_pack|performance",
  "use_architecture_matcher": true,
  "strategy": "semantic|keyword|hybrid",
  "search_queries": [
    {{
      "type": "semantic|keyword",
      "text": "query text for vector search",
      "weight": 0.7,
      "limit": 150
    }}
  ],
  "filters": {{
    "exclude_project_ids": [],
    "min_downloads": 5000,
    "categories_include": [],
    "categories_prefer": []
  }},
  "diversity": {{
    "max_per_category": 20,
    "ensure_variety": true
  }},
  "target_count": {max_mods * 2}
}}

EXAMPLES:

Request: "add sodium and iris"
→ request_type: "simple_add"
→ use_architecture_matcher: false
→ Strategy: keyword (specific mods requested)
→ Queries: [{{ "type": "keyword", "text": "sodium iris", "weight": 1.0 }}]

Request: "150 survival mods with progression"
→ request_type: "themed_pack"
→ use_architecture_matcher: true
→ Strategy: hybrid
→ Queries: [
    {{ "type": "semantic", "text": "survival progression gameplay difficulty", "weight": 0.7 }},
    {{ "type": "keyword", "text": "survival progression", "weight": 0.3 }}
  ]

Request: "only optimization mods for low-end PC"
→ request_type: "performance"
→ use_architecture_matcher: false
→ Strategy: hybrid
→ Queries: [
    {{ "type": "semantic", "text": "performance optimization FPS boost", "weight": 0.6 }},
    {{ "type": "keyword", "text": "sodium lithium iris modernfix", "weight": 0.9 }}
  ]
→ Filters: {{ "categories_include": ["optimization"] }}

Request: "cyberpunk modpack with performance optimization"
→ request_type: "themed_pack"
→ use_architecture_matcher: true
→ Strategy: hybrid
→ Queries: [
    {{ "type": "semantic", "text": "cyberpunk technology futuristic neon", "weight": 0.8 }},
    {{ "type": "semantic", "text": "performance optimization FPS", "weight": 0.7 }}
  ]
→ Filters: {{ "categories_prefer": ["optimization", "technology"] }}

Request: "RPG модпак с магией и данжами"
→ request_type: "themed_pack"
→ use_architecture_matcher: true
→ Strategy: semantic
→ Queries: [{{ "type": "semantic", "text": "RPG magic spells dungeons adventure", "weight": 1.0 }}]

Now create the search plan:"""

    # Отправляем в DeepSeek
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
                    {'role': 'system', 'content': system_context},
                    {'role': 'user', 'content': user_message}
                ],
                'temperature': 0.1,  # Очень низкая для структурированного вывода
                'max_tokens': 2000
            },
            timeout=30
        )
        
        if response.status_code != 200:
            raise Exception(f"DeepSeek API error: {response.status_code} - {response.text}")
        
        result = response.json()
        content = result['choices'][0]['message']['content'].strip()
        
        # Извлекаем инфо о токенах
        usage = result.get('usage', {})
        prompt_tokens = usage.get('prompt_tokens', 0)
        completion_tokens = usage.get('completion_tokens', 0)
        total_tokens = usage.get('total_tokens', 0)
        
        cost = (prompt_tokens * DEEPSEEK_INPUT_COST / 1_000_000) + (completion_tokens * DEEPSEEK_OUTPUT_COST / 1_000_000)
        
        print(f"📥 [Query Planner] Received response")
        print(f"   📊 Tokens: {total_tokens:,} (prompt: {prompt_tokens:,}, completion: {completion_tokens:,})")
        print(f"   💵 Cost: ${cost:.6f}")
        
        # Парсим JSON (убираем markdown если есть)
        content = content.replace('```json', '').replace('```', '').strip()
        
        # Находим JSON объект
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if not json_match:
            raise Exception("Could not parse JSON from Query Planner response")
        
        search_plan = json.loads(json_match.group())
        
        # Добавляем current_mods в exclude_project_ids
        if 'filters' not in search_plan:
            search_plan['filters'] = {}
        
        search_plan['filters']['exclude_project_ids'] = current_mods
        
        # Добавляем метаданные
        search_plan['_metadata'] = {
            'user_prompt': user_prompt,
            'mc_version': mc_version,
            'mod_loader': mod_loader,
            'fabric_compat_mode': fabric_compat_mode,
            'max_mods': max_mods
        }
        
        # Добавляем token info
        search_plan['_tokens'] = {
            'prompt_tokens': prompt_tokens,
            'completion_tokens': completion_tokens,
            'total_tokens': total_tokens,
            'cost_usd': cost
        }
        
        print(f"✅ [Query Planner] Created search plan:")
        print(f"   Strategy: {search_plan.get('strategy', 'unknown')}")
        print(f"   Queries: {len(search_plan.get('search_queries', []))}")
        print(f"   Target candidates: {search_plan.get('target_count', 'unknown')}")
        
        return search_plan
        
    except Exception as e:
        print(f"❌ [Query Planner] Error: {e}")
        # Fallback: создаём простой план
        print("⚠️  [Query Planner] Using fallback search plan")
        return create_fallback_plan(user_prompt, current_mods, max_mods)


def create_fallback_plan(user_prompt: str, current_mods: List[str], max_mods: int) -> Dict:
    """
    Создаёт простой план поиска если AI не сработал
    """
    # Определяем request_type по длине и ключевым словам
    prompt_lower = user_prompt.lower()
    word_count = len(user_prompt.split())
    
    if word_count <= 5 and ('add' in prompt_lower or 'give' in prompt_lower):
        request_type = "simple_add"
        use_architecture_matcher = False
    elif 'performance' in prompt_lower or 'optimization' in prompt_lower or 'fps' in prompt_lower:
        request_type = "performance"
        use_architecture_matcher = False
    else:
        request_type = "themed_pack"
        use_architecture_matcher = True
    
    return {
        "request_type": request_type,
        "use_architecture_matcher": use_architecture_matcher,
        "strategy": "hybrid",
        "search_queries": [
            {
                "type": "semantic",
                "text": user_prompt,
                "weight": 0.7,
                "limit": max_mods * 3
            },
            {
                "type": "keyword",
                "text": user_prompt,
                "weight": 0.3,
                "limit": max_mods * 2
            }
        ],
        "filters": {
            "exclude_project_ids": current_mods,
            "min_downloads": 1000,
            "categories_include": [],
            "categories_prefer": []
        },
        "diversity": {
            "max_per_category": 30,
            "ensure_variety": True
        },
        "target_count": max_mods * 2,
        "_metadata": {
            "user_prompt": user_prompt,
            "max_mods": max_mods,
            "is_fallback": True
        }
    }
