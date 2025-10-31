"""
Pipeline Transparency
Обеспечивает прозрачность процесса AI сборки:
- Pipeline ID для воспроизводимости
- Reasons для каждого мода (why chosen / why excluded)
- Intermediate results и scores
"""

import uuid
from datetime import datetime
from typing import Dict, List, Optional
import json


class PipelineExecution:
    """Представляет одно выполнение pipeline с полной прозрачностью"""
    
    def __init__(self, user_prompt: str, mc_version: str, mod_loader: str):
        self.pipeline_id = str(uuid.uuid4())
        self.timestamp = datetime.utcnow().isoformat() + 'Z'
        self.user_prompt = user_prompt
        self.mc_version = mc_version
        self.mod_loader = mod_loader
        
        # Этапы
        self.query_plan = None
        self.candidates = []
        self.selected_mods = []
        self.dependencies_added = []
        self.fabric_compat_mods = []
        
        # Прозрачность
        self.scores = {}  # mod_id -> {search_score, combined_score, bm25, etc}
        self.reasons_chosen = {}  # mod_id -> reason
        self.reasons_excluded = {}  # mod_id -> reason
        
        # Метрики
        self.metrics = {
            'candidates_count': 0,
            'selected_count': 0,
            'dependencies_count': 0,
            'total_mods': 0,
            'ai_calls': 0,
            'total_tokens': 0,
            'estimated_cost_usd': 0.0
        }
    
    def set_query_plan(self, plan: Dict):
        """Сохраняет план поиска от Query Planner"""
        self.query_plan = plan
    
    def set_candidates(self, candidates: List[Dict]):
        """Сохраняет кандидатов с scores"""
        self.candidates = candidates
        self.metrics['candidates_count'] = len(candidates)
        
        # Извлекаем scores
        for mod in candidates:
            mod_id = mod.get('source_id') or mod.get('slug')
            if not mod_id:
                continue
            
            self.scores[mod_id] = {
                'search_score': mod.get('_search_score', 0),
                'combined_score': mod.get('_combined_score', 0),
                'bm25_raw': mod.get('_bm25_raw', 0),
                'search_types': mod.get('_search_types', []),
                'downloads': mod.get('downloads', 0),
                'rank_in_results': candidates.index(mod) + 1
            }
    
    def set_selected_mods(self, selected: List[Dict]):
        """Сохраняет выбранные AI моды с причинами"""
        self.selected_mods = selected
        self.metrics['selected_count'] = len(selected)
        
        # Извлекаем причины выбора
        for mod in selected:
            mod_id = mod.get('source_id') or mod.get('slug')
            if not mod_id:
                continue
            
            reason = mod.get('ai_reason', 'Selected by AI')
            self.reasons_chosen[mod_id] = reason
    
    def add_excluded_mod(self, mod: Dict, reason: str):
        """Добавляет мод в excluded с причиной"""
        mod_id = mod.get('source_id') or mod.get('slug')
        if mod_id:
            self.reasons_excluded[mod_id] = reason
    
    def set_dependencies(self, dependencies: List[Dict]):
        """Сохраняет автоматически добавленные dependencies"""
        self.dependencies_added = dependencies
        self.metrics['dependencies_count'] = len(dependencies)
        
        # Добавляем причины
        for dep in dependencies:
            mod_id = dep.get('source_id') or dep.get('slug')
            if mod_id:
                reason = f"Auto-added as dependency of {dep.get('_dependency_of', 'unknown')}"
                self.reasons_chosen[mod_id] = reason
    
    def set_fabric_compat_mods(self, mods: List[Dict]):
        """Сохраняет Fabric Compatibility моды"""
        self.fabric_compat_mods = mods
        
        # Добавляем причины
        for mod in mods:
            mod_id = mod.get('source_id') or mod.get('slug')
            if mod_id:
                reason = mod.get('_compat_reason', 'Required for Fabric compatibility')
                self.reasons_chosen[mod_id] = reason
    
    def track_ai_call(self, tokens_used: int, cost_usd: float):
        """Отслеживает AI вызовы и стоимость"""
        self.metrics['ai_calls'] += 1
        self.metrics['total_tokens'] += tokens_used
        self.metrics['estimated_cost_usd'] += cost_usd
    
    def finalize(self) -> Dict:
        """Финализирует выполнение и возвращает полный отчёт"""
        # Считаем финальные метрики
        self.metrics['total_mods'] = (
            len(self.selected_mods) + 
            len(self.dependencies_added) + 
            len(self.fabric_compat_mods)
        )
        
        return {
            'pipeline_id': self.pipeline_id,
            'timestamp': self.timestamp,
            'input': {
                'prompt': self.user_prompt,
                'mc_version': self.mc_version,
                'mod_loader': self.mod_loader
            },
            'stages': {
                'query_plan': {
                    'strategy': self.query_plan.get('strategy') if self.query_plan else None,
                    'search_queries_count': len(self.query_plan.get('search_queries', [])) if self.query_plan else 0
                },
                'candidates': {
                    'count': self.metrics['candidates_count'],
                    'top_10_scores': self._get_top_scores(10)
                },
                'ai_selection': {
                    'selected_count': self.metrics['selected_count'],
                    'reasons': self.reasons_chosen
                },
                'dependencies': {
                    'count': self.metrics['dependencies_count']
                },
                'fabric_compat': {
                    'count': len(self.fabric_compat_mods),
                    'enabled': len(self.fabric_compat_mods) > 0
                }
            },
            'transparency': {
                'scores': self.scores,
                'reasons_chosen': self.reasons_chosen,
                'reasons_excluded': self.reasons_excluded,
                'excluded_count': len(self.reasons_excluded)
            },
            'metrics': self.metrics,
            'reproducibility': {
                'pipeline_id': self.pipeline_id,
                'can_reproduce': True,
                'note': 'Use this pipeline_id to reproduce the same execution'
            }
        }
    
    def _get_top_scores(self, n: int) -> List[Dict]:
        """Возвращает топ N модов по score"""
        scores_list = [
            {'mod_id': mod_id, **scores}
            for mod_id, scores in self.scores.items()
        ]
        
        scores_list.sort(key=lambda x: x.get('combined_score', 0), reverse=True)
        return scores_list[:n]
    
    def get_summary(self) -> str:
        """Возвращает краткое резюме выполнения"""
        return (
            f"Pipeline {self.pipeline_id[:8]}... executed:\n"
            f"  • Candidates: {self.metrics['candidates_count']}\n"
            f"  • AI Selected: {self.metrics['selected_count']}\n"
            f"  • Dependencies: {self.metrics['dependencies_count']}\n"
            f"  • Total Mods: {self.metrics['total_mods']}\n"
            f"  • AI Calls: {self.metrics['ai_calls']}\n"
            f"  • Tokens Used: {self.metrics['total_tokens']:,}\n"
            f"  • Est. Cost: ${self.metrics['estimated_cost_usd']:.4f}"
        )


# Глобальный реестр pipeline executions
_pipeline_registry = {}


def create_pipeline(user_prompt: str, mc_version: str, mod_loader: str) -> PipelineExecution:
    """Создаёт новый pipeline execution"""
    pipeline = PipelineExecution(user_prompt, mc_version, mod_loader)
    _pipeline_registry[pipeline.pipeline_id] = pipeline
    return pipeline


def get_pipeline(pipeline_id: str) -> Optional[PipelineExecution]:
    """Возвращает pipeline execution по ID"""
    return _pipeline_registry.get(pipeline_id)


def export_pipeline_report(pipeline: PipelineExecution, filepath: str):
    """Экспортирует полный отчёт pipeline в JSON файл"""
    report = pipeline.finalize()
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    print(f"📊 Pipeline report exported to: {filepath}")
