"""
Layer 1.5: Architecture Matcher
Находит похожие модпаки через semantic search и извлекает их архитектуры как reference examples
"""

import requests
from typing import List, Dict
from sentence_transformers import SentenceTransformer

# Глобальная модель embeddings (lazy load)
embedding_model = None


def get_embedding_model():
    """Ленивая загрузка модели embeddings"""
    global embedding_model
    if embedding_model is None:
        print("📥 [Architecture Matcher] Loading sentence-transformers model...")
        embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
        print("✅ [Architecture Matcher] Model loaded")
    return embedding_model


def find_reference_modpacks(
    user_prompt: str,
    mc_version: str,
    mod_loader: str,
    supabase_url: str,
    supabase_key: str,
    top_n: int = 5
) -> List[Dict]:
    """
    Находит похожие модпаки через semantic search по embedding
    
    Args:
        user_prompt: Запрос пользователя
        mc_version: Версия MC (для контекста, но не фильтруем строго)
        mod_loader: Лоадер (для контекста)
        supabase_url: URL Supabase
        supabase_key: Ключ Supabase
        top_n: Количество reference модпаков
    
    Returns:
        List reference модпаков с их архитектурами
    """
    
    print(f"🔍 [Architecture Matcher] Searching for reference modpacks...")
    print(f"   Query: \"{user_prompt[:50]}...\"")
    
    # 1. Генерируем эмбеддинг запроса
    model = get_embedding_model()
    query_embedding = model.encode(user_prompt, show_progress_bar=False).tolist()
    
    # 2. Ищем похожие модпаки через vector search
    try:
        response = requests.post(
            f'{supabase_url}/rest/v1/rpc/search_modpacks_semantic',
            headers={
                'apikey': supabase_key,
                'Authorization': f'Bearer {supabase_key}',
                'Content-Type': 'application/json'
            },
            json={
                'query_embedding': query_embedding,
                'match_count': top_n * 2  # Берём больше для фильтрации
            },
            timeout=30
        )
        
        if response.status_code != 200:
            print(f"   ⚠️  Vector search failed: {response.status_code}")
            print(f"   Response: {response.text}")
            return []
        
        modpacks = response.json()
        
    except Exception as e:
        print(f"   ⚠️  Search error: {e}")
        return []
    
    # 3. Фильтруем модпаки с валидными архитектурами
    valid_modpacks = []
    
    for modpack in modpacks:
        # Проверяем что есть architecture
        architecture = modpack.get('architecture')
        if not architecture:
            continue
        
        # Проверяем что architecture содержит capabilities
        capabilities = architecture.get('capabilities', [])
        if not capabilities or len(capabilities) < 3:
            # Слишком мало capabilities - не интересно как reference
            continue
        
        # Проверяем providers
        providers = architecture.get('providers', {})
        if not providers or len(providers) < 3:
            # Слишком мало providers - не интересно
            continue
        
        # Добавляем distance для отладки
        distance = modpack.get('distance', 0)
        
        valid_modpacks.append({
            'slug': modpack.get('slug'),
            'title': modpack.get('title'),
            'summary': modpack.get('summary', ''),
            'mc_versions': modpack.get('mc_versions', []),
            'loaders': modpack.get('loaders', []),
            'architecture': architecture,
            'distance': distance,
            '_similarity_score': 1.0 / (1.0 + distance)  # Преобразуем в similarity
        })
        
        if len(valid_modpacks) >= top_n:
            break
    
    # 4. Выводим результаты
    print(f"   → Found {len(valid_modpacks)} reference modpacks with valid architectures")
    
    for i, modpack in enumerate(valid_modpacks, 1):
        arch = modpack['architecture']
        cap_count = len(arch.get('capabilities', []))
        provider_count = len(arch.get('providers', {}))
        similarity = modpack['_similarity_score']
        
        print(f"   {i}. {modpack['title']} (similarity: {similarity:.3f})")
        print(f"      → {cap_count} capabilities, {provider_count} provider groups")
        print(f"      → Versions: {', '.join(modpack['mc_versions'][:3])}...")
    
    return valid_modpacks


def extract_capability_patterns(reference_modpacks: List[Dict]) -> Dict:
    """
    Извлекает паттерны capabilities из reference модпаков
    
    Args:
        reference_modpacks: Список reference модпаков с архитектурами
    
    Returns:
        Dict с агрегированными паттернами
    """
    
    print(f"\n📊 [Architecture Matcher] Extracting capability patterns...")
    
    # Считаем частоту capabilities
    from collections import Counter
    
    all_capabilities = []
    capability_to_providers = {}
    
    for modpack in reference_modpacks:
        architecture = modpack['architecture']
        capabilities = architecture.get('capabilities', [])
        providers = architecture.get('providers', {})
        
        all_capabilities.extend(capabilities)
        
        # Собираем примеры providers для каждого capability
        for cap in capabilities:
            if cap not in capability_to_providers:
                capability_to_providers[cap] = []
            
            # Добавляем provider mods для этого capability
            cap_providers = providers.get(cap, [])
            capability_to_providers[cap].extend(cap_providers)
    
    # Подсчёт частоты
    capability_frequency = Counter(all_capabilities)
    
    # Топ capabilities
    top_capabilities = capability_frequency.most_common(20)
    
    print(f"   Top capabilities across {len(reference_modpacks)} reference modpacks:")
    for cap, count in top_capabilities[:10]:
        print(f"   • {cap}: {count}/{len(reference_modpacks)} modpacks")
    
    return {
        'top_capabilities': [cap for cap, _ in top_capabilities],
        'capability_frequency': dict(capability_frequency),
        'capability_providers': capability_to_providers,
        'total_reference_modpacks': len(reference_modpacks)
    }


def format_for_ai_context(
    reference_modpacks: List[Dict],
    capability_patterns: Dict,
    max_context_length: int = 3000
) -> str:
    """
    Форматирует reference данные для AI контекста
    
    Args:
        reference_modpacks: Reference модпаки
        capability_patterns: Паттерны capabilities
        max_context_length: Максимальная длина контекста в символах
    
    Returns:
        Отформатированный текст для AI промпта
    """
    
    context = []
    
    context.append("REFERENCE MODPACK ARCHITECTURES:")
    context.append("=" * 60)
    context.append(f"Based on {len(reference_modpacks)} similar successful modpacks:\n")
    
    # Топ capabilities
    context.append("COMMON CAPABILITIES PATTERN:")
    top_caps = capability_patterns['top_capabilities'][:15]
    for i, cap in enumerate(top_caps, 1):
        freq = capability_patterns['capability_frequency'][cap]
        context.append(f"  {i}. {cap} (in {freq}/{len(reference_modpacks)} modpacks)")
    
    context.append("\nEXAMPLE MODPACK ARCHITECTURES:")
    
    # Детали по первым 3 reference модпакам
    for i, modpack in enumerate(reference_modpacks[:3], 1):
        context.append(f"\n{i}. {modpack['title']}:")
        
        arch = modpack['architecture']
        capabilities = arch.get('capabilities', [])
        
        # Показываем только релевантные capabilities (пересечение с top)
        relevant_caps = [cap for cap in capabilities if cap in top_caps]
        
        context.append(f"   Core capabilities: {', '.join(relevant_caps[:10])}")
        
        # Примеры модов для ключевых capabilities
        providers = arch.get('providers', {})
        for cap in relevant_caps[:5]:
            mods = providers.get(cap, [])[:3]  # Первые 3 мода
            if mods:
                context.append(f"   - {cap}: {', '.join(mods)}")
    
    full_context = "\n".join(context)
    
    # Обрезаем если слишком длинный
    if len(full_context) > max_context_length:
        full_context = full_context[:max_context_length] + "\n... (truncated)"
    
    return full_context
