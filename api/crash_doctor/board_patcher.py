"""
Board Patcher
Создаёт исправленную версию board_state на основе плана фиксов
"""

from typing import Dict, List
import copy
from datetime import datetime, UTC


def create_patched_board_state(
    original_board_state: Dict,
    fix_plan: Dict,
    mc_version: str = None,
    mod_loader: str = None
) -> Dict:
    """
    Создаёт исправленную версию board_state на основе плана фиксов
    
    Args:
        original_board_state: Оригинальное состояние доски
        fix_plan: План фиксов от fix_planner.plan_fixes()
        mc_version: Версия MC (для добавления модов)
        mod_loader: Загрузчик (для добавления модов)
        
    Returns:
        Dict с patched_board_state и metadata
    """
    
    # Глубокое копирование board_state
    patched = copy.deepcopy(original_board_state)
    
    # Создаём индекс модов для быстрого поиска
    mod_index = {}
    for i, mod in enumerate(patched.get('mods', [])):
        mod_slug = mod.get('slug', '')
        mod_source_id = mod.get('source_id') or mod.get('project_id', '')
        mod_title = mod.get('title') or mod.get('name', '')
        
        if mod_slug:
            mod_index[mod_slug.lower()] = i
        if mod_source_id:
            mod_index[mod_source_id.lower()] = i
        if mod_title:
            mod_index[mod_title.lower()] = i
    
    operations = fix_plan.get('operations', [])
    applied_operations = []
    failed_operations = []
    
    for op in operations:
        action = op.get('action')
        target_mod = op.get('target_mod', '')
        
        if action == 'remove_mod':
            # Удаляем мод из board_state
            mod_idx = find_mod_index(target_mod, mod_index, patched.get('mods', []))
            
            # Проверяем валидность индекса
            if mod_idx is not None and 0 <= mod_idx < len(patched.get('mods', [])):
                removed_mod = patched['mods'].pop(mod_idx)
                applied_operations.append({
                    'action': 'remove_mod',
                    'mod': removed_mod.get('title') or removed_mod.get('name', 'unknown'),
                    'success': True
                })
                
                # Обновляем mod_index после удаления (все индексы после удалённого сдвигаются)
                mod_index = {}
                for i, mod in enumerate(patched.get('mods', [])):
                    mod_slug = mod.get('slug', '')
                    mod_source_id = mod.get('source_id') or mod.get('project_id', '')
                    mod_title = mod.get('title') or mod.get('name', '')
                    
                    if mod_slug:
                        mod_index[mod_slug.lower()] = i
                    if mod_source_id:
                        mod_index[mod_source_id.lower()] = i
                    if mod_title:
                        mod_index[mod_title.lower()] = i
                
                # Удаляем мод из категории, если он там был
                category_id = removed_mod.get('category_id')
                if category_id:
                    for cat in patched.get('categories', []):
                        if cat.get('id') == category_id:
                            # Категория останется, но мода в ней не будет
                            break
            else:
                failed_operations.append({
                    'action': 'remove_mod',
                    'target': target_mod,
                    'reason': 'Mod not found in board_state or invalid index'
                })
        
        elif action == 'disable_mod':
            # Помечаем мод как отключенный (is_disabled: true)
            mod_idx = find_mod_index(target_mod, mod_index, patched.get('mods', []))
            
            # Проверяем валидность индекса
            if mod_idx is not None and 0 <= mod_idx < len(patched.get('mods', [])):
                patched['mods'][mod_idx]['is_disabled'] = True
                applied_operations.append({
                    'action': 'disable_mod',
                    'mod': patched['mods'][mod_idx].get('title', 'unknown'),
                    'success': True
                })
            else:
                failed_operations.append({
                    'action': 'disable_mod',
                    'target': target_mod,
                    'reason': 'Mod not found in board_state or invalid index'
                })
        
        elif action == 'add_mod':
            # Добавляем мод (пока заглушка - нужно будет интегрировать с dependency_resolver)
            # TODO: Интегрировать с dependency_resolver для получения полной информации о моде
            applied_operations.append({
                'action': 'add_mod',
                'target': target_mod,
                'note': 'Mod addition requires dependency resolver integration',
                'success': False  # Пока не реализовано
            })
        
        elif action == 'enable_fabric_compat':
            # Включаем fabricCompatMode
            patched['fabricCompatMode'] = True
            applied_operations.append({
                'action': 'enable_fabric_compat',
                'success': True
            })
        
        elif action == 'clear_connector_cache':
            # Очистка кэша Connector - это файловая операция, которую нужно выполнить на стороне лаунчера
            # Помечаем как успешную операцию, но фактическое удаление папки .connector будет выполнено лаунчером
            applied_operations.append({
                'action': 'clear_connector_cache',
                'target': '.connector',
                'success': True,
                'note': 'This requires deleting the .connector folder in the mods directory. The launcher will handle this.'
            })
    
    # Добавляем метаданные
    patched['_crash_fix_applied'] = True
    patched['_crash_fix_timestamp'] = datetime.now(UTC).isoformat()
    patched['_crash_fix_operations_count'] = len(applied_operations)
    patched['_crash_fix_failed_operations'] = failed_operations
    
    return {
        'patched_board_state': patched,
        'applied_operations': applied_operations,
        'failed_operations': failed_operations,
        'total_mods_removed': len([op for op in applied_operations if op.get('action') == 'remove_mod']),
        'total_mods_disabled': len([op for op in applied_operations if op.get('action') == 'disable_mod'])
    }


def find_mod_index(mod_identifier: str, mod_index: Dict, mods_list: List) -> int:
    """
    Находит индекс мода в списке
    
    Returns:
        Индекс мода или None
    """
    identifier_lower = mod_identifier.lower()
    
    # Пробуем найти через индекс
    if identifier_lower in mod_index:
        return mod_index[identifier_lower]
    
    # Пробуем найти через частичное совпадение
    for i, mod in enumerate(mods_list):
        mod_title = (mod.get('title') or mod.get('name', '')).lower()
        mod_slug = (mod.get('slug') or '').lower()
        
        if identifier_lower in mod_title or identifier_lower in mod_slug:
            return i
    
    return None

