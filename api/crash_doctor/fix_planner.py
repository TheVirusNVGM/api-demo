"""
Fix Planner
Планирует последовательность фиксов на основе анализа краша
"""

from typing import Dict, List, Optional
import requests
import json


def plan_fixes(analysis: Dict, board_state: Dict, mc_version: Optional[str] = None, mod_loader: Optional[str] = None, extracted_info: Optional[Dict] = None) -> Dict:
    """
    Создаёт план исправлений на основе анализа
    
    Args:
        analysis: Результат analyze_crash()
        board_state: Текущее состояние доски
        mc_version: Версия MC (опционально)
        mod_loader: Загрузчик модов (опционально)
        extracted_info: Извлечённая информация из лога (опционально)
        
    Returns:
        Dict с планом фиксов: operations[], warnings[], estimated_success_probability
    """
    
    operations = []
    warnings = []
    seen_operations = set()  # Для отслеживания дубликатов
    
    # Приоритизируем фиксы: сначала critical, потом high, medium, low
    suggested_fixes = analysis.get('suggested_fixes', [])
    sorted_fixes = sorted(
        suggested_fixes,
        key=lambda x: {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}.get(x.get('priority', 'medium'), 2)
    )
    
    for fix in sorted_fixes:
        action = fix.get('action')
        target_mod = fix.get('target_mod', '').lower().strip()
        reason = fix.get('reason', '')
        priority = fix.get('priority', 'medium')
        
        # Пропускаем некорректные действия
        if not action or not target_mod or target_mod == '.connector':
            # .connector обрабатывается отдельно
            if action == 'clear_connector_cache':
                continue  # Пропускаем, добавим позже автоматически
            warnings.append(f"Invalid fix suggestion: action={action}, target={target_mod}")
            continue
        
        # Создаём уникальный ключ для проверки дубликатов
        operation_key = (action, target_mod)
        if operation_key in seen_operations:
            continue  # Пропускаем дубликат
        seen_operations.add(operation_key)
        
        operation = {
            'action': action,
            'target_mod': target_mod,
            'reason': reason,
            'priority': priority,
            'confidence': analysis.get('confidence', 0.5)
        }
        
        # Валидация в зависимости от типа действия
        mod_info = find_mod_in_board_state(target_mod, board_state)
        
        if action in ['remove_mod', 'disable_mod']:
            # Для удаления/отключения мод должен быть на доске
            if mod_info:
                operation['mod_slug'] = mod_info.get('slug')
                operation['mod_source_id'] = mod_info.get('source_id') or mod_info.get('project_id')
                operations.append(operation)
            else:
                warnings.append(f"Cannot {action} '{target_mod}': mod not found on board")
        
        elif action == 'add_mod':
            # Для добавления проверяем существование мода на Modrinth
            modrinth_info = find_mod_on_modrinth(target_mod, mc_version, mod_loader)
            if modrinth_info:
                operation['mod_source_id'] = modrinth_info.get('project_id')
                operation['mod_slug'] = modrinth_info.get('slug')
                operation['target_mod'] = modrinth_info.get('title', target_mod)
                operations.append(operation)
            else:
                warnings.append(f"Cannot add mod '{target_mod}': mod not found on Modrinth or not compatible")
        
        elif action in ['update_mod', 'change_version']:
            # Для обновления мод должен быть на доске И должна существовать новая версия
            if mod_info:
                operation['mod_slug'] = mod_info.get('slug')
                operation['mod_source_id'] = mod_info.get('source_id') or mod_info.get('project_id')
                
                # Проверяем наличие обновления через Modrinth API
                project_id = operation['mod_source_id']
                if project_id:
                    update_info = check_mod_update_available(project_id, mc_version, mod_loader)
                    if update_info:
                        operation['update_available'] = True
                        operation['latest_version'] = update_info.get('version_number')
                        operation['latest_filename'] = update_info.get('file_name')
                        operation['file_url'] = update_info.get('file_url')
                        operations.append(operation)
                    else:
                        warnings.append(f"No update available for '{target_mod}' (project_id: {project_id})")
                else:
                    warnings.append(f"Cannot check for updates for '{target_mod}': missing project_id")
            else:
                warnings.append(f"Cannot {action} '{target_mod}': mod not found on board")
        
        elif action == 'replace_mod':
            # Replace не реализован - пропускаем
            warnings.append(f"Action 'replace_mod' is not implemented. Suggest 'remove_mod' instead for '{target_mod}'")
            continue
        
        elif action == 'enable_fabric_compat':
            # Это действие всегда валидно
            operations.append(operation)
        
        else:
            # Неизвестное действие - пропускаем
            warnings.append(f"Unknown action '{action}' for mod '{target_mod}'")
    
    # Автоматически добавляем очистку кэша Connector при обнаружении Connector ошибок
    error_category = analysis.get('error_category', 'unknown')
    connector_issues = extracted_info.get('connector_issues', []) if extracted_info else []
    mixin_errors = extracted_info.get('mixin_errors', []) if extracted_info else []
    
    # Проверяем наличие Connector ошибок
    has_connector_errors = (
        error_category in ['mixin_error', 'class_not_found', 'fabric_mod_on_neoforge'] or
        len(connector_issues) > 0 or
        len(mixin_errors) > 0 or
        'connector' in str(analysis.get('root_cause', '')).lower() or
        'mixin' in str(analysis.get('root_cause', '')).lower()
    )
    
    if has_connector_errors:
        operation_key = ('clear_connector_cache', '.connector')
        if operation_key not in seen_operations:
            seen_operations.add(operation_key)
            operations.append({
                'action': 'clear_connector_cache',
                'target_mod': '.connector',
                'reason': 'Clear Connector cache to reset mixin transformations and class mappings. This helps diagnose if the issue is corrupted cache or actual mod incompatibility.',
                'priority': 'high',
                'confidence': 0.7
            })
    
    # Добавляем предупреждения о missing dependencies (только если их ещё нет И мод существует)
    missing_deps = analysis.get('missing_dependencies', [])
    for dep in missing_deps:
        if dep.get('priority') == 'critical':
            dep_mod_name = dep.get('mod_name', '').lower().strip()
            dep_mod_id = dep.get('mod_id', '').strip()  # Может быть slug или project_id
            
            # ВАЛИДАЦИЯ: Проверяем существование мода на Modrinth ПЕРЕД добавлением
            mod_info = find_mod_on_modrinth(dep_mod_id or dep_mod_name, mc_version, mod_loader)
            
            if not mod_info:
                warnings.append(f"Cannot add missing dependency '{dep_mod_name}': mod not found on Modrinth or not compatible")
                continue
            
            operation_key = ('add_mod', dep_mod_name)
            if operation_key not in seen_operations:
                seen_operations.add(operation_key)
                
                operation = {
                    'action': 'add_mod',
                    'target_mod': mod_info.get('title', dep_mod_name),  # Используем правильное название
                    'reason': dep.get('reason', 'Required dependency'),
                    'priority': 'critical',
                    'confidence': 0.8,  # Высокая уверенность для missing dependencies
                    'mod_source_id': mod_info.get('project_id'),
                    'mod_slug': mod_info.get('slug')
                }
                
                operations.append(operation)
    
    # ДЕДУПЛИКАЦИЯ: Убираем противоречивые операции (remove_mod + add_mod для одного мода)
    # ВАЖНО: Проверяем project_id, а не только имя мода!
    # Если на доске есть мод с одним project_id (например, Fabric версия), а добавляется мод с другим project_id (NeoForge версия),
    # то обе операции нужны - это разные моды!
    operations_to_remove = []
    
    # Собираем информацию о модах, которые нужно добавить (по имени и project_id)
    mods_to_add = {}  # {mod_name_lower: {'project_id': ..., 'op_index': ...}}
    for i, op in enumerate(operations):
        if op.get('action') == 'add_mod':
            mod_name = op.get('target_mod', '').lower().strip()
            project_id = op.get('mod_source_id')
            if mod_name:
                mods_to_add[mod_name] = {
                    'project_id': project_id,
                    'op_index': i
                }
    
    # Проверяем remove_mod операции
    for i, op in enumerate(operations):
        if op.get('action') in ['remove_mod', 'disable_mod']:
            mod_name = op.get('target_mod', '').lower().strip()
            mod_on_board = find_mod_in_board_state(mod_name, board_state)
            remove_project_id = op.get('mod_source_id') or (mod_on_board.get('source_id') if mod_on_board else None) or (mod_on_board.get('project_id') if mod_on_board else None)
            
            # Проверяем, есть ли add_mod для этого мода
            if mod_name in mods_to_add:
                add_info = mods_to_add[mod_name]
                add_project_id = add_info.get('project_id')
                
                # Если project_id совпадают или оба None - это один и тот же мод, удаляем remove_mod
                # Если project_id разные - это разные моды (например, Fabric vs NeoForge), обе операции нужны
                if remove_project_id and add_project_id and remove_project_id == add_project_id:
                    # Один и тот же мод - удаляем remove_mod
                    operations_to_remove.append(i)
                    warnings.append(f"Removed redundant '{op.get('action')}' for '{mod_name}' - same mod (project_id: {remove_project_id}), only 'add_mod' needed")
                elif not remove_project_id and not add_project_id:
                    # Оба project_id неизвестны, но имя совпадает - вероятно один мод
                    operations_to_remove.append(i)
                    warnings.append(f"Removed redundant '{op.get('action')}' for '{mod_name}' - mod is not installed according to crash log, only 'add_mod' needed")
                # Если project_id разные - оставляем обе операции (это замена мода на другую версию)
    
    # Удаляем операции в обратном порядке, чтобы не сбить индексы
    for i in reversed(operations_to_remove):
        operations.pop(i)
    
    # Оценка вероятности успеха
    confidence = analysis.get('confidence', 0.5)
    num_critical_fixes = len([op for op in operations if op.get('priority') == 'critical'])
    
    if num_critical_fixes > 0 and confidence > 0.7:
        estimated_success = 0.8
    elif confidence > 0.6:
        estimated_success = 0.6
    else:
        estimated_success = 0.4
    
    return {
        'operations': operations,
        'warnings': warnings,
        'estimated_success_probability': estimated_success,
        'total_fixes': len(operations),
        'root_cause': analysis.get('root_cause', 'Unknown'),
        'error_category': analysis.get('error_category', 'unknown')
    }


def find_mod_in_board_state(mod_identifier: str, board_state: Dict) -> Dict:
    """
    Находит мод в board_state по имени, slug или source_id
    
    Args:
        mod_identifier: Имя мода, slug или source_id
        board_state: Состояние доски
        
    Returns:
        Dict с информацией о моде или None
    """
    if 'mods' not in board_state:
        return None
    
    identifier_lower = mod_identifier.lower()
    
    for mod in board_state['mods']:
        # Проверяем по title/name
        mod_title = (mod.get('title') or mod.get('name', '')).lower()
        if identifier_lower in mod_title or mod_title in identifier_lower:
            return mod
        
        # Проверяем по slug
        mod_slug = (mod.get('slug') or '').lower()
        if identifier_lower in mod_slug:
            return mod
        
        # Проверяем по source_id/project_id
        mod_id = (mod.get('source_id') or mod.get('project_id') or '').lower()
        if identifier_lower == mod_id:
            return mod
    
    return None


def check_mod_update_available(project_id: str, mc_version: Optional[str] = None, mod_loader: Optional[str] = None) -> Optional[Dict]:
    """
    Проверяет наличие обновления для мода через Modrinth API
    
    Args:
        project_id: Modrinth project_id мода
        mc_version: Версия Minecraft (опционально, для фильтрации)
        mod_loader: Загрузчик модов (опционально, для фильтрации)
        
    Returns:
        Dict с информацией о последней версии (version_number, file_name, file_url) или None
    """
    if not project_id:
        return None
    
    try:
        url = f'https://api.modrinth.com/v2/project/{project_id}/version'
        params = []
        
        # Modrinth API ожидает JSON массивы как строки в query параметрах
        if mc_version:
            params.append(('game_versions', f'["{mc_version}"]'))
        if mod_loader:
            params.append(('loaders', f'["{mod_loader.lower()}"]'))
        
        response = requests.get(
            url,
            params=params,
            headers={'User-Agent': 'Astral-AI-API/1.0'},
            timeout=5
        )
        
        if response.status_code == 200:
            versions = response.json()
            if versions and len(versions) > 0:
                # Берём первую версию (самую новую)
                latest = versions[0]
                files = latest.get('files', [])
                if files and len(files) > 0:
                    primary_file = files[0]
                    return {
                        'version_number': latest.get('version_number', ''),
                        'file_name': primary_file.get('filename', ''),
                        'file_url': primary_file.get('url', ''),
                        'file_size': primary_file.get('size', 0),
                        'changelog': latest.get('changelog', '')
                    }
    except Exception as e:
        print(f"   ⚠️  Failed to check for updates for '{project_id}': {e}")
    
    return None


def find_mod_on_modrinth(mod_identifier: str, mc_version: Optional[str] = None, mod_loader: Optional[str] = None) -> Optional[Dict]:
    """
    Ищет мод на Modrinth по имени, slug или project_id
    
    Args:
        mod_identifier: Имя мода, slug или project_id
        mc_version: Версия Minecraft (опционально, для фильтрации)
        mod_loader: Загрузчик модов (опционально, для фильтрации)
        
    Returns:
        Dict с информацией о моде (project_id, slug, title) или None
    """
    if not mod_identifier:
        return None
    
    mod_identifier = mod_identifier.strip()
    
    # Сначала пробуем найти напрямую по project_id или slug
    try:
        response = requests.get(
            f'https://api.modrinth.com/v2/project/{mod_identifier}',
            headers={'User-Agent': 'Astral-AI-API/1.0'},
            timeout=5
        )
        if response.status_code == 200:
            mod_data = response.json()
            return {
                'project_id': mod_data.get('id'),
                'slug': mod_data.get('slug'),
                'title': mod_data.get('title')
            }
    except Exception as e:
        print(f"   ⚠️  Direct Modrinth lookup failed for '{mod_identifier}': {e}")
    
    # Если не нашли напрямую, ищем через Search API
    try:
        import json
        search_url = 'https://api.modrinth.com/v2/search'
        params = {
            'query': mod_identifier,
            'limit': 5
        }
        
        # Формируем facets для фильтрации
        facets = [['project_type:mod']]
        if mc_version:
            facets.append([f'versions:{mc_version}'])
        if mod_loader:
            facets.append([f'categories:{mod_loader.lower()}'])
        
        params['facets'] = json.dumps(facets)
        
        response = requests.get(
            search_url,
            params=params,
            headers={'User-Agent': 'Astral-AI-API/1.0'},
            timeout=5
        )
        
        if response.status_code == 200:
            search_data = response.json()
            if search_data.get('hits') and len(search_data['hits']) > 0:
                # Берём первый результат (самый релевантный)
                found_mod = search_data['hits'][0]
                return {
                    'project_id': found_mod.get('project_id'),
                    'slug': found_mod.get('slug'),
                    'title': found_mod.get('title')
                }
    except Exception as e:
        print(f"   ⚠️  Modrinth search failed for '{mod_identifier}': {e}")
    
    return None

