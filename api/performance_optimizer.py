"""
Performance Optimization Manager
Управляет подбором оптимизационных модов с учётом:
- Эквивалентов для разных loader'ов (Sodium → Embeddium)
- Coverage check - покрытие всех слоёв оптимизации
- Совместимость и конфликты
"""

import json
import os
from typing import List, Dict, Set, Tuple


class PerformanceOptimizer:
    """Управляет performance optimization модами"""
    
    def __init__(self, equivalents_path: str = None):
        if equivalents_path is None:
            equivalents_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), 
                'mod_equivalents.json'
            )
        
        with open(equivalents_path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)
    
    def get_recommended_mods(self, mod_loader: str, mc_version: str) -> List[Dict]:
        """
        Возвращает рекомендуемые оптимизационные моды для данной конфигурации
        
        Returns:
            List модов с metadata (slug, name, layer, priority)
        """
        perf_config = self.config['equivalents']['performance_optimization']
        
        loader_key = mod_loader.lower()
        if loader_key not in perf_config:
            return []
        
        loader_config = perf_config[loader_key]
        
        # Для NeoForge/Forge проверяем версию
        if loader_key in ['neoforge', 'forge']:
            if mc_version in loader_config:
                return loader_config[mc_version]
            # Fallback на closest version
            available_versions = list(loader_config.keys())
            if available_versions:
                closest = available_versions[0]  # Берём первую доступную
                print(f"   ℹ️  No exact match for {mc_version}, using {closest} recommendations")
                return loader_config[closest]
        else:
            # Fabric - возвращаем core_mods
            return loader_config.get('core_mods', [])
        
        return []
    
    def get_search_keywords(self, mod_loader: str) -> List[str]:
        """Возвращает ключевые слова для поиска по loader'у"""
        hints = self.config['search_hints']['performance']
        loader_key = mod_loader.lower()
        
        # Специфичные keywords + generic
        specific = hints.get(f'{loader_key}_keywords', [])
        generic = hints.get('generic_keywords', [])
        
        return specific + generic
    
    def check_coverage(self, selected_mods: List[Dict]) -> Dict:
        """
        Проверяет покрытие оптимизационных слоёв
        
        Returns:
            Dict с coverage info и missing layers
        """
        required_layers = {
            'render': 'Render optimization',
            'memory': 'Memory optimization',
            'culling': 'Entity/block culling',
        }
        
        optional_layers = {
            'tick/ai': 'Tick rate & AI optimization',
            'lighting': 'Lighting optimization',
            'worldgen': 'World generation optimization',
            'fps': 'FPS optimization',
            'shaders': 'Shader support',
            'io': 'I/O optimization'
        }
        
        covered_layers = set()
        mods_by_layer = {}
        
        for mod in selected_mods:
            # Проверяем есть ли layer metadata
            layer = mod.get('_optimization_layer') or mod.get('layer')
            if layer:
                covered_layers.add(layer)
                if layer not in mods_by_layer:
                    mods_by_layer[layer] = []
                mods_by_layer[layer].append(mod.get('name', mod.get('slug', 'unknown')))
        
        missing_required = set(required_layers.keys()) - covered_layers
        missing_optional = set(optional_layers.keys()) - covered_layers
        
        return {
            'covered_layers': list(covered_layers),
            'mods_by_layer': mods_by_layer,
            'missing_required': [
                {'layer': layer, 'description': required_layers[layer]} 
                for layer in missing_required
            ],
            'missing_optional': [
                {'layer': layer, 'description': optional_layers[layer]} 
                for layer in missing_optional
            ],
            'coverage_score': len(covered_layers) / (len(required_layers) + len(optional_layers))
        }
    
    def enrich_mods_with_layer_info(
        self, 
        mods: List[Dict], 
        mod_loader: str, 
        mc_version: str
    ) -> List[Dict]:
        """
        Добавляет layer metadata к модам на основе recommended mods
        """
        recommended = self.get_recommended_mods(mod_loader, mc_version)
        
        # Создаём mapping: slug -> layer
        layer_map = {mod['slug']: mod['layer'] for mod in recommended}
        
        enriched = []
        for mod in mods:
            slug = mod.get('slug')
            if slug in layer_map:
                mod['_optimization_layer'] = layer_map[slug]
                mod['_is_recommended'] = True
            enriched.append(mod)
        
        return enriched
    
    def ensure_minimum_coverage(
        self,
        selected_mods: List[Dict],
        candidates: List[Dict],
        mod_loader: str,
        mc_version: str,
        max_additions: int = 10
    ) -> Tuple[List[Dict], List[str]]:
        """
        Добавляет недостающие моды для покрытия критичных слоёв
        
        Returns:
            (updated_mods, added_reasons)
        """
        # Обогащаем моды layer info
        selected_with_layers = self.enrich_mods_with_layer_info(
            selected_mods, mod_loader, mc_version
        )
        candidates_with_layers = self.enrich_mods_with_layer_info(
            candidates, mod_loader, mc_version
        )
        
        # Проверяем coverage
        coverage = self.check_coverage(selected_with_layers)
        
        if not coverage['missing_required']:
            print("✅ [Coverage Check] All required optimization layers covered")
            return selected_with_layers, []
        
        print(f"⚠️  [Coverage Check] Missing {len(coverage['missing_required'])} required layers:")
        
        added_reasons = []
        additions_count = 0
        
        # Пытаемся добавить моды для покрытия missing layers
        selected_slugs = {mod.get('slug') for mod in selected_with_layers}
        
        for missing in coverage['missing_required']:
            if additions_count >= max_additions:
                break
            
            layer = missing['layer']
            print(f"   🔍 Looking for {layer} optimization...")
            
            # Ищем в candidates
            for candidate in candidates_with_layers:
                if candidate.get('_optimization_layer') == layer:
                    slug = candidate.get('slug')
                    if slug not in selected_slugs:
                        candidate['_added_for_coverage'] = True
                        selected_with_layers.append(candidate)
                        selected_slugs.add(slug)
                        reason = f"Added {candidate.get('name')} for {layer} optimization coverage"
                        added_reasons.append(reason)
                        print(f"      ✅ {reason}")
                        additions_count += 1
                        break
        
        if additions_count == 0:
            print("   ℹ️  No additional mods added (candidates don't cover missing layers)")
        else:
            print(f"   ✅ Added {additions_count} mods to improve coverage")
        
        return selected_with_layers, added_reasons


# Глобальный экземпляр
_optimizer_instance = None


def get_performance_optimizer() -> PerformanceOptimizer:
    """Возвращает глобальный экземпляр PerformanceOptimizer"""
    global _optimizer_instance
    if _optimizer_instance is None:
        _optimizer_instance = PerformanceOptimizer()
    return _optimizer_instance
