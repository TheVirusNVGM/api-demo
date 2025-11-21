"""
Authentication and Authorization Module
Проверка JWT токенов через Supabase Auth и subscription tiers для защиты AI endpoints
"""

import requests
from typing import Optional
from functools import wraps
from flask import request, jsonify, g
import os
import sys

# Импорт config с правильным путём
sys.path.insert(0, os.path.dirname(__file__))
from config import SUPABASE_URL, SUPABASE_KEY


def verify_supabase_token(token: str) -> Optional[dict]:
    """
    Проверяет JWT токен через Supabase Auth API
    
    Args:
        token: Supabase JWT токен (формат xxx.yyy.zzz)
        
    Returns:
        Dict с user_id ('id') и другими данными пользователя, или None если невалидный
    """
    try:
        # Проверяем что это JWT (3 части через точку)
        if token.count('.') != 2:
            print(f"[WARNING] [Auth] Invalid token format - expected JWT (xxx.yyy.zzz)")
            return None
        
        token_preview = token[:30] + "..." if len(token) > 30 else token
        print(f"[Auth] Verifying JWT token (preview: {token_preview})")
        
        # Проверяем JWT токен через Supabase Auth API
        url = f'{SUPABASE_URL}/auth/v1/user'
        headers = {
            'Authorization': f'Bearer {token}',
            'apikey': SUPABASE_KEY,
            'Content-Type': 'application/json'
        }
        
        response = requests.get(url, headers=headers, timeout=5)
        
        if response.status_code == 200:
            user_data = response.json()
            user_id = user_data.get('id')
            
            if user_id:
                print(f"[OK] [Auth] JWT token verified, user_id: {user_id}")
                return {
                    'id': user_id,
                    'sub': user_id,  # Для совместимости
                    'user_id': user_id,
                    **user_data
                }
            else:
                print(f"[WARNING] [Auth] Supabase returned user data without 'id' field")
                print(f"[WARNING] [Auth] Response: {user_data}")
                return None
        
        elif response.status_code == 401:
            print(f"[WARNING] [Auth] Invalid or expired token (401)")
            try:
                error_data = response.json()
                print(f"[WARNING] [Auth] Error details: {error_data}")
            except:
                pass
            return None
        
        else:
            print(f"[WARNING] [Auth] Supabase Auth API error: {response.status_code}")
            print(f"[WARNING] [Auth] Response: {response.text[:200]}")
            return None
            
    except requests.exceptions.ConnectionError as e:
        print(f"[ERROR] [Auth] Connection error to Supabase: {e}")
        return None
    except requests.exceptions.Timeout as e:
        print(f"[ERROR] [Auth] Timeout accessing Supabase Auth: {e}")
        return None
    except Exception as e:
        print(f"[ERROR] [Auth] Exception verifying token: {e}")
        import traceback
        traceback.print_exc()
        return None


def get_user_subscription_tier(user_id: str) -> Optional[str]:
    """
    Получает subscription_tier пользователя из БД
    
    Args:
        user_id: UUID пользователя
        
    Returns:
        subscription_tier ('free', 'test', 'premium', 'pro') или None
    """
    try:
        headers = {
            'apikey': SUPABASE_KEY,
            'Authorization': f'Bearer {SUPABASE_KEY}',
            'Content-Type': 'application/json'
        }
        
        url = f'{SUPABASE_URL}/rest/v1/users'
        params = {'id': f'eq.{user_id}', 'select': 'id,subscription_tier'}
        
        response = requests.get(url, params=params, headers=headers, timeout=5)
        
        if response.status_code == 200:
            users = response.json()
            if users and len(users) > 0:
                tier = users[0].get('subscription_tier')
                return tier
            else:
                print(f"[WARNING] [Auth] User {user_id} not found in users table")
        else:
            print(f"[ERROR] [Auth] API error: {response.status_code}")
            print(f"[ERROR] [Auth] Response: {response.text[:200]}")
        
        return None
    except Exception as e:
        print(f"[ERROR] [Auth] Exception in get_user_subscription_tier: {e}")
        import traceback
        traceback.print_exc()
        return None


def check_subscription_tier(required_tier: str = None):
    """
    Decorator для проверки subscription tier
    
    Args:
        required_tier: Минимальный required tier ('test', 'premium', 'pro')
                      Если None, проверяет что НЕ 'free'
    
    Usage:
        @check_subscription_tier()
        def my_endpoint():
            ...
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            print(f"\n[REQUIRE_SUBSCRIPTION] {request.method} {request.path}")
            print(f"   Authorization header: {'Present' if request.headers.get('Authorization') else 'Missing'}")
            try:
                # 1. Извлекаем токен из заголовка
                auth_header = request.headers.get('Authorization', '')
                if not auth_header.startswith('Bearer '):
                    print(f"[WARNING] [Auth] Missing or invalid Authorization header")
                    return jsonify({
                        'error': 'Unauthorized',
                        'message': 'Authentication token required. Please include Authorization: Bearer <token> header.'
                    }), 401
                
                token = auth_header.replace('Bearer ', '').strip()
                if not token:
                    print(f"[WARNING] [Auth] Empty token")
                    return jsonify({
                        'error': 'Unauthorized',
                        'message': 'Invalid token format'
                    }), 401
                
                # 2. Проверяем JWT токен через Supabase Auth API
                user_data = verify_supabase_token(token)
                
                if not user_data:
                    return jsonify({
                        'error': 'Unauthorized',
                        'message': 'Invalid or expired token. Please re-authenticate.'
                    }), 401
                
                # 3. Получаем user_id из проверенного токена
                user_id = user_data.get('id') or user_data.get('sub') or user_data.get('user_id')
                if not user_id:
                    return jsonify({
                        'error': 'Unauthorized',
                        'message': 'Token missing user ID'
                    }), 401
                
                # 4. Проверяем subscription_tier в БД (НИКОГДА НЕ ДОВЕРЯЕМ КЛИЕНТУ!)
                subscription_tier = get_user_subscription_tier(user_id)
                
                if not subscription_tier:
                    # Пользователь не найден в БД или subscription_tier не установлен
                    print(f"[WARNING] [Auth] User {user_id} not found in users table or subscription_tier is None")
                    return jsonify({
                        'error': 'Unauthorized',
                        'message': 'User subscription tier not found. Please contact support.'
                    }), 401
                
                # 5. БЛОКИРУЕМ FREE пользователей (ГЛАВНАЯ ЗАЩИТА!)
                if subscription_tier == 'free':
                    print(f"[BLOCKED] [Auth] BLOCKED free user {user_id} from AI endpoint {request.path}")
                    return jsonify({
                        'error': 'Forbidden',
                        'message': 'AI features are not available for free tier. Please upgrade to test, premium, or pro subscription.'
                    }), 403
                
                # Логируем успешный доступ
                print(f"[OK] [Auth] Allowed {subscription_tier} user {user_id} to {request.path}")
                
                # 6. Проверяем required_tier (если указан)
                if required_tier:
                    tier_hierarchy = {'free': 0, 'test': 1, 'premium': 2, 'pro': 3}
                    user_tier_level = tier_hierarchy.get(subscription_tier, 0)
                    required_tier_level = tier_hierarchy.get(required_tier, 0)
                    
                    if user_tier_level < required_tier_level:
                        return jsonify({
                            'error': 'Forbidden',
                            'message': f'This feature requires {required_tier} tier or higher. Your current tier: {subscription_tier}'
                        }), 403
                
                # 7. Сохраняем данные в Flask g для использования в endpoint
                g.user_id = user_id
                g.subscription_tier = subscription_tier
                
                # 8. Разрешаем доступ
                return f(*args, **kwargs)
            
            except Exception as e:
                # Ловим все исключения в auth и возвращаем JSON error
                import traceback
                error_msg = f"[ERROR] [Auth] Exception in auth decorator: {e}"
                print(error_msg, flush=True)
                traceback.print_exc()
                return jsonify({
                    'error': 'Internal Server Error',
                    'message': f'Authentication error: {str(e)}'
                }), 500
        
        return decorated_function
    return decorator


def require_subscription(f):
    """
    Упрощённый decorator для проверки что пользователь НЕ free
    
    Usage:
        @require_subscription
        def my_endpoint():
            ...
    """
    return check_subscription_tier()(f)
