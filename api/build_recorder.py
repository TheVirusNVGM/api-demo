"""
Build Recorder - сохраняет каждую сборку модпака для обучения через фидбек
"""

import requests
import json
from typing import Dict, List, Optional


def save_modpack_build(
    title: str,
    prompt: str,
    mc_version: str,
    mod_loader: str,
    pack_archetype: Optional[str],
    mods: List[Dict],
    supabase_url: str,
    supabase_key: str
) -> Optional[str]:
    """
    Сохраняет сборку модпака в БД для последующего анализа фидбека
    
    Args:
        title: Название модпака (от AI или пользователя)
        prompt: Исходный запрос пользователя
        mc_version: Версия Minecraft
        mod_loader: Загрузчик модов
        pack_archetype: Тип модпака (e.g., "tech.automation", "optimization.vanilla_friendly")
        mods: Список модов с capabilities
        supabase_url: URL Supabase
        supabase_key: Ключ Supabase
    
    Returns:
        ID созданной записи или None при ошибке
    """
    
    # Генерируем архитектуру в формате модпаков
    architecture = generate_architecture_from_mods(mods, pack_archetype)
    
    headers = {
        'apikey': supabase_key,
        'Authorization': f'Bearer {supabase_key}',
        'Content-Type': 'application/json',
        'Prefer': 'return=representation'  # Вернуть созданную запись
    }
    
    data = {
        'title': title,
        'prompt': prompt,
        'mc_version': mc_version,
        'mod_loader': mod_loader,
        'pack_archetype': pack_archetype,
        'architecture': architecture
    }
    
    try:
        url = f"{supabase_url}/rest/v1/modpack_builds"
        response = requests.post(url, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        build_id = result[0]['id'] if isinstance(result, list) else result['id']
        
        print(f"📝 [Build Recorder] Saved build: {build_id}")
        return build_id
        
    except Exception as e:
        print(f"⚠️  [Build Recorder] Failed to save: {e}")
        return None


def generate_architecture_from_mods(mods: List[Dict], pack_archetype: Optional[str]) -> Dict:
    """
    Генерирует архитектуру в формате модпаков из списка модов
    
    Args:
        mods: Список модов с capabilities и source_id/slug
        pack_archetype: Тип модпака
    
    Returns:
        Dict в формате { version, meta, capabilities, providers }
    """
    
    all_capabilities = set()
    providers = {}
    
    for mod in mods:
        # Получаем идентификатор (предпочтение source_id для совместимости)
        mod_id = mod.get('source_id') or mod.get('project_id') or mod.get('slug')
        if not mod_id:
            continue
        
        # Собираем capabilities
        caps = mod.get('capabilities', [])
        all_capabilities.update(caps)
        
        # Заполняем providers
        for cap in caps:
            if cap not in providers:
                providers[cap] = []
            providers[cap].append(mod_id)
    
    architecture = {
        'version': '1.0.0',
        'meta': {
            'pack_archetype': pack_archetype or 'general.vanilla_plus',
            'mod_count': len(mods),
            'philosophy': []
        },
        'capabilities': sorted(list(all_capabilities)),
        'providers': providers
    }
    
    return architecture


def submit_feedback(
    build_id: str,
    feedback_data: Dict,
    supabase_url: str,
    supabase_key: str
) -> bool:
    """
    Добавляет фидбек к существующей сборке
    
    Args:
        build_id: ID сборки
        feedback_data: Данные фидбека
        supabase_url: URL Supabase
        supabase_key: Ключ Supabase
    
    Returns:
        True если успешно
    """
    
    headers = {
        'apikey': supabase_key,
        'Authorization': f'Bearer {supabase_key}',
        'Content-Type': 'application/json'
    }
    
    try:
        url = f"{supabase_url}/rest/v1/modpack_builds?id=eq.{build_id}"
        response = requests.patch(
            url, 
            headers=headers, 
            json={'feedback': feedback_data},
            timeout=30
        )
        response.raise_for_status()
        
        print(f"✅ [Build Recorder] Feedback submitted for build {build_id}")
        return True
        
    except Exception as e:
        print(f"⚠️  [Build Recorder] Failed to submit feedback: {e}")
        return False
