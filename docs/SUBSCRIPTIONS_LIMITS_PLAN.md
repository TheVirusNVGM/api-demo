## Subscriptions & Usage Limits — Integration Plan (based on current code)

### Контекст (что уже есть в коде)
- `api/auth.py`:
  - `verify_supabase_token` — проверка Supabase JWT через `/auth/v1/user`.
  - `check_subscription_tier`/`require_subscription` — запрещает `free`, кладёт `g.user_id` и `g.subscription_tier`.
- `api/rate_limiter.py`:
  - `TIER_LIMITS` в коде: daily/monthly/max_mods/ai_token_limit для `free/test/premium/pro`.
  - Использует поля таблицы `users`: `daily_requests_used`, `monthly_requests_used`, `ai_tokens_used`, `last_request_date`, `custom_limits`.
  - `check_limit(...)` — проверка лимитов с автосбросом на новый день/месяц (UTC). 
  - `increment_usage(...)` — инкремент счётчиков после успешного запроса.
- `api/index.py` (эндпоинты):
  - `POST /api/ai/build-board` — защищён `@require_subscription`, выполняет `rate_limiter.check_limit(...)` и после успеха делает `increment_usage(...)` (передаёт `tokens_used` из пайплайна, если есть).
  - `POST /api/ai/auto-sort` — защищён `@require_subscription`, НО пока без `check_limit(...)` и без `increment_usage(...)` (токены собирает для логов).
  - `POST /api/ai/build` — публичный (без авторизации и лимитов) — используется как legacy/simple API.
  - `GET  /api/ai/usage` — авторизованный, возвращает лимиты/остатки для текущего пользователя.

Вывод: базовая модель тарифов и счётчиков уже реализована; надо добить включение лимитирования для всех «дорогих» эндпоинтов и зафиксировать политику.

### Цели
- Единая политика доступа по тарифам: `free` — запрет; `test/premium/pro` — доступ.
- Прозрачные лимиты (daily/monthly, max_mods_per_request, ai_tokens/month) с уведомлениями 429.
- Согласованная работа окон (UTC), предсказуемый сброс.
- Минимальные изменения кода — используем уже написанные декораторы/лимитер.

### Политика и метрики
- Метрики списаний:
  - 1 запрос = 1 списание daily и monthly.
  - `tokens_used` (если есть из пайплайна) — суммируем в `ai_tokens_used`.
- Окна:
  - День/месяц в UTC; автосброс уже реализован в `reset_counters_if_needed`.
- Отказы:
  - 401 — нет/битый JWT.
  - 403 — тариф недостаточен (вкл. `free`).
  - 429 — превышен лимит; возвращаем `message` с причиной.

### План интеграции (без кода, по шагам)
1) Auto-Sort: включить лимитер
   - В начале `POST /api/ai/auto-sort` вызвать `check_limit(g.user_id, g.subscription_tier, max_mods=...)`.
   - После успешного завершения — `increment_usage(g.user_id, tokens_used=<сумма этапов tagging+categorization>)`.

2) Решить статус `POST /api/ai/build`
   - Вариант A (рекомендуется): защитить `@require_subscription` + `check_limit(...)` + `increment_usage(...)` как у `build-board`.
   - Вариант B: оставить публичным, но он тогда должен быть «урезанным» (без AI, без векторки) или прикрыт внешним rate limit по IP/CF. Иначе это обход тарифов.

3) Согласовать лимиты в `TIER_LIMITS`
   - Подтвердить целевые значения для `daily_requests`, `monthly_requests`, `max_mods_per_request`, `ai_token_limit`.
   - Зафиксировать поведение при `-1` (безлимит) — уже реализовано корректно.

4) Стабилизировать учёт токенов
   - `build-board` уже передаёт `tokens_used` из `result['_pipeline']['total_tokens']` (если поле есть).
   - Для `auto-sort` суммировать токены из обоих этапов и передавать в `increment_usage`.
   - Для `build` (если будет защищён) — аналогично, иначе пропустить учёт.

5) Ответы клиенту (контракт)
   - На 429 возвращать: `{ error: 'Rate limit exceeded', message: '<чёткая причина>' }` — уже так делается в `build-board`.
   - `GET /api/ai/usage` — уже возвращает `remaining`, `reset_at`, `unlimited`. Оставить как основной источник для UI лаунчера.

6) Админ и переопределения
   - `users.custom_limits` (JSON) уже поддерживается — перезаписывает лимиты тарифа на пользователя; использовать для ручных апгрейдов/партнёров.
   - Смена `subscription_tier` в `users` — эффект мгновенно; отдельной миграции не требуется.

7) Производительность и кэш
   - (Опционально) кэшировать `subscription_tier` в памяти на 30–60 сек на инстанс, чтобы снизить чтения из БД; при 429 не кэшировать.
   - Лимиты/инкременты — оставляем через PostgREST (как сейчас). Для высокой конкуренции можно позже вынести в RPC для атомарности.

### Риски и улучшения (бэклог)
- Гонки инкрементов при высоком RPS: низкий риск сейчас. Улучшение — сделать RPC `check_and_increment` в Supabase для атомности при большой нагрузке.
- `POST /api/ai/build` как публичная точка — окно обхода тарифов. Рекомендуется защитить или ограничить функционал.
- Идемпотентность: позже добавить `request_id` для предотвращения двойных списаний на ретраях.

### Критерии приёмки
- `free` не может вызвать `build-board` и `auto-sort` (403).
- На `build-board` и `auto-sort` при исчерпании квоты — 429 с понятной причиной.
- `GET /api/ai/usage` корректно отражает `daily_limit`, `used_today`, `remaining`, `reset_at`.
- Счётчики у пользователя растут на 1 за каждый успешный вызов; `ai_tokens_used` растёт на величину токенов, если они доступны.

### Итоговая картина по эндпоинтам
- `POST /api/ai/build-board`: защита + лимитер + инкремент — ГОТОВО.
- `POST /api/ai/auto-sort`: добавить лимитер + инкремент — СДЕЛАТЬ.
- `POST /api/ai/build`: определить политику (A — защитить и включить лимиты, B — оставить публичным с ограничениями) — РЕШИТЬ.
- `GET /api/ai/usage`: оставить как есть для UI лаунчера.

Если ок — дальше можно перейти к маленьким точечным правкам в двух местах (`auto-sort` лимитер и инкремент; решение по `build`).


