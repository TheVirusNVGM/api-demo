# 🔐 API Security - Subscription Tier Protection

## Обзор

AI endpoints защищены проверкой subscription tier на сервере. Free пользователи **полностью заблокированы** от доступа к AI функциям.

## Защищённые Endpoints

### `POST /api/ai/build-board`
- **Требование**: subscription_tier != 'free'
- **Доступ**: test, premium, pro

### `POST /api/ai/auto-sort`
- **Требование**: subscription_tier != 'free'
- **Доступ**: test, premium, pro

## Механизм защиты

### 1. JWT Token Verification

```python
# Клиент отправляет токен в заголовке
Authorization: Bearer <jwt_token>
```

**Проверка:**
1. Извлекается токен из заголовка `Authorization`
2. Валидируется через Supabase Auth API (`/auth/v1/user`)
3. Извлекается `user_id` из токена

### 2. Subscription Tier Check

**Важно:** subscription_tier берётся **ТОЛЬКО ИЗ БД**, никогда из клиента!

```python
# Проверка в БД
subscription_tier = get_user_subscription_tier(user_id)

# Блокировка free
if subscription_tier == 'free':
    return 403 Forbidden
```

### 3. Database Query

```sql
-- Query в таблицу users
SELECT subscription_tier FROM users WHERE id = $1
```

**Таблица users должна содержать:**
- `id` (UUID) - user_id из JWT
- `subscription_tier` (TEXT) - 'free', 'test', 'premium', 'pro'

## Использование

### В коде

```python
from auth import require_subscription

@app.route('/api/ai/build-board', methods=['POST'])
@require_subscription  # ✅ Защита
def api_build_board_state():
    # Только пользователи с test/premium/pro могут дойти до этой точки
    user_id = g.user_id  # Доступен после проверки
    subscription_tier = g.subscription_tier
    ...
```

### Пользовательские данные

После успешной проверки доступны в Flask `g`:

```python
user_id = g.user_id              # UUID пользователя
subscription_tier = g.subscription_tier  # 'test' | 'premium' | 'pro'
```

## Ошибки

### 401 Unauthorized
- Токен отсутствует
- Токен невалидный или истёк
- Пользователь не найден в БД

### 403 Forbidden
- Пользователь имеет subscription_tier = 'free'
- Сообщение: "AI features are not available for free tier..."

## Логирование

Все попытки доступа логируются:

```
✅ [Auth] Token verified for user <uuid>
✅ [Auth] Allowed test user <uuid> to /api/ai/build-board
🚫 [Auth] BLOCKED free user <uuid> from AI endpoint /api/ai/build-board
⚠️  [Auth] Invalid token (401 from Supabase)
```

## Важные принципы

1. **НИКОГДА не доверяйте клиенту** - subscription_tier всегда из БД
2. **Всегда проверяйте токен** - перед проверкой подписки
3. **Логируйте блокировки** - для мониторинга попыток обхода
4. **Fallback безопасность** - если Supabase недоступен, fallback на декодирование без проверки подписи (для отладки, но работает)

## Настройка

### Переменные окружения

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-service-role-key
```

### Зависимости

```bash
pip install pyjwt>=2.8.0
```

## Testing

### Тест с валидным токеном

```bash
curl -X POST http://localhost:5000/api/ai/build-board \
  -H "Authorization: Bearer <valid_jwt_token>" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "test"}'
```

### Тест без токена

```bash
curl -X POST http://localhost:5000/api/ai/build-board \
  -H "Content-Type: application/json" \
  -d '{"prompt": "test"}'
# → 401 Unauthorized
```

### Тест с free пользователем

```bash
# С токеном free пользователя
# → 403 Forbidden
```

