"""
Unified Sanitizer
Объединяет и очищает все данные (crash log, game log, board_state) в один структурированный JSON
для отправки в LLM
"""

from typing import Dict, List, Optional
import json
from .board_sanitizer import sanitize_board_state
from .log_sanitizer import sanitize_crash_log, sanitize_game_log, extract_crash_info


def create_unified_crash_data(
    sanitized_crash_log: str,
    board_state: Dict,
    sanitized_game_log: Optional[str] = None,
    extracted_info: Optional[Dict] = None,
    mc_version: Optional[str] = None,
    mod_loader: Optional[str] = None
) -> Dict:
    """
    Создаёт единый структурированный JSON со всеми данными для анализа краша
    
    Принимает уже санитизированные данные и объединяет их в один JSON
    
    Args:
        sanitized_crash_log: Уже санитизированный crash log
        board_state: Полный board_state из лаунчера (будет санитизирован внутри)
        sanitized_game_log: Уже санитизированный game log (опционально)
        extracted_info: Информация, извлечённая из лога (loader, version, exception)
        mc_version: Версия MC (опционально, приоритет над extracted_info)
        mod_loader: Загрузчик (опционально, приоритет над extracted_info)
        
    Returns:
        Dict с очищенными данными в структурированном формате:
        {
            "crash_info": {...},
            "crash_log": "...",
            "mods": [...],
            "game_log": "..."
        }
    """
    
    # Определяем, есть ли crash report или только game log
    has_crash_report = bool(sanitized_crash_log and len(sanitized_crash_log) > 100 and ('Exception' in sanitized_crash_log or 'Crash Report' in sanitized_crash_log))
    
    # Используем переданные или извлечённые версию и loader
    final_mc_version = mc_version or (extracted_info.get('mc_version') if extracted_info else None)
    final_mod_loader = mod_loader or (extracted_info.get('mod_loader', 'fabric') if extracted_info else 'fabric')
    
    # Санитизируем board_state
    sanitized_board = sanitize_board_state(board_state)
    
    # Создаём единую структуру
    unified_data = {
        "crash_info": {
            "mc_version": final_mc_version,
            "mod_loader": final_mod_loader,
            "error_type": extracted_info.get('error_type', 'unknown') if extracted_info else 'unknown',
            "main_exception": extracted_info.get('main_exception') if extracted_info else None,
            "mixin_errors": extracted_info.get('mixin_errors', []) if extracted_info else [],
            "class_not_found_errors": extracted_info.get('class_not_found_errors', []) if extracted_info else [],
            "connector_issues": extracted_info.get('connector_issues', []) if extracted_info else [],
            "has_crash_report": has_crash_report
        },
        "crash_log": sanitized_crash_log[:15000] if sanitized_crash_log else "",  # Ограничиваем размер
        "mods": sanitized_board.get('mods', []),
        "game_log": sanitized_game_log[:5000] if sanitized_game_log else None
    }
    
    return unified_data

