# Crash Doctor → MCP Migration Plan

## 📋 Обзор

Миграция Crash Doctor с Python-оркестрированного pipeline на MCP (Model Context Protocol) для полноценного agent loop с reasoning между шагами.

**Цель:** Превратить Crash Doctor из "Python рулит → LLM анализирует → Python планирует" в "LLM Agent сам строит цепочку reasoning → tool calls".

---

## 🔄 Текущая vs Целевая Архитектура

### Текущая (Python-оркестрированная)

```
User Request
    ↓
analyze_and_fix_crash() [Python]
    ↓
Step 1: sanitize_crash_log() [Python]
    ↓
Step 2: analyze_crash() [LLM - один большой промпт]
    ↓
Step 3: plan_fixes() [Python - делает запросы к Modrinth]
    ↓
Step 4: create_patched_board_state() [Python]
    ↓
Result
```

**Проблемы:**
- Python рулит последовательностью
- LLM получает всё сразу в одном промпте
- Нет reasoning между шагами
- Нет автономности LLM

### Целевая (MCP Agent Loop)

```
User Request
    ↓
MCP Agent Start
    ↓
LLM Reasoning: "Нужно санитизировать лог"
    ↓
Tool: sanitize_log()
    ↓
LLM Reasoning: "Вижу ошибку с модом X, нужно найти его на Modrinth"
    ↓
Tool: search_modrinth_mod()
    ↓
LLM Reasoning: "Проверю версии для совместимости"
    ↓
Tool: check_mod_versions()
    ↓
LLM Reasoning: "Поищу похожие краши в БД"
    ↓
Tool: find_similar_crashes()
    ↓
LLM Reasoning: "Соберу план фиксов"
    ↓
Tool: create_fix_plan()
    ↓
LLM Reasoning: "Применю фиксы к board_state"
    ↓
Tool: apply_fixes_to_board()
    ↓
Final Result
```

**Преимущества:**
- LLM сам управляет цепочкой
- Reasoning между каждым шагом
- Автономность и гибкость
- Легко добавлять новые tools

---

## 🛠️ MCP Tools для Crash Doctor

### 1. `sanitize_log`
**Описание:** Очищает crash log от шума, PII, повторяющихся строк

**Вход:**
```json
{
  "crash_log": "raw crash log text",
  "max_length": 20000
}
```

**Выход:**
```json
{
  "sanitized_log": "cleaned log",
  "extracted_info": {
    "mc_version": "1.20.1",
    "mod_loader": "neoforge",
    "error_type": "ClassNotFoundException"
  }
}
```

**Реализация:** Обёртка над `log_sanitizer.sanitize_crash_log()`

---

### 2. `search_modrinth_mod`
**Описание:** Ищет мод на Modrinth по имени/slug/project_id

**Вход:**
```json
{
  "mod_identifier": "jei",
  "mc_version": "1.20.1",
  "mod_loader": "neoforge"
}
```

**Выход:**
```json
{
  "project_id": "jei",
  "slug": "jei",
  "title": "Just Enough Items",
  "description": "...",
  "versions": [...]
}
```

**Реализация:** Обёртка над `fix_planner.find_mod_on_modrinth()`

---

### 3. `check_mod_versions`
**Описание:** Проверяет доступные версии мода для конкретной версии MC/loader

**Вход:**
```json
{
  "project_id": "jei",
  "mc_version": "1.20.1",
  "mod_loader": "neoforge"
}
```

**Выход:**
```json
{
  "latest_version": "11.6.0",
  "file_url": "https://...",
  "filename": "jei-1.20.1-11.6.0.jar",
  "compatible": true
}
```

**Реализация:** Обёртка над `fix_planner.check_mod_update_available()`

---

### 4. `find_similar_crashes`
**Описание:** Ищет похожие краши в базе решений (Supabase)

**Вход:**
```json
{
  "crash_signature": "ClassNotFoundException: net.minecraft.class_1234",
  "mod_loader": "neoforge",
  "mc_version": "1.20.1"
}
```

**Выход:**
```json
{
  "similar_crashes": [
    {
      "session_id": "0000123",
      "root_cause": "Missing dependency",
      "suggestions": [...],
      "confidence": 0.9
    }
  ]
}
```

**Реализация:** Новый tool, запрос к Supabase `crash_doctor_sessions`

---

### 5. `validate_mod_conflicts`
**Описание:** Проверяет конфликты между модами в board_state

**Вход:**
```json
{
  "mod_list": ["jei", "rei", "emi"],
  "board_state": {...}
}
```

**Выход:**
```json
{
  "conflicts": [
    {
      "mod1": "jei",
      "mod2": "rei",
      "reason": "Both are item viewers",
      "severity": "high"
    }
  ]
}
```

**Реализация:** Новый tool, использует логику из `dependency_resolver.py`

---

### 6. `create_fix_plan`
**Описание:** Создаёт план фиксов на основе анализа

**Вход:**
```json
{
  "analysis": {
    "root_cause": "Missing dependency",
    "problematic_mods": [...],
    "missing_dependencies": [...]
  },
  "board_state": {...}
}
```

**Выход:**
```json
{
  "operations": [
    {
      "action": "add_mod",
      "target_mod": "fabric-api",
      "reason": "Required dependency",
      "priority": "critical"
    }
  ],
  "estimated_success_probability": 0.9
}
```

**Реализация:** Обёртка над `fix_planner.plan_fixes()`

---

### 7. `apply_fixes_to_board`
**Описание:** Применяет фиксы к board_state, создаёт patched версию

**Вход:**
```json
{
  "fix_plan": {
    "operations": [...]
  },
  "board_state": {...},
  "mc_version": "1.20.1",
  "mod_loader": "neoforge"
}
```

**Выход:**
```json
{
  "patched_board_state": {...},
  "applied_operations": 3,
  "failed_operations": 0,
  "mods_removed": 1,
  "mods_added": 2
}
```

**Реализация:** Обёртка над `board_patcher.create_patched_board_state()`

---

### 8. `save_crash_session`
**Описание:** Сохраняет сессию анализа в БД для базы знаний

**Вход:**
```json
{
  "user_id": "user_123",
  "crash_log": "...",
  "analysis": {...},
  "suggestions": [...],
  "confidence": 0.9
}
```

**Выход:**
```json
{
  "session_id": "0000123",
  "saved": true
}
```

**Реализация:** Обёртка над `crash_doctor_recorder.save_crash_doctor_session()`

---

## 📦 Структура Файлов

```
api/
├── crash_doctor/
│   ├── __init__.py
│   ├── analyze.py                    # УДАЛИТЬ Python-оркестрацию
│   ├── mcp_server.py                 # НОВЫЙ: MCP сервер
│   ├── mcp_tools.py                  # НОВЫЙ: Обёртки функций в MCP tools
│   ├── crash_analyzer.py             # ОСТАВИТЬ (используется в tools)
│   ├── fix_planner.py                # ОСТАВИТЬ (используется в tools)
│   ├── board_patcher.py              # ОСТАВИТЬ (используется в tools)
│   ├── log_sanitizer.py              # ОСТАВИТЬ (используется в tools)
│   └── ...
└── index.py                          # Обновить endpoint для MCP
```

---

## 🔨 План Миграции

### Этап 1: Создание MCP Tools (2-3 часа)

1. **Создать `mcp_tools.py`**
   - Обернуть существующие функции в MCP tools
   - Определить schemas для каждого tool
   - Добавить валидацию входных данных

2. **Создать `mcp_server.py`**
   - Настроить MCP сервер
   - Зарегистрировать все tools
   - Настроить agent loop

### Этап 2: Переделка analyze.py (1-2 часа)

1. **Упростить `analyze_and_fix_crash()`**
   - Убрать Python-оркестрацию
   - Оставить только запуск MCP agent
   - Передать начальный контекст в agent

2. **Создать system prompt для agent**
   - Описать задачу Crash Doctor
   - Объяснить доступные tools
   - Задать стратегию анализа

### Этап 3: Интеграция с API (1 час)

1. **Обновить `/api/ai/crash-doctor/analyze`**
   - Вызывать MCP agent вместо старого pipeline
   - Сохранить совместимость с SSE streaming
   - Обновить логирование

### Этап 4: Тестирование (2-3 часа)

1. **Unit тесты для каждого tool**
2. **Integration тесты для agent loop**
3. **E2E тесты с реальными crash logs**

### Этап 5: Оптимизация (1-2 часа)

1. **Оптимизировать промпты**
2. **Добавить rate limiting для tool calls**
3. **Улучшить error handling**

---

## 💻 Пример Кода

### mcp_tools.py

```python
"""
MCP Tools для Crash Doctor
Обёртки над существующими функциями
"""

from typing import Dict, Any
from .log_sanitizer import sanitize_crash_log, sanitize_game_log, extract_crash_info
from .fix_planner import find_mod_on_modrinth, check_mod_update_available
from .board_patcher import create_patched_board_state
from .crash_doctor_recorder import save_crash_doctor_session


def tool_sanitize_log(crash_log: str, max_length: int = 20000) -> Dict[str, Any]:
    """MCP Tool: Очищает crash log"""
    result = sanitize_crash_log(crash_log, max_length=max_length)
    return {
        "sanitized_log": result["sanitized_log"],
        "extracted_info": result["extracted_info"]
    }


def tool_search_modrinth_mod(
    mod_identifier: str,
    mc_version: str = None,
    mod_loader: str = None
) -> Dict[str, Any]:
    """MCP Tool: Ищет мод на Modrinth"""
    mod_info = find_mod_on_modrinth(mod_identifier, mc_version, mod_loader)
    if not mod_info:
        return {"error": f"Mod '{mod_identifier}' not found"}
    return mod_info


def tool_check_mod_versions(
    project_id: str,
    mc_version: str,
    mod_loader: str
) -> Dict[str, Any]:
    """MCP Tool: Проверяет версии мода"""
    version_info = check_mod_update_available(project_id, mc_version, mod_loader)
    if not version_info:
        return {"error": "No compatible versions found"}
    return version_info


# ... остальные tools
```

### mcp_server.py

```python
"""
MCP Server для Crash Doctor
"""

from mcp import Server, Tool
from .mcp_tools import (
    tool_sanitize_log,
    tool_search_modrinth_mod,
    tool_check_mod_versions,
    # ... остальные tools
)


def create_crash_doctor_mcp_server(deepseek_key: str, supabase_url: str, supabase_key: str):
    """Создаёт MCP сервер с tools для Crash Doctor"""
    
    server = Server("crash-doctor")
    
    # Регистрируем tools
    server.add_tool(
        Tool(
            name="sanitize_log",
            description="Очищает crash log от шума и PII, извлекает метаданные",
            input_schema={
                "type": "object",
                "properties": {
                    "crash_log": {"type": "string"},
                    "max_length": {"type": "integer", "default": 20000}
                },
                "required": ["crash_log"]
            },
            handler=tool_sanitize_log
        )
    )
    
    server.add_tool(
        Tool(
            name="search_modrinth_mod",
            description="Ищет мод на Modrinth по имени/slug/project_id",
            input_schema={
                "type": "object",
                "properties": {
                    "mod_identifier": {"type": "string"},
                    "mc_version": {"type": "string"},
                    "mod_loader": {"type": "string"}
                },
                "required": ["mod_identifier"]
            },
            handler=tool_search_modrinth_mod
        )
    )
    
    # ... остальные tools
    
    return server
```

### analyze.py (упрощённая версия)

```python
"""
Crash Doctor Analysis - MCP Agent Version
"""

from .mcp_server import create_crash_doctor_mcp_server
from deepseek import DeepSeekClient


def analyze_and_fix_crash(
    crash_log: str,
    board_state: Dict,
    game_log: str = None,
    mc_version: str = None,
    mod_loader: str = None,
    deepseek_key: str = None,
    supabase_url: str = None,
    supabase_key: str = None
) -> Dict:
    """
    Анализирует краш через MCP Agent Loop
    """
    
    # Создаём MCP сервер
    mcp_server = create_crash_doctor_mcp_server(deepseek_key, supabase_url, supabase_key)
    
    # Создаём DeepSeek клиент с function calling
    client = DeepSeekClient(api_key=deepseek_key)
    
    # System prompt для agent
    system_prompt = """You are Crash Doctor - an expert Minecraft crash analyzer.

Your task: Analyze crash logs and suggest fixes by using available tools.

Available tools:
- sanitize_log: Clean crash log and extract metadata
- search_modrinth_mod: Find mod on Modrinth
- check_mod_versions: Check mod versions for compatibility
- find_similar_crashes: Find similar crashes in database
- validate_mod_conflicts: Check mod conflicts
- create_fix_plan: Create fix plan
- apply_fixes_to_board: Apply fixes to board_state
- save_crash_session: Save analysis session

Strategy:
1. Start by sanitizing the crash log
2. Analyze the error and identify problematic mods
3. Search for mods on Modrinth if needed
4. Check versions for compatibility
5. Find similar crashes in database
6. Create fix plan
7. Apply fixes to board_state
8. Save session

Think step by step and use tools when needed."""

    # Начальный контекст
    initial_context = {
        "crash_log": crash_log,
        "game_log": game_log,
        "board_state": board_state,
        "mc_version": mc_version,
        "mod_loader": mod_loader
    }
    
    # Запускаем agent loop
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Analyze this crash:\n\nCrash Log:\n{crash_log[:5000]}\n\nBoard State: {len(board_state.get('mods', []))} mods"}
    ]
    
    # Agent loop с function calling
    result = client.chat.completions.create(
        model="deepseek-chat",
        messages=messages,
        tools=mcp_server.get_tools_schema(),  # Получаем schemas tools
        tool_choice="auto"  # LLM сам решает, когда вызывать tools
    )
    
    # Обрабатываем ответ agent
    # ... логика обработки
    
    return {
        "success": True,
        "suggestions": [...],
        "patched_board_state": {...},
        "confidence": 0.9
    }
```

---

## 📊 Оценка Изменений

### Код для переделки

| Файл | Текущий размер | Изменения | Новый размер |
|------|----------------|-----------|--------------|
| `analyze.py` | ~200 строк | Упростить до ~50 строк | ~50 строк |
| `mcp_server.py` | - | Создать новый | ~150 строк |
| `mcp_tools.py` | - | Создать новый | ~200 строк |
| `crash_analyzer.py` | ~350 строк | Оставить как есть | ~350 строк |
| `fix_planner.py` | ~400 строк | Оставить как есть | ~400 строк |
| `board_patcher.py` | ~200 строк | Оставить как есть | ~200 строк |

**Итого:** ~20% кода переделывается, остальное остаётся без изменений.

### Время реализации

- **Этап 1:** 2-3 часа (MCP tools)
- **Этап 2:** 1-2 часа (analyze.py)
- **Этап 3:** 1 час (API интеграция)
- **Этап 4:** 2-3 часа (тестирование)
- **Этап 5:** 1-2 часа (оптимизация)

**Всего:** ~7-11 часов работы

---

## ✅ Преимущества MCP

1. **Автономность:** LLM сам решает, какие tools вызывать
2. **Гибкость:** Легко добавлять новые tools
3. **Reasoning:** LLM думает между каждым шагом
4. **Меньше промптов:** Не нужно передавать всё сразу
5. **Меньше костылей:** Убираем Python-оркестрацию
6. **Качество:** LLM может итеративно улучшать анализ

---

## 🚀 Следующие Шаги

1. ✅ Создать этот план (готово)
2. ⏳ Установить MCP библиотеку для Python
3. ⏳ Создать `mcp_tools.py` с обёртками
4. ⏳ Создать `mcp_server.py`
5. ⏳ Переделать `analyze.py`
6. ⏳ Обновить API endpoint
7. ⏳ Протестировать
8. ⏳ Задеплоить

---

## 📚 Ресурсы

- [MCP Specification](https://modelcontextprotocol.io/)
- [Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk)
- [DeepSeek Function Calling Docs](https://platform.deepseek.com/docs/guides/function-calling)

---

**Статус:** 📝 План готов, ожидает реализации




