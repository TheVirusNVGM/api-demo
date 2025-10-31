"""
Dependency Resolver
Автоматически резолвит и добавляет required dependencies для модов
"""

import json
from typing import List, Dict, Set


def resolve_dependencies(
    selected_mods: List[Dict],
    mc_version: str,
    mod_loader: str,
    supabase_url: str,
    supabase_key: str,
    max_total_mods: int = None  # None = без лимита для dependencies
) -> List[Dict]:
    """
    Резолвит dependencies для выбранных модов
    
    Args:
        selected_mods: Моды выбранные AI
        mc_version: Версия Minecraft (например "1.21.1")
        supabase_url: URL Supabase
        supabase_key: Ключ Supabase
        max_total_mods: DEPRECATED - dependencies больше не ограничены
    
    Returns:
        Список модов с добавленными dependencies (без лимита)
    """
    import requests
    
    print("=" * 80)
    print("🔗 [Dependency Resolver] Resolving required dependencies...")
    print("=" * 80)
    
    # Собираем source_id всех уже выбранных модов
    selected_source_ids = {mod.get('source_id') for mod in selected_mods if mod.get('source_id')}
    
    dependencies_to_add = []
    processed_mods = set()  # Чтобы не обрабатывать один мод дважды
    
    def fetch_mods_batch(source_ids: List[str]) -> Dict[str, Dict]:
        """Фетчит несколько модов из БД за один запрос"""
        if not source_ids:
            return {}
        
        try:
            # Supabase PostgREST поддерживает фильтр 'in'
            ids_filter = ','.join(source_ids)
            response = requests.get(
                f'{supabase_url}/rest/v1/mods',
                params={'source_id': f'in.({ids_filter})', 'select': '*'},
                headers={
                    'apikey': supabase_key,
                    'Authorization': f'Bearer {supabase_key}'
                },
                timeout=15
            )
            
            if response.status_code == 200:
                mods = response.json()
                # Создаём mapping source_id -> mod
                return {mod['source_id']: mod for mod in mods if mod.get('source_id')}
        except Exception as e:
            print(f"   ⚠️  Failed to batch fetch mods: {e}")
        
        return {}
    
    def is_mod_compatible_with_loader(mod: Dict) -> tuple[bool, str]:
        """
        Проверяет, совместим ли мод с текущим loader'ом
        Returns: (is_compatible, reason)
        """
        mod_loaders = mod.get('loaders', [])
        
        # Если loaders не указаны - считаем совместимым
        if not mod_loaders:
            return (True, '')
        
        # Проверяем наличие текущего loader'а
        if mod_loader.lower() not in [l.lower() for l in mod_loaders]:
            available_loaders = ', '.join(mod_loaders)
            return (False, f"Not available for {mod_loader} (only for: {available_loaders})")
        
        return (True, '')
    
    def check_incompatibilities(mod_to_check: Dict, existing_mods: List[Dict]) -> tuple[bool, str]:
        """
        Проверяет несовместимости мода с уже выбранными (ДВУНАПРАВЛЕННО)
        Учитывает loader-специфичные несовместимости
        Returns: (is_compatible, reason)
        """
        mod_source_id = mod_to_check.get('source_id')
        mod_incompats = mod_to_check.get('incompatibilities', {})
        
        # Защита от None/null
        if mod_incompats is None:
            mod_incompats = {}
        
        # Если incompatibilities это строка JSON - парсим
        if isinstance(mod_incompats, str):
            try:
                mod_incompats = json.loads(mod_incompats)
            except:
                mod_incompats = {}
        
        # Проверяем все уже выбранные моды
        for existing_mod in existing_mods:
            existing_id = existing_mod.get('source_id')
            
            # ПРОВЕРКА 1: Проверяем, есть ли у mod_to_check несовместимость с existing_mod
            if mod_incompats and isinstance(mod_incompats, dict) and existing_id and existing_id in mod_incompats:
                incompat_info = mod_incompats[existing_id]
                
                # Проверяем loader-специфичность
                incompat_loaders = incompat_info.get('loaders')
                if incompat_loaders:
                    # Несовместимость только на определенных loader'ах
                    if mod_loader.lower() not in [l.lower() for l in incompat_loaders]:
                        # Текущий loader не в списке - совместимы!
                        print(f"        ℹ️  Incompatibility exists but not for {mod_loader} (only for {incompat_loaders})")
                        continue
                
                # Несовместимость применяется
                reason = incompat_info.get('reason', 'Unknown incompatibility')
                return (False, f"Incompatible with {existing_mod.get('name', existing_id)}: {reason}")
            
            # ПРОВЕРКА 2: Проверяем ОБРАТНОЕ - есть ли у existing_mod несовместимость с mod_to_check
            existing_incompats = existing_mod.get('incompatibilities', {})
            
            # Защита от None
            if existing_incompats is None:
                existing_incompats = {}
            
            if isinstance(existing_incompats, str):
                try:
                    existing_incompats = json.loads(existing_incompats)
                except:
                    existing_incompats = {}
            
            if existing_incompats and isinstance(existing_incompats, dict) and mod_source_id and mod_source_id in existing_incompats:
                incompat_info = existing_incompats[mod_source_id]
                
                # Проверяем loader-специфичность
                incompat_loaders = incompat_info.get('loaders')
                if incompat_loaders:
                    if mod_loader.lower() not in [l.lower() for l in incompat_loaders]:
                        print(f"        ℹ️  Reverse incompatibility exists but not for {mod_loader} (only for {incompat_loaders})")
                        continue
                
                # Несовместимость применяется
                reason = incompat_info.get('reason', 'Unknown incompatibility')
                return (False, f"{existing_mod.get('name', existing_id)} is incompatible with this mod: {reason}")
        
        return (True, '')
    
    def process_mod_dependencies(mod: Dict, mods_map: Dict[str, Dict], depth: int = 0):
        """
        Рекурсивно обрабатывает dependencies мода
        mods_map: уже загруженные данные модов (source_id -> mod)
        """
        if depth > 3:  # Ограничение глубины рекурсии
            return
        
        source_id = mod.get('source_id')
        mod_name = mod.get('name', 'unknown')
        
        if not source_id:
            return
        
        if source_id in processed_mods:
            return
        
        processed_mods.add(source_id)
        if depth == 0:
            print(f"   🔍 {mod_name}")
        
        # Получаем dependencies из БД
        dependencies = mod.get('dependencies', {})
        
        # Если dependencies это строка JSON - парсим
        if isinstance(dependencies, str):
            try:
                dependencies = json.loads(dependencies)
            except:
                dependencies = {}
        
        if not dependencies or not isinstance(dependencies, dict):
            return
        
        # Обрабатываем каждую зависимость
        for dep_source_id, dep_info in dependencies.items():
            # Пропускаем если уже есть в выбранных или добавленных
            if dep_source_id in selected_source_ids:
                continue
            
            if any(d.get('source_id') == dep_source_id for d in dependencies_to_add):
                continue
            
            # Проверяем тип зависимости
            dep_type = dep_info.get('type', 'optional')
            if dep_type != 'required':
                continue
            
            # Проверяем версию MC
            dep_versions = dep_info.get('versions', [])
            if dep_versions and mc_version not in dep_versions:
                version_match = any(
                    mc_version.startswith(v) or v.startswith(mc_version) 
                    for v in dep_versions
                )
                if not version_match:
                    continue
            
            # Получаем данные из уже загруженного batch
            dep_mod = mods_map.get(dep_source_id)
            if not dep_mod:
                continue
            
            # ПРОВЕРКА СОВМЕСТИМОСТИ С LOADER'ОМ
            is_loader_ok, loader_reason = is_mod_compatible_with_loader(dep_mod)
            if not is_loader_ok:
                continue
            
            # ПРОВЕРКА НЕСОВМЕСТИМОСТИ
            all_existing = selected_mods + dependencies_to_add
            is_compatible, incompat_reason = check_incompatibilities(dep_mod, all_existing)
            
            if not is_compatible:
                continue
            
            dep_mod['_added_as_dependency'] = True
            dep_mod['_dependency_of'] = mod.get('name', 'unknown')
            dependencies_to_add.append(dep_mod)
            print(f"      ✅ {dep_mod.get('name')}")
            
            # Рекурсивно обрабатываем зависимости этой зависимости
            process_mod_dependencies(dep_mod, mods_map, depth + 1)
    
    # Сначала фильтруем выбранные моды по loader'у
    print("🔍 Filtering selected mods by loader compatibility...")
    filtered_selected_mods = []
    for mod in selected_mods:
        is_loader_ok, loader_reason = is_mod_compatible_with_loader(mod)
        if not is_loader_ok:
            print(f"   ⏭️  Removed: {mod.get('name')} - {loader_reason}")
            continue
        filtered_selected_mods.append(mod)
    
    if len(filtered_selected_mods) < len(selected_mods):
        print(f"   ℹ️  Filtered out {len(selected_mods) - len(filtered_selected_mods)} incompatible mods")
    
    # Резолвим конфликты по популярности
    print("🔥 Resolving conflicts by popularity...")
    resolved_mods = []
    skipped_due_to_conflicts = []
    
    for mod in filtered_selected_mods:
        # Проверяем конфликты с уже добавленными
        is_compatible, reason = check_incompatibilities(mod, resolved_mods)
        
        if not is_compatible:
            # Нашли конфликт! Сравниваем популярность
            mod_downloads = mod.get('downloads', 0)
            
            # Находим конфликтующий мод
            conflicting_mod = None
            for existing in resolved_mods:
                # Проверяем в обе стороны
                mod_incompats = mod.get('incompatibilities', {})
                if isinstance(mod_incompats, str):
                    try:
                        mod_incompats = json.loads(mod_incompats)
                    except:
                        mod_incompats = {}
                
                existing_incompats = existing.get('incompatibilities', {})
                if isinstance(existing_incompats, str):
                    try:
                        existing_incompats = json.loads(existing_incompats)
                    except:
                        existing_incompats = {}
                
                # Защита от None
                if not isinstance(mod_incompats, dict):
                    mod_incompats = {}
                if not isinstance(existing_incompats, dict):
                    existing_incompats = {}
                
                if (existing.get('source_id') in mod_incompats) or (mod.get('source_id') in existing_incompats):
                    conflicting_mod = existing
                    break
            
            if conflicting_mod:
                conflicting_downloads = conflicting_mod.get('downloads', 0)
                
                if mod_downloads > conflicting_downloads:
                    # Новый мод популярнее - заменяем
                    print(f"   🔄 Replacing {conflicting_mod.get('name')} ({conflicting_downloads:,} downloads) with {mod.get('name')} ({mod_downloads:,} downloads)")
                    resolved_mods.remove(conflicting_mod)
                    resolved_mods.append(mod)
                    skipped_due_to_conflicts.append(conflicting_mod)
                else:
                    # Существующий мод популярнее - оставляем его
                    print(f"   ⏭️  Skipping {mod.get('name')} ({mod_downloads:,} downloads) - keeping {conflicting_mod.get('name')} ({conflicting_downloads:,} downloads)")
                    skipped_due_to_conflicts.append(mod)
            else:
                # Не нашли конфликтующий мод - пропускаем
                print(f"   ⏭️  Skipping {mod.get('name')} - {reason}")
                skipped_due_to_conflicts.append(mod)
        else:
            # Нет конфликтов - добавляем
            resolved_mods.append(mod)
    
    if skipped_due_to_conflicts:
        print(f"   💥 Resolved {len(skipped_due_to_conflicts)} conflict(s)")
    
    filtered_selected_mods = resolved_mods
    
    # Сначала собираем все нужные source_id зависимостей
    print("\n📦 Collecting required dependencies...")
    all_dep_ids_to_fetch = set()
    
    for mod in filtered_selected_mods:
        dependencies = mod.get('dependencies', {})
        if isinstance(dependencies, str):
            try:
                dependencies = json.loads(dependencies)
            except:
                dependencies = {}
        
        if not isinstance(dependencies, dict):
            continue
        
        for dep_source_id, dep_info in dependencies.items():
            dep_type = dep_info.get('type', 'optional')
            if dep_type != 'required':
                continue
            
            # Проверяем версию MC
            dep_versions = dep_info.get('versions', [])
            if dep_versions and mc_version not in dep_versions:
                version_match = any(
                    mc_version.startswith(v) or v.startswith(mc_version) 
                    for v in dep_versions
                )
                if not version_match:
                    continue
            
            # Пропускаем если уже выбран
            if dep_source_id in selected_source_ids:
                continue
            
            all_dep_ids_to_fetch.add(dep_source_id)
    
    print(f"   🔍 Found {len(all_dep_ids_to_fetch)} unique dependencies to fetch")
    
    # Фетчим все зависимости одним запросом
    if all_dep_ids_to_fetch:
        print(f"   🚀 Fetching all dependencies in one batch...")
        dependency_mods_map = fetch_mods_batch(list(all_dep_ids_to_fetch))
        print(f"   ✅ Fetched {len(dependency_mods_map)}/{len(all_dep_ids_to_fetch)} mods from DB")
    else:
        dependency_mods_map = {}
    
    # Теперь обрабатываем зависимости с уже загруженными данными
    print("\n🔧 Processing dependencies...")
    for mod in filtered_selected_mods:
        process_mod_dependencies(mod, dependency_mods_map)
    
    # Объединяем результаты
    final_mods = filtered_selected_mods + dependencies_to_add
    
    print()
    print(f"✅ [Dependency Resolver] Complete:")
    print(f"   - AI selected: {len(selected_mods)} mods")
    print(f"   - After loader filter: {len(filtered_selected_mods)} mods")
    print(f"   - Dependencies added: {len(dependencies_to_add)} mods")
    print(f"   - Total: {len(final_mods)} mods ({len(filtered_selected_mods)} gameplay + {len(dependencies_to_add)} libraries)")
    print(f"   ℹ️  Dependencies are NOT counted in mod limit (they're libraries)")
    print()
    
    return final_mods
