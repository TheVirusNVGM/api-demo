"""
Layer 1: Hybrid Search Engine
Выполняет план поиска, комбинируя векторный и keyword поиск с BM25
"""

import requests
from typing import Dict, List, Tuple
from sentence_transformers import SentenceTransformer
from collections import defaultdict
import math
import re
from config import BM25_K1, BM25_B, CONNECTOR_MODS, CATEGORY_SYNONYMS

# Глобальная модель embeddings
embedding_model = None


def get_embedding_model():
    """Ленивая загрузка модели embeddings"""
    global embedding_model
    if embedding_model is None:
        print("📥 [Hybrid Search] Loading sentence-transformers model...")
        embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
        print("✅ [Hybrid Search] Model loaded")
    return embedding_model


def execute_search_plan(
    search_plan: Dict,
    supabase_url: str,
    supabase_key: str
) -> List[Dict]:
    """
    Выполняет план поиска и возвращает candidates
    
    Args:
        search_plan: План поиска от Query Planner
        supabase_url: URL Supabase
        supabase_key: Ключ Supabase
    
    Returns:
        List кандидатов с scores
    """
    
    print(f"🔍 [Hybrid Search] Executing search plan...")
    
    # Получаем метаданные
    metadata = search_plan.get('_metadata', {})
    mc_version = metadata.get('mc_version', '1.21.1')
    mod_loader = metadata.get('mod_loader', 'fabric')
    fabric_compat_mode = metadata.get('fabric_compat_mode', False)
    
    # Собираем результаты от всех queries
    all_results = []
    
    for query_config in search_plan.get('search_queries', []):
        query_type = query_config.get('type', 'semantic')
        query_text = query_config.get('text', '')
        weight = query_config.get('weight', 1.0)
        limit = query_config.get('limit', 100)
        
        print(f"   🔎 {query_type.upper()} query: \"{query_text[:50]}...\" (weight={weight})")
        
        if query_type == 'semantic':
            results = vector_search(
                query_text=query_text,
                limit=limit,
                supabase_url=supabase_url,
                supabase_key=supabase_key
            )
        elif query_type == 'keyword':
            results = keyword_search(
                query_text=query_text,
                limit=limit,
                supabase_url=supabase_url,
                supabase_key=supabase_key
            )
        else:
            print(f"   ⚠️  Unknown query type: {query_type}")
            continue
        
        # Применяем вес к scores
        for mod in results:
            mod['_search_score'] = mod.get('_search_score', 1.0) * weight
            mod['_search_type'] = query_type
        
        all_results.extend(results)
        print(f"      → Found {len(results)} mods")
    
    # Объединяем результаты (Reciprocal Rank Fusion - упрощённая версия)
    print(f"🔗 [Hybrid Search] Fusing {len(all_results)} results...")
    fused_results = fuse_results(all_results)
    
    print(f"   → {len(fused_results)} unique mods after fusion")
    
    # Применяем фильтры
    print(f"🔧 [Hybrid Search] Applying filters...")
    filtered_results = apply_filters(
        candidates=fused_results,
        filters=search_plan.get('filters', {}),
        mc_version=mc_version,
        mod_loader=mod_loader,
        fabric_compat_mode=fabric_compat_mode
    )
    
    print(f"   → {len(filtered_results)} mods after filtering")
    
    # Применяем diversity rules (но не для optimization/performance)
    filters = search_plan.get('filters', {})
    categories_include = filters.get('categories_include', [])
    
    # Для optimization/performance запросов diversity не нужен
    skip_diversity = any(cat in ['optimization', 'performance'] for cat in categories_include)
    
    if skip_diversity:
        print(f"🎨 [Hybrid Search] Skipping diversity check for optimization query...")
        diverse_results = filtered_results
        print(f"   → Keeping all {len(diverse_results)} optimization mods")
    else:
        print(f"🎨 [Hybrid Search] Ensuring diversity...")
        diverse_results = ensure_diversity(
            candidates=filtered_results,
            diversity_rules=search_plan.get('diversity', {})
        )
        print(f"   → {len(diverse_results)} mods after diversity check")
    
    # Ограничиваем по target_count
    target_count = search_plan.get('target_count', 100)
    final_results = diverse_results[:target_count]
    
    print(f"✅ [Hybrid Search] Returning {len(final_results)} candidates")
    
    return final_results


def vector_search(
    query_text: str,
    limit: int,
    supabase_url: str,
    supabase_key: str
) -> List[Dict]:
    """
    Векторный поиск через Supabase
    """
    model = get_embedding_model()
    query_embedding = model.encode(query_text).tolist()
    
    response = requests.post(
        f'{supabase_url}/rest/v1/rpc/search_mods_semantic',
        headers={
            'apikey': supabase_key,
            'Authorization': f'Bearer {supabase_key}',
            'Content-Type': 'application/json'
        },
        json={
            'query_embedding': query_embedding,
            'match_count': limit
        },
        timeout=30
    )
    
    if response.status_code != 200:
        print(f"   ⚠️  Vector search failed: {response.status_code}")
        print(f"   Error: {response.text}")
        return []
    
    results = response.json()
    
    # Добавляем search score (distance → similarity)
    for mod in results:
        # Supabase возвращает distance (меньше = лучше)
        # Преобразуем в similarity (больше = лучше)
        distance = mod.get('distance', 1.0)
        mod['_search_score'] = 1.0 / (1.0 + distance)
    
    return results


def keyword_search(
    query_text: str,
    limit: int,
    supabase_url: str,
    supabase_key: str
) -> List[Dict]:
    """
    Keyword поиск с BM25 scoring
    BM25 - статистический алгоритм ранжирования для IR
    """
    keywords = [w.lower() for w in query_text.split() if len(w) > 2]
    
    if not keywords:
        return []
    
    # Фетчим моды для BM25 scoring
    # Строим OR запрос для ВСЕХ keywords (не только первого!)
    or_conditions = []
    for keyword in keywords:
        or_conditions.append(f'name.ilike.*{keyword}*')
        or_conditions.append(f'summary.ilike.*{keyword}*')
        or_conditions.append(f'description.ilike.*{keyword}*')
    
    or_query = ','.join(or_conditions)
    
    response = requests.get(
        f'{supabase_url}/rest/v1/mods',
        headers={
            'apikey': supabase_key,
            'Authorization': f'Bearer {supabase_key}',
        },
        params={
            'or': f'({or_query})',
            'limit': limit * 3  # Берём больше для лучшего BM25
        },
        timeout=30
    )
    
    if response.status_code != 200:
        print(f"   ⚠️  Keyword search failed: {response.status_code}")
        return []
    
    results = response.json()
    
    # Применяем BM25 scoring
    results_with_bm25 = calculate_bm25_scores(results, keywords)
    
    # EXACT MATCH BOOST
    for mod in results_with_bm25:
        mod_slug = mod.get('slug', '').lower()
        mod_name = mod.get('name', '').lower()
        
        for keyword in keywords:
            keyword_lower = keyword.lower()
            if mod_slug == keyword_lower or mod_name == keyword_lower:
                mod['_search_score'] = mod.get('_search_score', 0) * 10
                mod['_exact_match'] = True
                break
    
    results_with_bm25.sort(key=lambda m: m.get('_search_score', 0), reverse=True)
    return results_with_bm25[:limit]


def calculate_bm25_scores(documents: List[Dict], query_terms: List[str], k1: float = BM25_K1, b: float = BM25_B) -> List[Dict]:
    """
    Вычисляет BM25 scores для документов
    
    BM25 Formula:
    score(D,Q) = Σ IDF(qi) * (f(qi,D) * (k1 + 1)) / (f(qi,D) + k1 * (1 - b + b * |D| / avgdl))
    
    Args:
        documents: Список модов
        query_terms: Термины запроса
        k1: Параметр насыщения (обычно 1.2-2.0)
        b: Параметр длины документа (обычно 0.75)
    
    Returns:
        Документы с добавленным _search_score
    """
    if not documents or not query_terms:
        return documents
    
    # Подготавливаем тексты документов
    doc_texts = []
    for mod in documents:
        # Веса: имя (3x) + summary (2x) + tags (2x) + description (1x)
        name = mod.get('name', '')
        summary = mod.get('summary', '')
        tags = ' '.join(mod.get('tags', []))
        desc = mod.get('description', '')[:500]  # Ограничиваем description
        
        # Повторяем важные части для веса
        text = f"{name} {name} {name} {summary} {summary} {tags} {tags} {desc}"
        doc_texts.append(text.lower())
    
    # Вычисляем avgdl (средняя длина документа)
    doc_lengths = [len(text.split()) for text in doc_texts]
    avgdl = sum(doc_lengths) / len(doc_lengths) if doc_lengths else 1
    
    N = len(documents)  # Количество документов
    
    # Вычисляем IDF для каждого query term
    idf_scores = {}
    for term in query_terms:
        # Количество документов, содержащих term
        df = sum(1 for text in doc_texts if term in text)
        # IDF = log((N - df + 0.5) / (df + 0.5) + 1)
        idf = math.log((N - df + 0.5) / (df + 0.5) + 1) if df > 0 else 0
        idf_scores[term] = idf
    
    # Вычисляем BM25 score для каждого документа
    for i, mod in enumerate(documents):
        text = doc_texts[i]
        doc_len = doc_lengths[i]
        
        score = 0.0
        for term in query_terms:
            if term not in text:
                continue
            
            # Частота термина в документе
            tf = text.count(term)
            
            # IDF термина
            idf = idf_scores.get(term, 0)
            
            # BM25 component
            numerator = tf * (k1 + 1)
            denominator = tf + k1 * (1 - b + b * (doc_len / avgdl))
            
            score += idf * (numerator / denominator)
        
        # Нормализуем score (для удобства, чтобы был в диапазоне 0-1)
        mod['_search_score'] = min(score / (len(query_terms) * 5), 1.0)
        mod['_bm25_raw'] = score
    
    return documents


def fuse_results(results: List[Dict]) -> List[Dict]:
    """
    Объединяет результаты от разных queries
    Использует Reciprocal Rank Fusion (упрощённая версия)
    """
    # Группируем по slug
    mods_dict = {}
    
    for mod in results:
        slug = mod.get('slug')
        if not slug:
            continue
        
        if slug not in mods_dict:
            mods_dict[slug] = mod.copy()
            mods_dict[slug]['_combined_score'] = 0
            mods_dict[slug]['_search_types'] = []
        
        # Добавляем score
        score = mod.get('_search_score', 0)
        mods_dict[slug]['_combined_score'] += score
        
        # Запоминаем откуда пришёл результат
        search_type = mod.get('_search_type', 'unknown')
        if search_type not in mods_dict[slug]['_search_types']:
            mods_dict[slug]['_search_types'].append(search_type)
    
    # Сортируем по combined score
    fused = sorted(
        mods_dict.values(),
        key=lambda m: m['_combined_score'],
        reverse=True
    )
    
    return fused


def apply_filters(
    candidates: List[Dict],
    filters: Dict,
    mc_version: str,
    mod_loader: str,
    fabric_compat_mode: bool
) -> List[Dict]:
    """
    Применяет фильтры к кандидатам
    """
    filtered = []
    
    exclude_ids = set(filters.get('exclude_project_ids', []))
    min_downloads = filters.get('min_downloads', 0)
    categories_include = set(filters.get('categories_include', []))
    categories_prefer = set(filters.get('categories_prefer', []))
    required_capabilities = set(filters.get('required_capabilities', []))
    preferred_capabilities = set(filters.get('preferred_capabilities', []))
    
    # DEBUG: Показываем фильтры
    if required_capabilities or preferred_capabilities:
        print(f"   🔧 Filters: min_downloads={min_downloads}, required_capabilities={required_capabilities}")
    else:
        print(f"   🔧 Filters: min_downloads={min_downloads}, categories_include={categories_include}")
    
    
    for mod in candidates:
        # Исключаем уже добавленные
        if mod.get('source_id') in exclude_ids or mod.get('slug') in exclude_ids:
            print(f"   ⏭️  Skipped (already added): {mod.get('slug')}")
            continue
        
        # Фильтруем устаревшие моды (reported_count >= 3)
        incompatibilities = mod.get('incompatibilities', {})
        if isinstance(incompatibilities, dict) and '_OUTDATED_' in incompatibilities:
            reported_count = incompatibilities['_OUTDATED_'].get('reported_count', 0)
            if reported_count >= 3:
                print(f"   ⏭️  Skipped (outdated): {mod.get('slug')} - reported {reported_count} times")
                continue
        
        # Проверяем несовместимости с модами уже в списке
        if isinstance(incompatibilities, dict):
            is_incompatible = False
            for other_mod in filtered:
                other_id = other_mod.get('source_id') or other_mod.get('slug')
                if other_id in incompatibilities:
                    # Проверяем loader-specific несовместимости
                    incompat_info = incompatibilities[other_id]
                    if isinstance(incompat_info, dict):
                        incompat_loaders = incompat_info.get('loaders')
                        # Если loaders не указаны - глобальная несовместимость
                        if not incompat_loaders or mod_loader in incompat_loaders:
                            print(f"   ⏭️  Skipped (incompatible): {mod.get('slug')} ↔️ {other_mod.get('slug')}")
                            is_incompatible = True
                            break
            
            if is_incompatible:
                continue
        
        # Минимум загрузок
        if mod.get('downloads', 0) < min_downloads:
            print(f"   ⏭️  Skipped (low downloads): {mod.get('slug')} - {mod.get('downloads', 0)} < {min_downloads}")
            continue
        
        # Проверка версии MC
        mod_versions = mod.get('mc_versions', [])
        if mod_versions and mc_version not in mod_versions:
            # Проверяем partial match (например "1.21.1" в ["1.21"])
            version_match = any(
                mc_version.startswith(v) or v.startswith(mc_version)
                for v in mod_versions
            )
            if not version_match:
                continue
        
        # Проверка loader
        mod_loaders = mod.get('loaders', [])
        if mod_loaders:
            if fabric_compat_mode:
                # Принимаем и fabric и neoforge/forge
                loader_ok = any(loader in mod_loaders for loader in ['fabric', 'neoforge', 'forge'])
                if loader_ok:
                    # Приоритет NeoForge
                    mod['_prefers_neoforge'] = 'neoforge' in mod_loaders or 'forge' in mod_loaders
            else:
                loader_ok = mod_loader in mod_loaders
            
            if not loader_ok:
                continue
        
        # Категории (если указаны) - используем modrinth_categories + tags
        mod_categories = set(mod.get('modrinth_categories', []))
        mod_tags = set(mod.get('tags', []))
        all_categories = mod_categories | mod_tags
        
        if categories_include:
            
            has_matching_category = False
            for required_cat in categories_include:
                # Получаем синонимы для required категории
                synonyms = CATEGORY_SYNONYMS.get(required_cat.lower(), {required_cat.lower()})
                
                # Проверяем частичное совпадение с синонимами
                for mod_cat in all_categories:
                    mod_cat_lower = mod_cat.lower()
                    for synonym in synonyms:
                        if synonym in mod_cat_lower or mod_cat_lower in synonym:
                            has_matching_category = True
                            break
                    if has_matching_category:
                        break
                if has_matching_category:
                    break
            
            if not has_matching_category:
                # Не логируем каждый skip - слишком много спама
                continue
        
        # Бонус за предпочитаемые категории
        if categories_prefer and all_categories.intersection(categories_prefer):
            mod['_combined_score'] = mod.get('_combined_score', 0) * 1.2
        
        # Capability-based scoring (не фильтр!)
        mod_capabilities = set(mod.get('capabilities', []))
        
        # Бонус за required capabilities (сильный)
        if required_capabilities and mod_capabilities.intersection(required_capabilities):
            mod['_combined_score'] = mod.get('_combined_score', 0) * 1.5
        
        # Бонус за preferred capabilities (средний)
        if preferred_capabilities and mod_capabilities.intersection(preferred_capabilities):
            mod['_combined_score'] = mod.get('_combined_score', 0) * 1.2
        
        filtered.append(mod)
    
    # Сортируем: NeoForge моды сначала (если fabric compat)
    if fabric_compat_mode:
        filtered.sort(
            key=lambda m: (
                not m.get('_prefers_neoforge', False),
                -m.get('_combined_score', 0),
                -m.get('downloads', 0)
            )
        )
    else:
        filtered.sort(
            key=lambda m: (-m.get('_combined_score', 0), -m.get('downloads', 0))
        )
    
    return filtered


def ensure_diversity(
    candidates: List[Dict],
    diversity_rules: Dict
) -> List[Dict]:
    """
    Обеспечивает разнообразие результатов
    Использует НАШИ теги (393 шт) с fallback на modrinth_categories
    """
    if not diversity_rules.get('ensure_variety', False):
        return candidates
    
    # Увеличенный лимит - 50 модов на категорию
    max_per_category = diversity_rules.get('max_per_category', 50)
    
    # Считаем моды per category
    category_counts = defaultdict(int)
    diverse_results = []
    
    for mod in candidates:
        # ПРИОРИТЕТ: Используем НАШИ теги (393 шт)
        our_tags = mod.get('tags', [])
        
        if our_tags and isinstance(our_tags, list) and len(our_tags) > 0:
            # Берём первый тег как primary category
            # Наши теги более точные!
            primary_category = our_tags[0] if isinstance(our_tags[0], str) else 'other'
        else:
            # FALLBACK: Если нет тегов - смотрим modrinth_categories
            modrinth_cats = mod.get('modrinth_categories', [])
            primary_category = modrinth_cats[0] if modrinth_cats else 'other'
        
        # Проверяем лимит
        if category_counts[primary_category] < max_per_category:
            diverse_results.append(mod)
            category_counts[primary_category] += 1
    
    return diverse_results
