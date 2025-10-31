"""
Fabric Compatibility Manager
Управляет автоматическим добавлением compatibility mods на основе конфига
"""

import json
import os
from typing import List, Dict, Optional


class FabricCompatManager:
    """Управляет Fabric Compatibility mode на основе конфига"""
    
    def __init__(self, config_path: str = None):
        if config_path is None:
            # По умолчанию ищем конфиг в корне проекта
            config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'fabric_compat_config.json')
        
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)
    
    def get_compatibility_rule(self, mod_loader: str, mc_version: str) -> Optional[Dict]:
        """
        Находит применимое правило совместимости
        
        Args:
            mod_loader: Загрузчик (forge/neoforge/fabric)
            mc_version: Версия Minecraft (например "1.21.1")
        
        Returns:
            Правило совместимости или None
        """
        for rule in self.config['compatibility_rules']:
            if not rule['enabled']:
                continue
            
            conditions = rule['conditions']
            if (conditions['mod_loader'].lower() == mod_loader.lower() and 
                conditions['mc_version'] == mc_version):
                return rule
        
        return None
    
    def get_required_mods(self, mod_loader: str, mc_version: str) -> List[Dict]:
        """
        Возвращает список обязательных модов для данной конфигурации
        
        Returns:
            Список модов с metadata (source_id, name, reason, priority)
        """
        rule = self.get_compatibility_rule(mod_loader, mc_version)
        if not rule:
            return []
        
        # Сортируем по приоритету
        required_mods = sorted(
            rule['required_mods'], 
            key=lambda m: m.get('priority', 999)
        )
        
        return required_mods
    
    def is_connector_mod(self, source_id: str) -> bool:
        """Проверяет, является ли мод connector'ом (триггером авто-включения)"""
        connector_ids = self.config['auto_enable_triggers']['connector_mods']
        return source_id in connector_ids
    
    def get_category_config(self) -> Dict:
        """Возвращает конфигурацию категории для Fabric Compatibility"""
        return self.config['category_config']
    
    def fetch_compatibility_mods(
        self, 
        mod_loader: str, 
        mc_version: str,
        supabase_url: str,
        supabase_key: str
    ) -> List[Dict]:
        """
        Фетчит реальные моды из БД для данной конфигурации
        
        Args:
            mod_loader: Загрузчик
            mc_version: Версия MC
            supabase_url: URL Supabase
            supabase_key: API ключ
        
        Returns:
            Список модов с полными данными из БД
        """
        import requests
        
        required_mods_meta = self.get_required_mods(mod_loader, mc_version)
        
        if not required_mods_meta:
            print(f"   ℹ️  No compatibility mods required for {mod_loader} {mc_version}")
            return []
        
        print(f"🔧 Fabric Compatibility Mode: {mod_loader} {mc_version}")
        print(f"   Fetching {len(required_mods_meta)} compatibility mods...")
        
        fetched_mods = []
        
        for mod_meta in required_mods_meta:
            source_id = mod_meta['source_id']
            
            try:
                response = requests.get(
                    f'{supabase_url}/rest/v1/mods',
                    params={'source_id': f'eq.{source_id}', 'select': '*'},
                    headers={
                        'apikey': supabase_key,
                        'Authorization': f'Bearer {supabase_key}'
                    },
                    timeout=10
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if data:
                        mod = data[0]
                        # Добавляем metadata
                        mod['_compat_reason'] = mod_meta['reason']
                        mod['_compat_priority'] = mod_meta['priority']
                        fetched_mods.append(mod)
                        print(f"   ✅ {mod['name']}: {mod_meta['reason']}")
                    else:
                        print(f"   ⚠️  Mod {mod_meta['name']} ({source_id}) not found in DB")
                else:
                    print(f"   ❌ Failed to fetch {mod_meta['name']}: {response.status_code}")
            
            except Exception as e:
                print(f"   ❌ Error fetching {mod_meta['name']}: {e}")
        
        print(f"   ✅ Successfully fetched {len(fetched_mods)}/{len(required_mods_meta)} compatibility mods")
        
        return fetched_mods
    
    def should_enable_for_config(self, mod_loader: str, mc_version: str) -> bool:
        """Проверяет, должен ли Fabric Compat режим быть доступен"""
        return self.get_compatibility_rule(mod_loader, mc_version) is not None


# Глобальный экземпляр
_manager_instance = None


def get_fabric_compat_manager() -> FabricCompatManager:
    """Возвращает глобальный экземпляр FabricCompatManager"""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = FabricCompatManager()
    return _manager_instance
