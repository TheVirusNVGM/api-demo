# 🔌 API Integration Guide

Документация для интеграции лаунчера и сайта с ASTRAL AI API.

## 🔐 Авторизация

**Все AI endpoints требуют JWT токен в заголовке:**

```http
Authorization: Bearer <jwt_token>
```

Токен получается через Supabase Auth и содержит `user_id` (в поле `sub`).

---

## 📡 Endpoints

### 1. `POST /api/ai/build-board`

**Описание:** Создаёт модпак в формате `board_state.json` для импорта в лаунчер.

**Требования:**
- ✅ Subscription tier: `test`, `premium`, или `pro` (free заблокированы)
- ✅ JWT токен в заголовке `Authorization`

**Request Body:**
```json
{
  "prompt": "Create a medieval fantasy modpack with castles and magic",
  "mc_version": "1.21.1",
  "mod_loader": "fabric",
  "current_mods": ["AANobbMI", "LNytGWDc"],  // Опционально: существующие моды на доске
  "max_mods": 80,
  "project_id": "my-modpack-id",  // Опционально: ID проекта в лаунчере
  "fabric_compat_mode": false,  // Опционально: включить Fabric+ совместимость
  "use_v3_architecture": true  // Опционально: использовать V3 архитектуру (по умолчанию true)
}
```

**Response (Success 200):**
```json
{
  "success": true,
  "build_id": "uuid-here",
  "board_state": {
    "project_id": "my-modpack-id",
    "camera": {
      "scale": 1.0,
      "tx": 0,
      "ty": 0
    },
    "mods": [
      {
        "project_id": "AANobbMI",
        "slug": "sodium",
        "position": { "x": 100, "y": 200 },
        "title": "Sodium",
        "icon_url": "https://...",
        "description": "...",
        "unique_id": "uuid-here",
        "is_disabled": false,
        "cached_dependencies": ["fabric-api"],
        "dependencies_fetched": true,
        "category_id": "performance-category-id",
        "category_index": 0
      }
    ],
    "categories": [
      {
        "id": "performance-category-id",
        "title": "Performance",
        "position": { "x": 50, "y": 150 },
        "color": "#3b82f6",
        "width": 340,
        "height": 200
      }
    ],
    "updated_at": "2024-01-01T00:00:00Z"
  },
  "summary": {
    "title": "Medieval Fantasy Modpack",
    "description": "...",
    "category_descriptions": [
      {
        "category": "Performance",
        "description": "..."
      }
    ],
    "key_features": ["..."],
    "stats": {
      "total_mods": 45,
      "gameplay_mods": 30,
      "dependencies": 15,
      "categories": 8
    },
    "tokens_used": 15000,
    "cost_usd": 0.15
  },
  "explanation": "AI explanation of mod selection...",
  "stats": {
    "total_mods": 45,
    "prompt": "Create a medieval fantasy modpack...",
    "mc_version": "1.21.1",
    "mod_loader": "fabric"
  }
}
```

**Response (Error 400/401/403/500):**
```json
{
  "error": "Unauthorized",
  "message": "AI features are not available for free tier. Please upgrade to test, premium, or pro subscription."
}
```

**Коды ошибок:**
- `400` - Invalid request (missing required fields)
- `401` - Unauthorized (invalid/missing token)
- `403` - Forbidden (free tier blocked)
- `500` - Internal server error

---

### 2. `POST /api/ai/auto-sort`

**Описание:** Автоматически категоризирует существующие моды на доске.

**Требования:**
- ✅ Subscription tier: `test`, `premium`, или `pro`
- ✅ JWT токен

**Request Body:**
```json
{
  "mods": [
    {
      "name": "Sodium",
      "source_id": "AANobbMI",
      "description": "Performance mod..."
    }
  ],
  "max_categories": 8,
  "creativity": 5.0
}
```

**Response:**
```json
{
  "success": true,
  "categories": [...],
  "mod_to_category": {
    "AANobbMI": "performance-category-id"
  },
  "stats": {...}
}
```

---

### 3. `POST /api/get-mod-tags`

**Описание:** Получает AI-генерируемые теги для модов.

**Требования:** Нет (публичный endpoint)

**Request Body:**
```json
{
  "mods": [
    {
      "name": "Sodium",
      "source_id": "AANobbMI",
      "description": "..."
    }
  ]
}
```

---

### 4. `POST /api/feedback`

**Описание:** Отправка фидбека о несовместимостях модов.

**Request Body:**
```json
{
  "mod_id": "AANobbMI",
  "incompatible_with": ["LNytGWDc"],
  "loader": "fabric",
  "mc_version": "1.21.1",
  "description": "Crashes on startup"
}
```

---

### 5. `POST /api/feedback/categorization`

**Описание:** Отправка фидбека о качестве категоризации.

**Request Body:**
```json
{
  "build_id": "uuid-from-build-response",
  "modpack_rating": 4,
  "issues": [
    {
      "issue_type": "wrong_category",
      "mod_id": "AANobbMI",
      "expected_capability": "sim.optimization",
      "actual_capability": "dependency.library",
      "severity": "high"
    }
  ]
}
```

---

## 🔧 Примеры интеграции

### TypeScript (Launcher)

```typescript
async function buildModpack(prompt: string, config: BuildConfig) {
  const token = astralAuth.getSession()?.access_token;
  
  const response = await fetch('http://localhost:5000/api/ai/build-board', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`
    },
    body: JSON.stringify({
      prompt,
      mc_version: config.minecraftVersion,
      mod_loader: config.modLoader,
      current_mods: config.currentModIds,
      max_mods: config.maxMods,
      project_id: config.projectId,
      fabric_compat_mode: config.fabricCompatMode
    })
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.message || 'Build failed');
  }

  const data = await response.json();
  return data;
}
```

### JavaScript (Website)

```javascript
async function buildModpack(prompt, config) {
  const token = localStorage.getItem('access_token');
  
  const response = await fetch('https://api.astral.com/api/ai/build-board', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`
    },
    body: JSON.stringify({
      prompt,
      mc_version: config.minecraftVersion,
      mod_loader: config.modLoader,
      max_mods: config.maxMods,
      fabric_compat_mode: false
    })
  });

  return response.json();
}
```

---

## 🔒 Security

1. **JWT Token Verification:**
   - Токен проверяется через Supabase Auth API
   - Извлекается `user_id` из токена (`sub` поле)

2. **Subscription Tier Check:**
   - Tier получается **ТОЛЬКО из БД** (никогда из клиента!)
   - Free пользователи получают `403 Forbidden`
   - Проверка происходит на каждом запросе

3. **Database Query:**
   ```sql
   SELECT subscription_tier FROM users WHERE id = $1
   ```

---

## 📊 Response Structure

### `board_state.mods`

Каждый мод содержит:
- `project_id` - Modrinth project ID
- `slug` - Modrinth slug (для URL)
- `position` - Позиция на доске `{x, y}`
- `title`, `description`, `icon_url`
- `unique_id` - UUID для отслеживания
- `category_id` - ID категории (для группировки)
- `category_index` - Индекс внутри категории
- `cached_dependencies` - Массив зависимостей
- `is_disabled` - Заблокирован ли мод

### `board_state.categories`

Каждая категория содержит:
- `id` - UUID категории
- `title` - Название категории
- `position` - Позиция на доске `{x, y}`
- `color` - HEX цвет (#3b82f6)
- `width`, `height` - Размеры категории

---

## ⚠️ Важные замечания

1. **Fabric Compat Mode:**
   - Если `fabric_compat_mode: true`, автоматически добавляются Connector моды
   - Передаётся оригинальный `mod_loader` проекта (сервер сам определяет нужен ли Fabric+)

2. **V3 Architecture:**
   - По умолчанию используется V3 (Architecture-First)
   - Для простых запросов автоматически переключается на V2
   - Можно явно указать через `use_v3_architecture: false`

3. **Dependencies:**
   - Зависимости добавляются автоматически
   - Не считаются в `max_mods` лимите
   - Всегда включены Fabric API, Cloth Config и т.д.

4. **Error Handling:**
   - Всегда проверяйте `response.ok` перед парсингом JSON
   - Ошибки возвращаются в формате `{error, message}`
   - 500 ошибки могут содержать HTML (для отладки) или JSON

---

## 🔗 Base URL

- **Local Development:** `http://localhost:5000`
- **Production:** `https://api.astral.com` (или ваш домен)
- **Cloudflare Tunnel:** `https://xxxxx.trycloudflare.com` (временный публичный URL)

---

## 📝 Changelog

### Current Version
- ✅ JWT auth через Supabase
- ✅ Subscription tier проверка
- ✅ Free tier блокировка
- ✅ V3 Conditional Architecture
- ✅ Fabric Compatibility Mode
- ✅ Build ID tracking для фидбека

