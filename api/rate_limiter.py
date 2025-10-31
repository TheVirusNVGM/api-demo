"""
Rate Limiter
Проверяет лимиты использования AI endpoints по тарифам
"""

from datetime import date, datetime
from typing import Optional, Dict, Tuple
import requests


# Лимиты по тарифам (в коде, легко менять)
TIER_LIMITS = {
    'free': {
        'daily_requests': 0,        # Free не может использовать AI вообще
        'monthly_requests': 0,
        'max_mods_per_request': 0,
        'ai_token_limit': 0
    },
    'test': {
        'daily_requests': 50,       # 50 запросов в день
        'monthly_requests': 1000,   # 1000 в месяц
        'max_mods_per_request': 50,
        'ai_token_limit': 100000    # 100k токенов в месяц
    },
    'premium': {
        'daily_requests': 200,      # 200 запросов в день
        'monthly_requests': 5000,   # 5000 в месяц
        'max_mods_per_request': 100,
        'ai_token_limit': 500000    # 500k токенов в месяц
    },
    'pro': {
        'daily_requests': -1,       # Безлимит
        'monthly_requests': -1,
        'max_mods_per_request': 200,
        'ai_token_limit': -1
    }
}


class RateLimiter:
    def __init__(self, supabase_url: str, supabase_key: str):
        self.supabase_url = supabase_url
        self.supabase_key = supabase_key
    
    def get_user_usage(self, user_id: str) -> Optional[Dict]:
        """Получает текущее использование пользователя из БД"""
        try:
            headers = {
                'apikey': self.supabase_key,
                'Authorization': f'Bearer {self.supabase_key}',
                'Content-Type': 'application/json'
            }
            
            response = requests.get(
                f'{self.supabase_url}/rest/v1/users',
                params={
                    'id': f'eq.{user_id}',
                    'select': 'subscription_tier,daily_requests_used,monthly_requests_used,ai_tokens_used,last_request_date,custom_limits'
                },
                headers=headers,
                timeout=5
            )
            
            if response.status_code == 200:
                users = response.json()
                if users and len(users) > 0:
                    return users[0]
            
            return None
        except Exception as e:
            print(f"[Rate Limiter] Error fetching usage: {e}")
            return None
    
    def reset_counters_if_needed(self, user_id: str, user_data: Dict) -> Dict:
        """Сбрасывает счётчики если наступил новый день/месяц"""
        today = date.today()
        last_request = user_data.get('last_request_date')
        
        updates = {}
        
        # Парсим дату из БД (формат ISO: YYYY-MM-DD)
        if last_request:
            try:
                last_date = datetime.fromisoformat(last_request).date()
            except:
                last_date = None
        else:
            last_date = None
        
        # Если новый день - сбрасываем daily
        if not last_date or last_date < today:
            updates['daily_requests_used'] = 0
            updates['last_request_date'] = today.isoformat()
        
        # Если новый месяц - сбрасываем monthly
        if not last_date or (last_date.year, last_date.month) < (today.year, today.month):
            updates['monthly_requests_used'] = 0
            updates['ai_tokens_used'] = 0
        
        # Обновляем БД если есть изменения
        if updates:
            try:
                headers = {
                    'apikey': self.supabase_key,
                    'Authorization': f'Bearer {self.supabase_key}',
                    'Content-Type': 'application/json'
                }
                
                requests.patch(
                    f'{self.supabase_url}/rest/v1/users?id=eq.{user_id}',
                    headers=headers,
                    json=updates,
                    timeout=5
                )
                
                # Обновляем локальные данные
                user_data.update(updates)
            except Exception as e:
                print(f"[Rate Limiter] Error resetting counters: {e}")
        
        return user_data
    
    def check_limit(self, user_id: str, subscription_tier: str, max_mods: int = 0) -> Tuple[bool, Optional[str]]:
        """
        Проверяет лимиты пользователя перед AI запросом
        
        Returns:
            (allowed: bool, error_message: Optional[str])
        """
        # Free tier полностью заблокирован (это уже проверяется в auth.py)
        if subscription_tier == 'free':
            return (False, 'AI features are not available for free tier. Please upgrade.')
        
        # Получаем лимиты для тарифа
        limits = TIER_LIMITS.get(subscription_tier)
        if not limits:
            return (False, f'Unknown subscription tier: {subscription_tier}')
        
        # Получаем usage из БД
        user_data = self.get_user_usage(user_id)
        if not user_data:
            return (False, 'Failed to fetch user data')
        
        # Сбрасываем счётчики если нужно
        user_data = self.reset_counters_if_needed(user_id, user_data)
        
        # Проверяем custom_limits (если есть)
        custom_limits = user_data.get('custom_limits')
        if custom_limits and isinstance(custom_limits, dict):
            limits = {**limits, **custom_limits}
        
        # Проверка 1: Daily limit
        if limits['daily_requests'] != -1:
            daily_used = user_data.get('daily_requests_used', 0)
            if daily_used >= limits['daily_requests']:
                return (False, f"Daily limit reached ({limits['daily_requests']} requests/day). Try again tomorrow.")
        
        # Проверка 2: Monthly limit
        if limits['monthly_requests'] != -1:
            monthly_used = user_data.get('monthly_requests_used', 0)
            if monthly_used >= limits['monthly_requests']:
                return (False, f"Monthly limit reached ({limits['monthly_requests']} requests/month). Upgrade your plan.")
        
        # Проверка 3: Max mods per request
        if limits['max_mods_per_request'] != -1 and max_mods > limits['max_mods_per_request']:
            return (False, f"Too many mods requested. Maximum: {limits['max_mods_per_request']} mods. Your plan: {subscription_tier}")
        
        # Проверка 4: AI tokens (опционально, если отслеживаем)
        if limits['ai_token_limit'] != -1:
            tokens_used = user_data.get('ai_tokens_used', 0)
            if tokens_used >= limits['ai_token_limit']:
                return (False, f"AI token limit reached ({limits['ai_token_limit']} tokens/month). Upgrade your plan.")
        
        # Всё ок
        return (True, None)
    
    def increment_usage(self, user_id: str, tokens_used: int = 0):
        """
        Увеличивает счётчики использования после успешного AI запроса
        
        Args:
            user_id: ID пользователя
            tokens_used: Количество использованных токенов (опционально)
        """
        try:
            headers = {
                'apikey': self.supabase_key,
                'Authorization': f'Bearer {self.supabase_key}',
                'Content-Type': 'application/json'
            }
            
            # Используем PostgREST increment через RPC или просто обновляем
            # Простой способ: читаем текущие значения и инкрементим
            user_data = self.get_user_usage(user_id)
            if not user_data:
                return
            
            updates = {
                'daily_requests_used': (user_data.get('daily_requests_used', 0) or 0) + 1,
                'monthly_requests_used': (user_data.get('monthly_requests_used', 0) or 0) + 1,
                'last_request_date': date.today().isoformat()
            }
            
            if tokens_used > 0:
                updates['ai_tokens_used'] = (user_data.get('ai_tokens_used', 0) or 0) + tokens_used
            
            requests.patch(
                f'{self.supabase_url}/rest/v1/users?id=eq.{user_id}',
                headers=headers,
                json=updates,
                timeout=5
            )
        except Exception as e:
            print(f"[Rate Limiter] Error incrementing usage: {e}")


# Singleton instance
_rate_limiter_instance = None

def get_rate_limiter(supabase_url: str, supabase_key: str) -> RateLimiter:
    """Получить глобальный экземпляр rate limiter"""
    global _rate_limiter_instance
    if _rate_limiter_instance is None:
        _rate_limiter_instance = RateLimiter(supabase_url, supabase_key)
    return _rate_limiter_instance
