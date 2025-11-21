"""
Log Sanitizer
Очищает crash logs и game logs от шума, PII, повторений
"""

import re
from typing import Dict, List, Tuple
from datetime import datetime


def sanitize_crash_log(crash_log: str, max_length: int = 20000) -> Dict[str, any]:
    """
    Очищает crash log от мусора, извлекает ключевую информацию
    
    Args:
        crash_log: Сырой crash log
        max_length: Максимальная длина после очистки
        
    Returns:
        Dict с очищенным логом и метаданными
    """
    if not crash_log:
        return {
            'sanitized_log': '',
            'extracted_info': {},
            'lines_removed': 0,
            'original_length': 0
        }
    
    original_length = len(crash_log)
    lines = crash_log.split('\n')
    original_lines = len(lines)
    
    # 1. Удаляем PII (пути пользователя) и UUIDs
    sanitized_lines = []
    path_patterns = [
        r'C:\\Users\\[^\\]+',       # Windows C:\Users\...
        r'[A-Z]:\\Users\\[^\\]+',   # Windows user paths
        r'/home/[^/]+',              # Linux home paths
        r'/Users/[^/]+',             # macOS home paths
    ]
    
    for line in lines:
        sanitized_line = line
        for pattern in path_patterns:
            sanitized_line = re.sub(pattern, '[USER_PATH]', sanitized_line, flags=re.IGNORECASE)
        # Удаляем UUIDs и access tokens
        sanitized_line = re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', '[UUID]', sanitized_line, flags=re.IGNORECASE)
        sanitized_line = re.sub(r'--accessToken, [^,\]]+', '--accessToken, [REDACTED]', sanitized_line)
        sanitized_lines.append(sanitized_line)
    
    # 2. СОХРАНЯЕМ ВСЕ ВАЖНЫЕ СЕКЦИИ (любые проблемы, не только dependencies)
    important_keywords = [
        '-- ',  # Все секции с "--" (Mod loading issue, System Details, etc.)
        'Mod loading issue',
        'Failure message',
        'requires',
        'not installed',
        'incompatible',
        'conflict',
        'Minecraft Version',
        'ModLauncher',
        'neoforge',
        'forge',
        'fabric',
        'Missing',
        'mandatory dependencies',
        'Mod List:',
        'Exception',
        'Error',
        'FATAL',
        'WARN',
        'CRASH',
        'Crash Report',
        'Description:',
        'Stacktrace',
        'Caused by',
        'at ',
        'java.lang.',
        'java.util.'
    ]
    
    # 3. Удаляем повторяющиеся сообщения "Cowardly refusing to send event"
    unique_lines = []
    seen_refusing = set()
    
    # 4. Удаляем огромные списки библиотек и модов (оставляем только начало/конец)
    in_mod_list = False
    mod_list_lines = []
    mod_list_start_idx = None
    
    for i, line in enumerate(sanitized_lines):
        # Пропускаем повторяющиеся "Cowardly refusing"
        if 'Cowardly refusing to send event' in line:
            if line not in seen_refusing:
                seen_refusing.add(line)
                continue  # Пропускаем первую, остальные удаляем
        
        # Обнаруживаем начало списка модов
        if 'Mod List:' in line or 'Name Version (Mod Id)' in line:
            in_mod_list = True
            mod_list_start_idx = i
            mod_list_lines = [line]
            unique_lines.append(line)
            continue
        
        # Если в списке модов - сохраняем только первые N и последние M строк
        if in_mod_list:
            mod_list_lines.append(line)
            # Если список закончился (пустая строка после или следующий блок)
            if i < len(sanitized_lines) - 1:
                next_line = sanitized_lines[i + 1]
                if next_line.strip() == '' or '[' in next_line[:10] or '--' in next_line[:5]:
                    # Закончился список, сохраняем только первые 30 и последние 10
                    if len(mod_list_lines) > 40:
                        important_lines = mod_list_lines[:30] + ['... [TRUNCATED: {} mods] ...'.format(len(mod_list_lines) - 40)] + mod_list_lines[-10:]
                        unique_lines.extend(important_lines)
                    else:
                        unique_lines.extend(mod_list_lines)
                    in_mod_list = False
                    mod_list_lines = []
                continue
            else:
                # Конец файла
                if len(mod_list_lines) > 40:
                    important_lines = mod_list_lines[:30] + ['... [TRUNCATED] ...'] + mod_list_lines[-10:]
                    unique_lines.extend(important_lines)
                else:
                    unique_lines.extend(mod_list_lines)
                in_mod_list = False
                continue
        
        # Удаляем DEBUG/TRACE сообщения (слишком много)
        if '[DEBUG]' in line or '[TRACE]' in line:
            continue
        
        # Сохраняем важные строки - либо содержат ключевые слова, либо это секции с "--"
        is_important = any(keyword.lower() in line.lower() for keyword in important_keywords)
        
        # Всегда сохраняем секции (начинаются с "--")
        is_section = line.strip().startswith('--')
        
        # Сохраняем исключения и ошибки
        is_exception = line.strip().startswith('Exception') or line.strip().startswith('Error') or 'Exception' in line
        
        # Сохраняем строки с модами или проблемами
        has_mod_info = 'Mod' in line or 'mod' in line.lower()
        
        if is_important or is_section or is_exception or has_mod_info:
            unique_lines.append(line)
    
    # 3. Извлекаем ключевую информацию
    extracted_info = extract_crash_info('\n'.join(unique_lines))
    
    # 4. Обрезаем до max_length если нужно
    sanitized_log = '\n'.join(unique_lines)
    if len(sanitized_log) > max_length:
        # Берем начало (где обычно ошибка) и конец (где обычно стек)
        head = sanitized_log[:max_length // 2]
        tail = sanitized_log[-max_length // 2:]
        sanitized_log = head + '\n... [TRUNCATED] ...\n' + tail
    
    lines_removed = original_lines - len(sanitized_log.split('\n'))
    
    return {
        'sanitized_log': sanitized_log,
        'extracted_info': extracted_info,
        'lines_removed': lines_removed,
        'original_length': original_length,
        'sanitized_length': len(sanitized_log)
    }


def extract_crash_info(log: str) -> Dict[str, any]:
    """
    Извлекает ключевую информацию из краш-лога или game log
    
    Returns:
        Dict с полями: mod_loader, mc_version, main_exception, conflicting_mods_hints, error_type
    """
    info = {
        'mod_loader': None,
        'mc_version': None,
        'main_exception': None,
        'conflicting_mods_hints': [],
        'error_type': 'unknown',
        'mixin_errors': [],
        'class_not_found_errors': [],
        'connector_issues': []
    }
    
    # Определяем mod loader (приоритет NeoForge, потом Forge, потом Fabric)
    loader_patterns = {
        'neoforge': [r'neoforge', r'neo-forge', r'neoforge', r'ModLauncher.*neoforge'],
        'forge': [r'forge', r'minecraftforge', r'ModLauncher.*forge'],
        'fabric': [r'fabric-loader', r'fabric\s+loader']
    }
    
    log_lower = log.lower()
    for loader, patterns in loader_patterns.items():
        if any(re.search(pattern, log_lower) for pattern in patterns):
            info['mod_loader'] = loader
            break
    
    # Определяем версию MC
    mc_version_match = re.search(r'(\d+\.\d+(?:\.\d+)?)', log)
    if mc_version_match:
        info['mc_version'] = mc_version_match.group(1)
    
    # Находим главное исключение
    exception_patterns = [
        r'Exception in thread[^\n]*:\s*(\w+(?:\.\w+)*)',
        r'Caused by:\s*(\w+(?:\.\w+)*)',
        r'java\.\w+\.(\w+(?:Exception|Error))',
    ]
    
    for pattern in exception_patterns:
        match = re.search(pattern, log)
        if match:
            info['main_exception'] = match.group(1)
            break
    
    # Ищем упоминания модов в ошибках
    mod_hint_pattern = r'([A-Z][a-zA-Z0-9\s]+(?:Mod|API|Lib))'
    matches = re.findall(mod_hint_pattern, log)
    if matches:
        info['conflicting_mods_hints'] = list(set(matches[:10]))
    
    # Ищем mixin ошибки (критично для Connector)
    mixin_error_patterns = [
        r'@Mixin target ([^\s]+) was not found',
        r'Error loading class: ([^\s]+)',
        r'ClassNotFoundException: ([^\s]+)',
        r'NoClassDefFoundError: ([^\s]+)'
    ]
    
    for pattern in mixin_error_patterns:
        matches = re.findall(pattern, log)
        if matches:
            info['mixin_errors'].extend(matches)
            info['class_not_found_errors'].extend(matches)
    
    # Ищем проблемы с Connector
    connector_patterns = [
        r'Skipping jar.*is a Fabric mod and cannot be loaded',
        r'Connector.*bridge',
        r'connectorextras'
    ]
    
    connector_issues = []
    for pattern in connector_patterns:
        matches = re.findall(pattern, log, re.IGNORECASE)
        if matches:
            connector_issues.extend(matches)
    
    if connector_issues:
        info['connector_issues'] = list(set(connector_issues))
    
    # Определяем тип ошибки
    log_lower = log.lower()
    
    # Mixin/Class loading ошибки (критично для Connector)
    if 'mixin' in log_lower and ('target' in log_lower or 'not found' in log_lower):
        info['error_type'] = 'mixin_error'
    elif 'ClassNotFoundException' in log or 'NoClassDefFoundError' in log:
        info['error_type'] = 'class_not_found'
    elif 'is a Fabric mod and cannot be loaded' in log_lower:
        info['error_type'] = 'fabric_mod_on_neoforge'
    elif 'is not installed' in log or 'Missing' in log or 'requires' in log:
        info['error_type'] = 'dependency_or_loading'
    elif 'conflict' in log_lower or 'incompatible' in log_lower:
        info['error_type'] = 'mod_conflict'
    elif 'OutOfMemoryError' in log:
        info['error_type'] = 'memory'
    elif 'IllegalArgumentException' in log or 'NullPointerException' in log or 'RuntimeException' in log:
        info['error_type'] = 'runtime_error'
    else:
        info['error_type'] = 'unknown'
    
    return info


def sanitize_game_log(game_log: str, max_length: int = 10000) -> str:
    """
    Очищает game log (latest.log) - сохраняет важные ошибки и предупреждения
    
    Args:
        game_log: Сырой game log
        max_length: Максимальная длина
        
    Returns:
        Очищенный лог
    """
    if not game_log:
        return ''
    
    lines = game_log.split('\n')
    
    # Удаляем PII (пути)
    sanitized_lines = []
    for line in lines:
        line = re.sub(r'[A-Z]:\\Users\\[^\\]+', '[USER_PATH]', line)
        line = re.sub(r'/home/[^/]+', '[USER_PATH]', line)
        sanitized_lines.append(line)
    
    # Важные ключевые слова для сохранения (ошибки, предупреждения, проблемы)
    important_keywords = [
        'ERROR', 'WARN', 'FATAL', 'CRASH',
        'Exception', 'Error', 'Failed',
        'ClassNotFoundException', 'NoClassDefFoundError',
        'Mixin', '@Mixin', 'target.*was not found',
        'is a Fabric mod and cannot be loaded',
        'Skipping jar',
        'Connector', 'connectorextras',
        'Mod loading issue', 'Failure message',
        'requires', 'not installed', 'Missing',
        'incompatible', 'conflict',
        'ModLauncher', 'Mod List:'
    ]
    
    # Фильтруем важные строки
    important_lines = []
    for line in sanitized_lines:
        line_lower = line.lower()
        # Сохраняем строки с ошибками/предупреждениями
        if any(keyword.lower() in line_lower for keyword in important_keywords):
            important_lines.append(line)
        # Сохраняем строки с модами
        elif 'mod' in line_lower and ('found' in line_lower or 'loading' in line_lower):
            important_lines.append(line)
    
    # Если важных строк мало, берём последние N строк
    if len(important_lines) < 50:
        important_lines = sanitized_lines[-500:]  # Последние 500 строк
    
    sanitized_log = '\n'.join(important_lines)
    
    if len(sanitized_log) > max_length:
        # Берем начало (где обычно ошибки) и конец
        head = sanitized_log[:max_length // 2]
        tail = sanitized_log[-max_length // 2:]
        sanitized_log = head + '\n... [TRUNCATED] ...\n' + tail
    
    return sanitized_log

