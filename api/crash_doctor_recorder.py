"""
Crash Doctor Recorder
Сохраняет каждую сессию анализа крашлогов в БД для базы решений
"""

import requests
import json
from typing import Dict, List, Optional
from datetime import datetime


def save_crash_doctor_session(
    user_id: str,
    crash_log: str,
    game_log: Optional[str],
    mc_version: Optional[str],
    mod_loader: Optional[str],
    root_cause: str,
    confidence: float,
    suggestions: List[Dict],
    warnings: List[str],
    board_state: Dict,
    supabase_url: str,
    supabase_key: str
) -> Optional[str]:
    """
    Сохраняет сессию Crash Doctor в БД
    
    Args:
        user_id: ID пользователя
        crash_log: Полный текст крашлога
        game_log: Текст game log (latest.log) если есть
        mc_version: Версия Minecraft
        mod_loader: Загрузчик модов (neoforge/forge/fabric)
        root_cause: Причина краша от ИИ
        confidence: Уверенность ИИ (0.0-1.0)
        suggestions: Список решений от ИИ
        warnings: Предупреждения
        board_state: Состояние доски на момент анализа
        supabase_url: URL Supabase
        supabase_key: Ключ Supabase
    
    Returns:
        ID созданной записи (строка с ведущими нулями, например "0000001") или None при ошибке
    """
    
    headers = {
        'apikey': supabase_key,
        'Authorization': f'Bearer {supabase_key}',
        'Content-Type': 'application/json',
        'Prefer': 'return=representation'  # Вернуть созданную запись
    }
    
    # Подготавливаем данные для сохранения
    data = {
        'user_id': user_id,
        'crash_log': crash_log,
        'game_log': game_log if game_log else None,
        'mc_version': mc_version,
        'mod_loader': mod_loader,
        'root_cause': root_cause,
        'confidence': confidence,
        'suggestions': suggestions,  # Уже JSON array (не нужен dumps - Supabase ждёт объект)
        'warnings': warnings if warnings else [],  # Уже JSON array
        'board_state': board_state,  # Уже JSON object
        # created_at не нужен - Supabase сам установит DEFAULT now()
    }
    
    try:
        url = f"{supabase_url}/rest/v1/crash_doctor_sessions"
        response = requests.post(url, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        session_id = result[0]['id'] if isinstance(result, list) else result['id']
        
        # Форматируем ID с ведущими нулями (7 цифр, как в других таблицах)
        formatted_id = str(session_id).zfill(7)
        
        print(f"📝 [Crash Doctor Recorder] Saved session: {formatted_id}")
        return formatted_id
        
    except Exception as e:
        print(f"⚠️  [Crash Doctor Recorder] Failed to save: {e}")
        import traceback
        traceback.print_exc()
        return None


