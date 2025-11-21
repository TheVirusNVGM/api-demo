"""
Board State Sanitizer
Очищает board_state от ненужных данных перед отправкой в LLM
Оставляет только критичную информацию о модах для анализа краша
"""

from typing import Dict, List, Optional


def sanitize_board_state(board_state: Dict) -> Dict:
    """
    Очищает board_state от ненужных данных для анализа краша
    
    Убирает:
    - camera (позиция камеры)
    - categories (категории с позициями, цветами)
    - project_id (ID проекта)
    - updated_at (время обновления)
    - _ai_generated, _batch_download, _ai_build_id (метаданные)
    - position (x, y) в модах
    - icon_url, file_name, download_url, file_size, sha512 (информация о файлах)
    - unique_id, is_disabled, download_failed, has_version_warning, has_missing_dependencies
    - cached_dependencies, dependencies_fetched
    - category_id, category_index
    - is_incompatible, compatibility_issues
    - author, downloads, follows, categories, client_side, server_side, project_type, license
    - date_created, date_modified, latest_version, game_versions, gallery
    
    Оставляет только:
    - title/name (название мода)
    - slug (slug мода)
    - source_id/project_id (ID мода)
    - description (сокращенное до 100 символов)
    
    Args:
        board_state: Полный board_state из лаунчера
        
    Returns:
        Очищенный board_state с минимальными данными о модах
    """
    
    sanitized = {
        'mods': []
    }
    
    if 'mods' not in board_state:
        return sanitized
    
    for mod in board_state['mods']:
        # Извлекаем только критичные поля для анализа краша
        mod_info = {
            'name': mod.get('title') or mod.get('name', 'Unknown'),
        }
        
        # Slug мода
        slug = mod.get('slug') or mod.get('project_id')
        if slug:
            mod_info['slug'] = slug
        
        # Source ID (project_id)
        source_id = mod.get('source_id') or mod.get('project_id')
        if source_id:
            mod_info['source_id'] = source_id
        
        # Описание (сокращенное до 100 символов)
        description = mod.get('description', '') or mod.get('summary', '')
        if description:
            description_short = description[:100].strip()
            if len(description) > 100:
                # Обрезаем по последнему пробелу чтобы не обрывать слово
                last_space = description_short.rfind(' ')
                if last_space > 50:  # Если есть пробел не слишком близко к началу
                    description_short = description_short[:last_space]
            mod_info['description'] = description_short
        
        sanitized['mods'].append(mod_info)
    
    return sanitized

