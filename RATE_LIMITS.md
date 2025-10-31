# 🚦 Rate Limiting System

## Overview

Rate limiting система защищает AI endpoints от злоупотреблений и обеспечивает fair use по тарифам.

## Tier Limits

| Tier    | Daily Requests | Monthly Requests | Max Mods/Request | AI Tokens/Month |
|---------|---------------|------------------|------------------|-----------------|
| **Free**    | 0             | 0                | 0                | 0               |
| **Test**    | 50            | 1,000            | 50               | 100,000         |
| **Premium** | 200           | 5,000            | 100              | 500,000         |
| **Pro**     | Unlimited     | Unlimited        | 200              | Unlimited       |

## How It Works

### 1. Database Schema

```sql
ALTER TABLE users
ADD COLUMN daily_requests_used INTEGER DEFAULT 0,
ADD COLUMN monthly_requests_used INTEGER DEFAULT 0,
ADD COLUMN ai_tokens_used INTEGER DEFAULT 0,
ADD COLUMN last_request_date DATE,
ADD COLUMN custom_limits JSONB;
```

### 2. Check Limits (Before Request)

```python
rate_limiter = get_rate_limiter(SUPABASE_URL, SUPABASE_KEY)
allowed, error_msg = rate_limiter.check_limit(
    user_id=user_id,
    subscription_tier='premium',
    max_mods=75
)

if not allowed:
    return 429  # Rate limit exceeded
```

### 3. Increment Usage (After Success)

```python
rate_limiter.increment_usage(user_id, tokens_used=4183)
```

### 4. Auto-Reset

Счётчики автоматически сбрасываются:
- **Daily**: каждый день в 00:00
- **Monthly**: 1 числа каждого месяца

## Custom Limits

Для VIP клиентов можно задать кастомные лимиты:

```sql
UPDATE users
SET custom_limits = '{"daily_requests": 500, "max_mods_per_request": 150}'
WHERE id = 'user-uuid';
```

Кастомные лимиты переопределяют дефолтные для тарифа.

## Changing Limits

Лимиты хранятся в коде (`rate_limiter.py`):

```python
TIER_LIMITS = {
    'premium': {
        'daily_requests': 200,      # Изменить здесь
        'monthly_requests': 5000,
        'max_mods_per_request': 100,
        'ai_token_limit': 500000
    }
}
```

После изменения - просто перезапустить API.

## Error Responses

### 429 Too Many Requests

```json
{
  "error": "Rate limit exceeded",
  "message": "Daily limit reached (50 requests/day). Try again tomorrow."
}
```

### 403 Forbidden

```json
{
  "error": "Forbidden",
  "message": "AI features are not available for free tier. Please upgrade."
}
```

## Monitoring

Счётчики доступны в админке через таблицу `users`:

```sql
SELECT 
  id,
  subscription_tier,
  daily_requests_used,
  monthly_requests_used,
  ai_tokens_used,
  last_request_date
FROM users
WHERE subscription_tier != 'free'
ORDER BY monthly_requests_used DESC
LIMIT 100;
```

## Migration

Чтобы добавить лимиты в существующую БД:

```bash
psql -h your-db-host -U postgres -d your-db -f migrations/001_add_rate_limiting.sql
```

Или через Supabase SQL Editor:
1. Открыть Supabase Dashboard
2. SQL Editor
3. Вставить содержимое `migrations/001_add_rate_limiting.sql`
4. Run

## Testing

```python
# Test rate limiter
from rate_limiter import get_rate_limiter

limiter = get_rate_limiter(SUPABASE_URL, SUPABASE_KEY)

# Check limit
allowed, msg = limiter.check_limit('user-uuid', 'test', max_mods=30)
print(f"Allowed: {allowed}, Message: {msg}")

# Increment
limiter.increment_usage('user-uuid', tokens_used=1000)
```
