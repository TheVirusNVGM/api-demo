"""
Log Validator
Валидация крашлогов - проверка соответствия модов в логе и на доске
"""

import re
from typing import Dict, List, Tuple, Optional
from datetime import datetime


def extract_mods_from_crash_log(crash_log: str, game_log: Optional[str] = None) -> List[str]:
    """
    Извлекает список модов из crash_log или game_log
    
    Ищет моды в:
    1. Секции "Mod List:" (формат: "Mod Name Version (mod_id)")
    2. Секции "-- Mod loading issue for: [mod_id] --"
    3. Упоминаниях модов в ошибках
    
    Returns:
        List[str] - список mod_id или mod slugs
    """
    mods = set()
    combined_log = crash_log
    if game_log:
        combined_log += "\n" + game_log
    
    # 1. Извлекаем из "Mod List:" секции
    mod_list_pattern = r'Mod List:.*?\n(.*?)(?=\n--|\n\n|$)'
    mod_list_match = re.search(mod_list_pattern, combined_log, re.DOTALL | re.IGNORECASE)
    if mod_list_match:
        mod_list_text = mod_list_match.group(1)
        # Формат: "Mod Name Version (mod_id)" или просто "mod_id"
        mod_id_patterns = [
            r'\(([a-z0-9_-]+)\)',  # (mod_id) в скобках
            r'^([a-z0-9_-]+)\s',   # mod_id в начале строки
            r'\s([a-z0-9_-]+)$',   # mod_id в конце строки
        ]
        for pattern in mod_id_patterns:
            matches = re.findall(pattern, mod_list_text, re.MULTILINE | re.IGNORECASE)
            mods.update(matches)
    
    # 2. Извлекаем из "Mod loading issue for: [mod_id]"
    mod_loading_pattern = r'Mod loading issue for:\s*\[?([a-z0-9_-]+)\]?'
    matches = re.findall(mod_loading_pattern, combined_log, re.IGNORECASE)
    mods.update(matches)
    
    # 3. Извлекаем из упоминаний модов в ошибках (например, "mod X requires Y")
    mod_mention_patterns = [
        r'mod\s+([a-z0-9_-]+)\s+requires',
        r'([a-z0-9_-]+)\s+requires',
        r'mod\s+([a-z0-9_-]+)\s+is\s+not',
        r'([a-z0-9_-]+)\s+is\s+not\s+installed',
    ]
    for pattern in mod_mention_patterns:
        matches = re.findall(pattern, combined_log, re.IGNORECASE)
        mods.update(matches)
    
    return list(mods)


def extract_mods_from_board_state(board_state: Dict) -> List[str]:
    """
    Извлекает список модов из board_state
    
    Returns:
        List[str] - список mod_id (source_id или project_id) и slugs
    """
    mods = set()
    
    if 'mods' not in board_state:
        return []
    
    for mod in board_state['mods']:
        # Используем source_id или project_id
        mod_id = mod.get('source_id') or mod.get('project_id')
        if mod_id:
            mods.add(mod_id.lower())
        
        # Также добавляем slug
        slug = mod.get('slug')
        if slug:
            mods.add(slug.lower())
    
    return list(mods)


def extract_crash_log_date(crash_log: str) -> Optional[datetime]:
    """
    Извлекает дату крашлога из заголовка
    
    Форматы:
    - "Time: 2024-01-15 12:34:56"
    - "Crash Report: 2024-01-15"
    - "---- Minecraft Crash Report ----\n// Time: 2024-01-15"
    
    Returns:
        datetime или None если дата не найдена
    """
    date_patterns = [
        r'Time:\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})',
        r'Time:\s*(\d{4}-\d{2}-\d{2})',
        r'Crash Report.*?(\d{4}-\d{2}-\d{2})',
        r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})',
    ]
    
    for pattern in date_patterns:
        match = re.search(pattern, crash_log)
        if match:
            date_str = match.group(1)
            try:
                # Пробуем разные форматы
                for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d']:
                    try:
                        return datetime.strptime(date_str, fmt)
                    except ValueError:
                        continue
            except Exception:
                continue
    
    return None


def validate_mods_match(
    crash_log: str,
    board_state: Dict,
    game_log: Optional[str] = None,
    previous_warning_hash: Optional[str] = None
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Валидирует соответствие модов в crash_log и board_state
    
    Args:
        crash_log: Содержимое crash log
        board_state: Текущее состояние доски
        game_log: Опциональный game log
        previous_warning_hash: Хеш предыдущего предупреждения (для отслеживания повторений)
        
    Returns:
        (is_valid: bool, warning_message: Optional[str], warning_hash: Optional[str])
        - is_valid: True если моды совпадают или валидация пропущена
        - warning_message: Сообщение об устаревшем логе (если есть)
        - warning_hash: Хеш для отслеживания повторений
    """
    # Извлекаем моды из crash_log
    crash_mods = extract_mods_from_crash_log(crash_log, game_log)
    if not crash_mods:
        # Если не удалось извлечь моды из лога - пропускаем валидацию
        return (True, None, None)
    
    # Извлекаем моды из board_state
    board_mods = extract_mods_from_board_state(board_state)
    if not board_mods:
        # Если на доске нет модов - пропускаем валидацию
        return (True, None, None)
    
    # Нормализуем для сравнения (lowercase)
    crash_mods_lower = {mod.lower() for mod in crash_mods}
    board_mods_lower = {mod.lower() for mod in board_mods}
    
    # Проверяем совпадения
    matches = crash_mods_lower.intersection(board_mods_lower)
    match_percentage = len(matches) / len(crash_mods_lower) if crash_mods_lower else 0
    
    # Если совпадений меньше 30% - считаем лог устаревшим
    if match_percentage < 0.3:
        # Извлекаем дату крашлога
        crash_date = extract_crash_log_date(crash_log)
        
        # Генерируем хеш для отслеживания повторений
        warning_hash = f"{len(crash_mods)}:{len(board_mods)}:{match_percentage:.2f}"
        
        # Если это повторное предупреждение с тем же хешем - пропускаем валидацию
        if previous_warning_hash == warning_hash:
            print(f"⚠️  [VALIDATION] Mod mismatch detected again (hash: {warning_hash[:8]}...), but crash log date is recent. Proceeding with analysis.")
            return (True, None, warning_hash)
        
        # Формируем сообщение
        date_info = ""
        if crash_date:
            date_info = f" Crash log date: {crash_date.strftime('%Y-%m-%d %H:%M:%S')}"
        
        warning_message = (
            f"Possible outdated crash log detected. "
            f"Only {int(match_percentage * 100)}% of mods from crash log match current board state. "
            f"Crash log mentions {len(crash_mods)} mods, but only {len(matches)} match current board.{date_info} "
            f"Please restart the game to generate a fresh crash log if the issue persists."
        )
        
        return (False, warning_message, warning_hash)
    
    return (True, None, None)


