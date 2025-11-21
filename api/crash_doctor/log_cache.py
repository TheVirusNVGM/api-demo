"""
Log Cache
Кеш для предотвращения повторной обработки одинаковых логов
"""

import hashlib
import time
from typing import Dict, Optional, Tuple
from threading import Lock


class LogCache:
    """
    In-memory кеш для хранения хешей обработанных логов
    
    Структура:
    {
        'user_id:log_hash': {
            'timestamp': float,
            'user_id': str,
            'log_hash': str,
            'processed': bool
        }
    }
    """
    
    def __init__(self, ttl_seconds: int = 3600):
        """
        Args:
            ttl_seconds: Время жизни записи в секундах (по умолчанию 1 час)
        """
        self.cache: Dict[str, Dict] = {}
        self.lock = Lock()
        self.ttl = ttl_seconds
    
    def _generate_hash(self, crash_log: str, game_log: Optional[str] = None) -> str:
        """
        Генерирует MD5 хеш для логов
        
        Логика определения "одинаковости":
        - Берутся первые 10000 символов crash_log + game_log
        - Это достаточно для уникальной идентификации конкретного краша
        - В начале лога обычно находится основная ошибка и стектрейс
        - Если первые 10к символов совпадают - это тот же краш
        
        Почему первые 10к символов:
        - В начале лога: ошибка, стектрейс, моды, версии - всё важное
        - В конце лога: обычно библиотеки и повторения
        - 10к символов = ~200-300 строк - достаточно для уникальности
        
        Args:
            crash_log: Содержимое crash log
            game_log: Содержимое game log (опционально)
            
        Returns:
            MD5 хеш в виде hex строки (32 символа)
        """
        content = crash_log
        if game_log:
            content += game_log
        
        # Используем первые 10000 символов для хеширования
        # Это достаточно для уникальной идентификации конкретного краша
        # В начале лога обычно находится основная ошибка, стектрейс и моды
        content_sample = content[:10000]
        
        return hashlib.md5(content_sample.encode('utf-8')).hexdigest()
    
    def _cleanup_expired(self):
        """
        Удаляет истёкшие записи из кеша
        
        Вызывается автоматически при каждом check_and_mark()
        Это гарантирует, что кеш не растёт бесконечно
        
        Память на запись:
        - Ключ: ~50 байт (user_id:hash = ~20 + 32 символа хеша)
        - Значение: ~100 байт (timestamp, user_id, hash, processed)
        - Итого: ~150 байт на запись
        
        При 1000 уникальных логов = ~150 KB памяти
        При 10000 уникальных логов = ~1.5 MB памяти
        
        С TTL 1 час и автоматической очисткой - это очень мало!
        """
        current_time = time.time()
        expired_keys = [
            key for key, value in self.cache.items()
            if current_time - value['timestamp'] > self.ttl
        ]
        
        for key in expired_keys:
            del self.cache[key]
    
    def check_and_mark(self, user_id: str, crash_log: str, game_log: Optional[str] = None) -> Tuple[bool, str]:
        """
        Проверяет, был ли этот лог уже успешно обработан
        
        ЗАЧЕМ НУЖЕН user_id:
        - Разные пользователи могут иметь одинаковые крашлоги (например, популярный мод крашит у всех одинаково)
        - Без user_id: если Пользователь A обработал лог → Пользователь B не сможет обработать тот же лог (заблокирован)
        - С user_id: каждый пользователь имеет свой "слот" в кеше → независимая обработка
        
        Пример:
        - Пользователь A: краш от мода X → hash="abc123" → кеш: "user_a:abc123"
        - Пользователь B: тот же краш от мода X → hash="abc123" → кеш: "user_b:abc123" (отдельная запись!)
        - Пользователь A повторно: тот же краш → "user_a:abc123" найден → дубликат ✅
        - Пользователь B повторно: тот же краш → "user_b:abc123" найден → дубликат ✅
        
        БЕЗ user_id (только хеш):
        - Пользователь A: краш → hash="abc123" → кеш: "abc123"
        - Пользователь B: тот же краш → hash="abc123" → кеш: "abc123" УЖЕ ЕСТЬ → блокируется ❌
        - Проблема: Пользователь B не может обработать свой лог!
        
        ВАЖНО: Лог помечается как обработанный только после успешного анализа.
        Если анализ упал с ошибкой, лог НЕ помечается как обработанный и можно повторить попытку.
        
        Args:
            user_id: ID пользователя (из JWT токена, из Supabase)
            crash_log: Содержимое crash log
            game_log: Содержимое game log (опционально)
            
        Returns:
            (is_duplicate: bool, log_hash: str)
            - is_duplicate: True если лог уже УСПЕШНО обрабатывался ЭТИМ пользователем
            - log_hash: MD5 хеш лога
        """
        with self.lock:
            # Очищаем истёкшие записи
            self._cleanup_expired()
            
            # Генерируем хеш
            log_hash = self._generate_hash(crash_log, game_log)
            # Ключ = user_id + хеш → каждый пользователь имеет свой "слот" в кеше
            cache_key = f"{user_id}:{log_hash}"
            
            # Проверяем, есть ли уже запись
            if cache_key in self.cache:
                entry = self.cache[cache_key]
                # Проверяем, не истёк ли TTL
                if time.time() - entry['timestamp'] < self.ttl:
                    # Проверяем, был ли анализ успешным
                    # Если success=False или отсутствует - разрешаем повторную попытку
                    if entry.get('success', False):
                        # Лог уже успешно обрабатывался
                        return (True, log_hash)
                    else:
                        # Предыдущий анализ упал с ошибкой - разрешаем повторную попытку
                        # Удаляем старую запись, чтобы начать заново
                        del self.cache[cache_key]
                else:
                    # Запись истекла, удаляем её
                    del self.cache[cache_key]
            
            # НЕ помечаем как обработанный здесь - это будет сделано после успешного анализа
            # Просто возвращаем False (не дубликат)
            return (False, log_hash)
    
    def mark_as_success(self, user_id: str, log_hash: str):
        """
        Помечает лог как успешно обработанный
        
        Вызывается только после успешного завершения анализа.
        Если анализ упал с ошибкой, этот метод НЕ вызывается.
        
        Args:
            user_id: ID пользователя
            log_hash: MD5 хеш лога
        """
        with self.lock:
            cache_key = f"{user_id}:{log_hash}"
            if cache_key in self.cache:
                # Обновляем запись, помечая как успешную
                self.cache[cache_key]['success'] = True
                self.cache[cache_key]['timestamp'] = time.time()  # Обновляем timestamp
            else:
                # Создаём новую запись
                self.cache[cache_key] = {
                    'timestamp': time.time(),
                    'user_id': user_id,
                    'log_hash': log_hash,
                    'success': True
                }
    
    def get_stats(self) -> Dict:
        """Возвращает статистику кеша"""
        with self.lock:
            self._cleanup_expired()
            return {
                'total_entries': len(self.cache),
                'ttl_seconds': self.ttl
            }


# Глобальный экземпляр кеша
_log_cache_instance: Optional[LogCache] = None


def get_log_cache() -> LogCache:
    """Получить глобальный экземпляр кеша логов"""
    global _log_cache_instance
    if _log_cache_instance is None:
        _log_cache_instance = LogCache(ttl_seconds=3600)  # 1 час TTL
    return _log_cache_instance

