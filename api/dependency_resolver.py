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
    max_total_mods: int = None,  # None = без лимита для dependencies
    fabric_compat_mode: bool = False,  # Фильтровать Fabric Compatibility моды если False
    fabric_fix_ids: List[str] = None  # Список source_id Fabric Compatibility модов
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
            # Пропускаем если уже есть в выбранных
            if dep_source_id in selected_source_ids:
                if depth == 0:  # Логируем только для первого уровня
                    print(f"      ⏭️  {dep_source_id[:8]}... already in selected mods")
                continue
            
            # Пропускаем если уже добавлен как зависимость
            if any(d.get('source_id') == dep_source_id for d in dependencies_to_add):
                if depth == 0:  # Логируем только для первого уровня
                    dep_name = next((d.get('name', dep_source_id) for d in dependencies_to_add if d.get('source_id') == dep_source_id), dep_source_id)
                    print(f"      ⏭️  {dep_name} already added as dependency")
                continue
            
            # Проверяем тип зависимости
            dep_type = dep_info.get('type', 'optional')
            if dep_type != 'required':
                if depth == 0:  # Логируем только для первого уровня
                    print(f"      ⏭️  {dep_source_id[:8]}... is optional dependency")
                continue
            
            # Проверяем версию MC
            dep_versions = dep_info.get('versions', [])
            if dep_versions and mc_version not in dep_versions:
                version_match = any(
                    mc_version.startswith(v) or v.startswith(mc_version) 
                    for v in dep_versions
                )
                if not version_match:
                    if depth == 0:  # Логируем только для первого уровня
                        print(f"      ⏭️  {dep_source_id[:8]}... - version mismatch (required: {dep_versions}, got: {mc_version})")
                    continue
            
            # Получаем данные из уже загруженного batch
            dep_mod = mods_map.get(dep_source_id)
            if not dep_mod:
                if depth == 0:  # Логируем только для первого уровня
                    dep_name = dep_info.get('name', dep_source_id[:8] + '...')
                    print(f"      ⚠️  Dependency {dep_name} ({dep_source_id[:8]}...) not found in DB")
                continue
            
            # ПРОВЕРКА СОВМЕСТИМОСТИ С LOADER'ОМ
            is_loader_ok, loader_reason = is_mod_compatible_with_loader(dep_mod)
            if not is_loader_ok:
                if depth == 0:  # Логируем только для первого уровня
                    print(f"      ⏭️  {dep_mod.get('name', dep_source_id)} - {loader_reason}")
                continue
            
            # ФИЛЬТРАЦИЯ FABRIC COMPATIBILITY МОДОВ
            if not fabric_compat_mode and fabric_fix_ids:
                if dep_mod.get('source_id') in fabric_fix_ids:
                    # Пропускаем Fabric Compatibility моды если режим выключен
                    if depth == 0:
                        print(f"      ⏭️  {dep_mod.get('name')} - Fabric Compatibility mod (mode disabled)")
                    continue
            
            # ФИЛЬТРАЦИЯ FFAPI (Forgified Fabric API)
            # FFAPI source_id: 'Aqlf1Shp'
            if not fabric_compat_mode:
                if dep_mod.get('source_id') == 'Aqlf1Shp':
                    # Пропускаем FFAPI если режим выключен
                    if depth == 0:
                        print(f"      ⏭️  {dep_mod.get('name')} - FFAPI (fabric compat mode disabled)")
                    continue
            
            # ПРОВЕРКА НЕСОВМЕСТИМОСТИ
            all_existing = selected_mods + dependencies_to_add
            is_compatible, incompat_reason = check_incompatibilities(dep_mod, all_existing)
            
            if not is_compatible:
                if depth == 0:  # Логируем только для первого уровня
                    print(f"      ⏭️  {dep_mod.get('name')} - {incompat_reason}")
                continue
            
            dep_mod['_added_as_dependency'] = True
            dep_mod['_dependency_of'] = mod.get('name', 'unknown')
            dependencies_to_add.append(dep_mod)
            dep_name = dep_mod.get('name', 'Unknown')
            dep_source_id = dep_mod.get('source_id', 'unknown')
            print(f"      ✅ {dep_name} (source_id: {dep_source_id[:8]}...)")
            
            # Рекурсивно обрабатываем зависимости этой зависимости
            process_mod_dependencies(dep_mod, mods_map, depth + 1)
    
    # Сначала фильтруем выбранные моды по loader'у и FFAPI зависимостям
    print("🔍 Filtering selected mods by loader compatibility...")
    filtered_selected_mods = []
    FFAPI_SOURCE_ID = 'Aqlf1Shp'  # Forgified Fabric API
    
    for mod in selected_mods:
        is_loader_ok, loader_reason = is_mod_compatible_with_loader(mod)
        if not is_loader_ok:
            print(f"   ⏭️  Removed: {mod.get('name')} - {loader_reason}")
            continue
        
        # Проверяем, требует ли мод FFAPI как зависимость
        if not fabric_compat_mode:
            mod_deps = mod.get('dependencies', {})
            if isinstance(mod_deps, str):
                try:
                    mod_deps = json.loads(mod_deps)
                except:
                    mod_deps = {}
            
            if isinstance(mod_deps, dict) and FFAPI_SOURCE_ID in mod_deps:
                dep_info = mod_deps[FFAPI_SOURCE_ID]
                if dep_info.get('type') == 'required':
                    print(f"   ⏭️  Removed: {mod.get('name')} - requires FFAPI (fabric compat mode disabled)")
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
    skipped_deps = []  # Для логирования пропущенных зависимостей
    
    for mod in filtered_selected_mods:
        mod_name = mod.get('name', 'unknown')
        dependencies = mod.get('dependencies', {})
        if isinstance(dependencies, str):
            try:
                dependencies = json.loads(dependencies)
            except:
                dependencies = {}
        
        if not isinstance(dependencies, dict):
            continue
        
        for dep_source_id, dep_info in dependencies.items():
            dep_name = dep_info.get('name', dep_source_id[:8] + '...')
            dep_type = dep_info.get('type', 'optional')
            if dep_type != 'required':
                skipped_deps.append(f"{mod_name} → {dep_name} (optional)")
                continue
            
            # Проверяем версию MC
            dep_versions = dep_info.get('versions', [])
            if dep_versions and mc_version not in dep_versions:
                version_match = any(
                    mc_version.startswith(v) or v.startswith(mc_version) 
                    for v in dep_versions
                )
                if not version_match:
                    skipped_deps.append(f"{mod_name} → {dep_name} (version mismatch: {dep_versions})")
                    continue
            
            # Пропускаем если уже выбран
            if dep_source_id in selected_source_ids:
                skipped_deps.append(f"{mod_name} → {dep_name} (already selected)")
                continue
            
            all_dep_ids_to_fetch.add(dep_source_id)
    
    print(f"   🔍 Found {len(all_dep_ids_to_fetch)} unique dependencies to fetch")
    if skipped_deps:
        print(f"   ℹ️  Skipped {len(skipped_deps)} dependencies (optional/already selected/version mismatch)")
        # Показываем первые 10 пропущенных для отладки
        for skipped in skipped_deps[:10]:
            print(f"      - {skipped}")
        if len(skipped_deps) > 10:
            print(f"      ... and {len(skipped_deps) - 10} more")
    
    # Фетчим все зависимости одним запросом
    if all_dep_ids_to_fetch:
        print(f"   🚀 Fetching all dependencies in one batch...")
        dependency_mods_map = fetch_mods_batch(list(all_dep_ids_to_fetch))
        fetched_count = len(dependency_mods_map)
        total_count = len(all_dep_ids_to_fetch)
        print(f"   ✅ Fetched {fetched_count}/{total_count} mods from DB")
        if fetched_count < total_count:
            missing_ids = all_dep_ids_to_fetch - set(dependency_mods_map.keys())
            print(f"   ⚠️  Missing {len(missing_ids)} dependencies in DB:")
            for missing_id in list(missing_ids)[:5]:
                print(f"      - {missing_id[:8]}...")
            if len(missing_ids) > 5:
                print(f"      ... and {len(missing_ids) - 5} more")
    else:
        dependency_mods_map = {}
    
    # Теперь обрабатываем зависимости с уже загруженными данными
    print("\n🔧 Processing dependencies...")
    for mod in filtered_selected_mods:
        process_mod_dependencies(mod, dependency_mods_map)
    
    # Объединяем результаты
    final_mods = filtered_selected_mods + dependencies_to_add
    
    # Логируем добавленные зависимости для отладки
    if dependencies_to_add:
        print(f"\n📋 Added dependencies ({len(dependencies_to_add)} mods):")
        for dep in dependencies_to_add:
            dep_name = dep.get('name', 'Unknown')
            dep_source_id = dep.get('source_id', 'unknown')
            dep_of = dep.get('_dependency_of', 'unknown')
            print(f"   • {dep_name} (source_id: {dep_source_id[:8]}..., required by: {dep_of})")
    
    # ПРОВЕРКА КОНФЛИКТОВ С ЗАВИСИМОСТЯМИ
    # Если мод A требует зависимость B, а мод C конфликтует с B, отсекаем C
    print("\n🔍 Checking conflicts with dependencies...")
    mods_to_remove = []
    
    for mod in filtered_selected_mods:
        # Получаем зависимости этого мода
        mod_deps = mod.get('dependencies', {})
        if isinstance(mod_deps, str):
            try:
                mod_deps = json.loads(mod_deps)
            except:
                mod_deps = {}
        
        if not isinstance(mod_deps, dict):
            continue
        
        # Проверяем каждую зависимость
        for dep_source_id, dep_info in mod_deps.items():
            if dep_info.get('type') != 'required':
                continue
            
            # Ищем эту зависимость среди добавленных dependencies
            dep_mod = next((d for d in dependencies_to_add if d.get('source_id') == dep_source_id), None)
            if not dep_mod:
                continue
            
            # Проверяем, не конфликтует ли какой-то выбранный мод с этой зависимостью
            for other_mod in filtered_selected_mods:
                if other_mod == mod:
                    continue
                
                # Проверяем конфликт в обе стороны
                other_incompats = other_mod.get('incompatibilities', {})
                if isinstance(other_incompats, str):
                    try:
                        other_incompats = json.loads(other_incompats)
                    except:
                        other_incompats = {}
                
                dep_incompats = dep_mod.get('incompatibilities', {})
                if isinstance(dep_incompats, str):
                    try:
                        dep_incompats = json.loads(dep_incompats)
                    except:
                        dep_incompats = {}
                
                if not isinstance(other_incompats, dict):
                    other_incompats = {}
                if not isinstance(dep_incompats, dict):
                    dep_incompats = {}
                
                # Если other_mod конфликтует с dep_mod (зависимостью mod)
                if (dep_source_id in other_incompats) or (other_mod.get('source_id') in dep_incompats):
                    # Отсекаем other_mod, так как он конфликтует с зависимостью mod
                    if other_mod not in mods_to_remove:
                        mods_to_remove.append(other_mod)
                        reason = other_incompats.get(dep_source_id, {}).get('reason', '') or dep_incompats.get(other_mod.get('source_id'), {}).get('reason', '')
                        print(f"   ⚠️  Removing {other_mod.get('name')} - conflicts with {dep_mod.get('name')} (required by {mod.get('name')})")
                        if reason:
                            print(f"      Reason: {reason}")
    
    # Удаляем конфликтующие моды
    if mods_to_remove:
        # Логируем что удаляем
        for mod_to_remove in mods_to_remove:
            print(f"   ⚠️  Will remove: {mod_to_remove.get('name')} (source_id: {mod_to_remove.get('source_id', 'unknown')[:8]}...)")
        
        final_mods = [m for m in final_mods if m not in mods_to_remove]
        filtered_selected_mods = [m for m in filtered_selected_mods if m not in mods_to_remove]
        print(f"   ✅ Removed {len(mods_to_remove)} mod(s) conflicting with dependencies")
        
        # Проверяем, что зависимости не были случайно удалены
        deps_before = len(dependencies_to_add)
        deps_after = sum(1 for m in final_mods if m.get('_added_as_dependency'))
        if deps_before != deps_after:
            print(f"   ⚠️  WARNING: Dependency count changed! Before: {deps_before}, After: {deps_after}")
            # Находим какие зависимости пропали
            missing_deps = []
            for dep in dependencies_to_add:
                dep_source_id = dep.get('source_id')
                if dep_source_id:
                    found = any(m.get('source_id') == dep_source_id for m in final_mods)
                    if not found:
                        missing_deps.append(f"{dep.get('name')} (source_id: {dep_source_id[:8]}...)")
            if missing_deps:
                print(f"      Missing dependencies: {', '.join(missing_deps[:3])}")
                if len(missing_deps) > 3:
                    print(f"      ... and {len(missing_deps) - 3} more")
    
    print()
    print(f"✅ [Dependency Resolver] Complete:")
    print(f"   - AI selected: {len(selected_mods)} mods")
    print(f"   - After loader filter: {len(filtered_selected_mods)} mods")
    print(f"   - Dependencies added: {len(dependencies_to_add)} mods")
    print(f"   - Total: {len(final_mods)} mods ({len(filtered_selected_mods)} gameplay + {len(dependencies_to_add)} libraries)")
    print(f"   ℹ️  Dependencies are NOT counted in mod limit (they're libraries)")
    
    # Проверяем, что все зависимости действительно в финальном списке
    if dependencies_to_add:
        missing_deps = []
        for dep in dependencies_to_add:
            dep_source_id = dep.get('source_id')
            if dep_source_id:
                found = any(m.get('source_id') == dep_source_id for m in final_mods)
                if not found:
                    missing_deps.append(dep.get('name', 'Unknown'))
        
        if missing_deps:
            print(f"   ⚠️  Warning: {len(missing_deps)} dependency(ies) were added but NOT found in final mods:")
            for dep_name in missing_deps[:5]:  # Показываем первые 5
                print(f"      - {dep_name}")
            if len(missing_deps) > 5:
                print(f"      ... and {len(missing_deps) - 5} more")
    
    print()
    
    # Финальная проверка перед возвратом
    final_deps_count = sum(1 for m in final_mods if m.get('_added_as_dependency'))
    final_selected_count = len(final_mods) - final_deps_count
    print(f"🔍 [Final Check] Returning {len(final_mods)} mods:")
    print(f"   - Selected mods: {final_selected_count}")
    print(f"   - Dependencies: {final_deps_count}")
    
    # Проверяем наличие всех зависимостей по source_id
    if dependencies_to_add:
        missing_in_final = []
        for dep in dependencies_to_add:
            dep_source_id = dep.get('source_id')
            if dep_source_id:
                found = any(m.get('source_id') == dep_source_id for m in final_mods)
                if not found:
                    missing_in_final.append(f"{dep.get('name')} ({dep_source_id[:8]}...)")
        
        if missing_in_final:
            print(f"   ⚠️  CRITICAL: {len(missing_in_final)} dependency(ies) missing in final_mods:")
            for missing in missing_in_final[:5]:
                print(f"      - {missing}")
            if len(missing_in_final) > 5:
                print(f"      ... and {len(missing_in_final) - 5} more")
    
    return final_mods
