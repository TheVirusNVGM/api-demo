"""
Modrinth Parser - полный парсинг модов с Modrinth в Supabase
Особенности:
- Проверка существующих модов в БД
- Пакетная обработка (по 100 записей)
- Обработка зависимостей через API версий
- Генерация AI summary и тегов
- Генерация embeddings
- Обработка таймаутов и ошибок
"""

import requests
import json
import time
import re
import os
import sys
from typing import List, Dict, Any, Optional
from pathlib import Path
from sentence_transformers import SentenceTransformer
from concurrent.futures import ThreadPoolExecutor, as_completed

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Добавляем api/ в путь для импорта config
sys.path.insert(0, str(Path(__file__).parent.parent / 'api'))
from config import SUPABASE_URL, SUPABASE_KEY, DEEPSEEK_API_KEY

# Конфигурация
MODRINTH_API = "https://api.modrinth.com/v2"

BATCH_SIZE = 100
REQUEST_DELAY = 0.1  # Задержка между запросами к Modrinth (секунды)
MAX_RETRIES = 3
MAX_WORKERS = 10  # Количество параллельных потоков
SAVE_CHUNK_SIZE = 10  # Сохранять в БД каждые N модов

# Инициализация
embedding_model = SentenceTransformer('all-MiniLM-L6-v2')

# Загрузка системы тегов
tags_system_path = Path(__file__).parent.parent / "tags_system.json"
with open(tags_system_path, 'r', encoding='utf-8') as f:
    tags_system_data = json.load(f)

# Собираем все теги из категорий
AVAILABLE_TAGS = []
for category_data in tags_system_data.get('categories', {}).values():
    AVAILABLE_TAGS.extend(category_data.get('tags', []))

def get_existing_mod_ids() -> set:
    """Получить список ID модов, уже существующих в БД"""
    print("🔍 Проверка существующих модов в БД...")
    url = f"{SUPABASE_URL}/rest/v1/mods?select=source_id"
    headers = {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}'
    }
    
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    
    existing_ids = {mod['source_id'] for mod in response.json() if mod.get('source_id')}
    print(f"✅ Найдено {len(existing_ids)} существующих модов")
    return existing_ids

def search_modrinth_mods(offset: int = 0, limit: int = 100) -> Dict[str, Any]:
    """Поиск модов на Modrinth"""
    url = f"{MODRINTH_API}/search"
    params = {
        'facets': '[["project_type:mod"]]',
        'limit': limit,
        'offset': offset,
        'index': 'downloads'  # Сортировка по количеству скачиваний
    }
    
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                raise
            print(f"⚠️ Ошибка запроса к Modrinth (попытка {attempt+1}/{MAX_RETRIES}): {e}")
            time.sleep(2 ** attempt)

def get_mod_dependencies(project_id: str, slug: str) -> Dict[str, Dict[str, Any]]:
    """
    Получить зависимости мода через API версий
    Возвращает словарь вида: {project_id: {type: str, versions: list}}
    """
    url = f"{MODRINTH_API}/project/{slug}/version"
    
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 404:
                return {}
            response.raise_for_status()
            versions = response.json()
            
            if not versions:
                return {}
            
            # Берём первую (самую свежую) версию
            latest_version = versions[0]
            dependencies_dict = {}
            
            for dep in latest_version.get('dependencies', []):
                dep_project_id = dep.get('project_id')
                dep_type = dep.get('dependency_type', 'required')
                
                if dep_project_id:
                    # Получаем game_versions из этой версии
                    game_versions = latest_version.get('game_versions', [])
                    
                    if dep_project_id not in dependencies_dict:
                        dependencies_dict[dep_project_id] = {
                            'type': dep_type,
                            'versions': game_versions
                        }
            
            return dependencies_dict
            
        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                print(f"⚠️ Не удалось получить зависимости для {slug}: {e}")
                return {}
            time.sleep(1)

def strip_html_and_markdown(text: str) -> str:
    """Удаление HTML тегов, markdown разметки и ссылок (из step1)"""
    if not text:
        return ''
    
    # Удаляем HTML теги
    text = re.sub(r'<[^>]+>', ' ', text)
    
    # Удаляем markdown изображения ![alt](url)
    text = re.sub(r'!\[([^\]]*)\]\([^\)]+\)', '', text)
    
    # Удаляем markdown ссылки [text](url)
    text = re.sub(r'\[([^\]]*)\]\([^\)]+\)', r'\1', text)
    
    # Удаляем прямые URL
    text = re.sub(r'https?://[^\s]+', '', text)
    
    # Удаляем HTML сущности
    text = re.sub(r'&[a-z]+;', ' ', text)
    
    # Удаляем множественные пробелы и переносы строк
    text = re.sub(r'\s+', ' ', text)
    
    return text.strip()

def generate_ai_summary(title: str, short_desc: str, full_body: str) -> str:
    """Генерация краткого описания через DeepSeek"""
    try:
        # Очищаем от HTML и Markdown
        clean_body = strip_html_and_markdown(full_body)
        clean_short = strip_html_and_markdown(short_desc)
        
        # Используем первые 1500 символов полного описания
        full_text = clean_body[:1500] if clean_body else clean_short
        
        prompt = f"""Write a concise summary (EXACTLY 400-450 characters) in English for this Minecraft mod.

Mod: {title}
Short description: {clean_short}
Full description: {full_text}

IMPORTANT RULES:
1. Write ONLY the summary text, NO introductions like "Here is" or "Summary:"
2. Start directly with describing what the mod does
3. DO NOT end with "..." - write a complete sentence that fits naturally within 450 characters
4. Make the summary informative and complete, exactly 400-450 characters
5. If approaching 450 characters, finish the current sentence properly"""

        response = requests.post(
            'https://api.deepseek.com/v1/chat/completions',
            headers={
                'Authorization': f'Bearer {DEEPSEEK_API_KEY}',
                'Content-Type': 'application/json'
            },
            json={
                'model': 'deepseek-chat',
                'messages': [
                    {'role': 'system', 'content': 'You write EXACTLY 400-450 character summaries for Minecraft mods. Write ONLY the summary text. DO NOT use "..." at the end. Make complete sentences that fit within 450 characters.'},
                    {'role': 'user', 'content': prompt}
                ],
                'temperature': 0.3,
                'max_tokens': 200
            },
            timeout=30
        )
        
        response.raise_for_status()
        result = response.json()
        summary = result['choices'][0]['message']['content'].strip()
        
        # Удаляем мусорные вступления
        summary = summary.replace('Here is a detailed summary of the ', '').replace(' mod.', '')
        summary = summary.replace('Of course! Here is a detailed summary of the ', '')
        summary = summary.replace('**', '').replace('---', '').strip()
        
        # Удаляем заголовки типа "ModName Mod Summary"
        if summary.startswith(title):
            summary = summary[len(title):].strip()
        if 'Summary' in summary[:50]:
            summary = summary.split('Summary', 1)[-1].strip()
        if summary.startswith(':') or summary.startswith('-'):
            summary = summary[1:].strip()
        
        # Если AI не уместила в 450, обрезаем по слову (без ...)
        if len(summary) > 450:
            summary = summary[:450].rsplit(' ', 1)[0]
        
        # Проверяем минимальную длину
        if len(summary) < 300:
            # Если summary короткий, берём из full_text
            clean_body = strip_html_and_markdown(full_body)
            clean_short = strip_html_and_markdown(short_desc)
            fallback = clean_body if clean_body else clean_short
            summary = fallback[:450] if fallback else title
        
        return summary
        
    except Exception as e:
        print(f"⚠️ Ошибка генерации summary: {e}")
        clean_body = strip_html_and_markdown(full_body)
        clean_short = strip_html_and_markdown(short_desc)
        fallback = clean_body if clean_body else clean_short
        return fallback[:450] if fallback else title

def classify_mod_tags(title: str, description: str, categories: List[str]) -> List[str]:
    """Классификация тегов через DeepSeek"""
    try:
        available_tags = AVAILABLE_TAGS
        
        system_prompt = """You are a Minecraft mod analyzer. Your task is to select 5-10 most relevant tags from the list.
Return ONLY tag names separated by commas, WITHOUT explanations."""
        
        user_prompt = f"""Analyze this mod:

Title: {title}
Description: {description}
Categories: {', '.join(categories)}

Available tags:
{', '.join(available_tags)}

Select 5-10 most relevant tags."""

        response = requests.post(
            'https://api.deepseek.com/v1/chat/completions',
            headers={
                'Authorization': f'Bearer {DEEPSEEK_API_KEY}',
                'Content-Type': 'application/json'
            },
            json={
                'model': 'deepseek-chat',
                'messages': [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_prompt}
                ],
                'temperature': 0.3,
                'max_tokens': 100
            },
            timeout=30
        )
        
        response.raise_for_status()
        result = response.json()
        tags_text = result['choices'][0]['message']['content'].strip()
        selected_tags = [tag.strip() for tag in tags_text.split(',')]
        
        # Валидация тегов
        valid_tags = [tag for tag in selected_tags if tag in available_tags]
        return valid_tags[:10]  # Максимум 10 тегов
        
    except Exception as e:
        print(f"⚠️ Ошибка классификации тегов: {e}")
        return []

def generate_embedding(text: str) -> List[float]:
    """Генерация embedding вектора"""
    try:
        embedding = embedding_model.encode(text)
        return embedding.tolist()
    except Exception as e:
        print(f"⚠️ Ошибка генерации embedding: {e}")
        return [0.0] * 384  # Размерность модели all-MiniLM-L6-v2

def get_project_full_info(project_id: str) -> Dict[str, Any]:
    """Получить полную информацию о проекте (с loaders и game_versions)"""
    url = f"{MODRINTH_API}/project/{project_id}"
    
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 404:
                return {}
            response.raise_for_status()
            return response.json()
        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                print(f"⚠️ Не удалось получить инфо о проекте {project_id}: {e}")
                return {}
            time.sleep(1)

def should_process_mod(mod_data: Dict[str, Any]) -> tuple[bool, str]:
    """Проверка, нужно ли обрабатывать мод"""
    # Минимум 5k скачиваний (снижено для большего покрытия)
    downloads = mod_data.get('downloads', 0)
    if downloads < 5000:
        return (False, f"Мало скачиваний: {downloads:,}")
    
    return (True, '')

def has_modern_version(game_versions: List[str]) -> bool:
    """Проверка, что мод поддерживает 1.20.1+"""
    modern_versions = [
        '1.20.1', '1.20.2', '1.20.3', '1.20.4', '1.20.5', '1.20.6',
        '1.21', '1.21.1', '1.21.2', '1.21.3', '1.21.4', '1.21.5', '1.21.6',
        '1.21.7', '1.21.8', '1.21.9', '1.21.10'
    ]
    
    for version in game_versions:
        # Проверяем, есть ли совпадения с современными версиями
        for modern in modern_versions:
            if version.startswith(modern):
                return True
    
    return False

def process_mod(mod_data: Dict[str, Any]) -> Dict[str, Any]:
    """Обработка одного мода"""
    project_id = mod_data['project_id']
    slug = mod_data['slug']
    title = mod_data['title']
    short_description = mod_data.get('description', '')
    
    # Проверка фильтров (скачивания)
    should_process, reason = should_process_mod(mod_data)
    if not should_process:
        raise Exception(f"Пропуск: {reason}")
    
    # Получаем полную инфо о проекте (там есть loaders, game_versions и body)
    full_info = get_project_full_info(project_id)
    if full_info:
        # Обновляем mod_data полной информацией
        mod_data.update(full_info)
    
    # Проверка версий (1.20.1+)
    game_versions = mod_data.get('game_versions', [])
    if not has_modern_version(game_versions):
        raise Exception(f"Пропуск: нет современных версий (1.20.1+)")
    
    # Получаем зависимости (без задержки, параллельно)
    dependencies = get_mod_dependencies(project_id, slug)
    dependencies_json = json.dumps(dependencies) if dependencies else None
    
    # Генерируем AI summary из полного описания
    full_body = mod_data.get('body', '')
    summary = generate_ai_summary(title, short_description, full_body)
    
    # Формируем description как в step1: short + body, очищенные
    clean_short = strip_html_and_markdown(short_description)
    clean_body = strip_html_and_markdown(full_body)
    if clean_short and clean_body:
        combined_description = f"{clean_short} {clean_body}"
    elif clean_body:
        combined_description = clean_body
    elif clean_short:
        combined_description = clean_short
    else:
        combined_description = title
    
    # Классифицируем теги
    categories = mod_data.get('categories', [])
    tags = classify_mod_tags(title, short_description, categories)
    
    # Генерируем embedding из name + summary + tags (для лучшего semantic search)
    tags_text = ' '.join(tags) if tags else ''
    # Повторяем важные части для увеличения их веса в embedding
    embedding_text = f"{title} {title} {summary} {tags_text} {tags_text}"
    embedding = generate_embedding(embedding_text)
    
    # Получаем дополнительные поля
    client_side = mod_data.get('client_side', 'unknown')
    server_side = mod_data.get('server_side', 'unknown')
    
    # Формируем env (client/server/both)
    if client_side == 'required' and server_side == 'required':
        env = 'both'
    elif client_side == 'required':
        env = 'client'
    elif server_side == 'required':
        env = 'server'
    else:
        env = 'both'  # По умолчанию
    
    # Получаем loaders и versions - ОБЯЗАТЕЛЬНО
    loaders = mod_data.get('loaders', [])
    if not loaders:
        loaders = []  # Пустой массив, не null
    
    mc_versions = mod_data.get('game_versions', [])
    if not mc_versions:
        mc_versions = []  # Пустой массив, не null
    
    # Формируем links из полей API
    links = {}
    if mod_data.get('issues_url'):
        links['issues'] = mod_data['issues_url']
    if mod_data.get('source_url'):
        links['source'] = mod_data['source_url']
    if mod_data.get('wiki_url'):
        links['wiki'] = mod_data['wiki_url']
    if mod_data.get('discord_url'):
        links['discord'] = mod_data['discord_url']
    
    # Формируем запись для БД
    mod_record = {
        'source_id': project_id,
        'slug': slug,
        'name': title,
        'summary': summary,
        'description': combined_description[:3000],  # Очищенное описание (как в step1)
        'icon_url': mod_data.get('icon_url'),
        'loaders': loaders,  # Уже проверенный массив
        'mc_versions': mc_versions,  # Уже проверенный массив
        'env': env,
        'project_type': mod_data.get('project_type', 'mod'),
        'modrinth_categories': categories,
        'downloads': mod_data.get('downloads', 0),
        'followers': mod_data.get('follows', 0),
        'created_at': mod_data.get('date_created'),
        'last_updated': mod_data.get('date_modified'),
        'source': 'modrinth',
        'links': json.dumps(links) if links else None,  # JSON string
        'dependencies': dependencies_json,
        'tags': tags,
        'embedding': embedding
    }
    
    return mod_record

def save_mods_batch(mods: List[Dict[str, Any]]) -> bool:
    """Сохранение пакета модов в БД"""
    url = f"{SUPABASE_URL}/rest/v1/mods"
    headers = {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json',
        'Prefer': 'return=minimal'
    }
    
    try:
        response = requests.post(url, headers=headers, json=mods, timeout=30)
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"❌ Ошибка сохранения пакета: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"   Response: {e.response.text[:500]}")
        return False

def main():
    """Основная функция парсинга"""
    print("🚀 Запуск парсера модов Modrinth\n")
    
    # Получаем существующие моды
    existing_ids = get_existing_mod_ids()
    
    # Счётчики
    total_processed = 0
    total_added = 0
    total_skipped = 0
    offset = 2085  # Начинаем с 2085 (после последнего добавленного)
    
    while True:
        print(f"\n📥 Загрузка модов с offset={offset}...")
        
        try:
            search_result = search_modrinth_mods(offset=offset, limit=BATCH_SIZE)
            hits = search_result.get('hits', [])
            total_hits = search_result.get('total_hits', 0)
            
            if not hits:
                print("✅ Все моды обработаны!")
                break
            
            print(f"📊 Получено {len(hits)} модов (всего в Modrinth: {total_hits})")
            
            # Фильтруем новые моды
            new_mods = [mod for mod in hits if mod['project_id'] not in existing_ids]
            skipped = len(hits) - len(new_mods)
            total_skipped += skipped
            
            if skipped > 0:
                print(f"⏭️ Пропущено {skipped} существующих модов")
            
            if not new_mods:
                print("ℹ️ Нет новых модов в этой партии")
                offset += BATCH_SIZE
                continue
            
            # Обрабатываем новые моды ПАРАЛЛЕЛЬНО и сохраняем чанками
            print(f"⚙️ Обработка {len(new_mods)} новых модов ({MAX_WORKERS} потоков, сохранение каждые {SAVE_CHUNK_SIZE})...")
            processed_mods = []
            
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                # Запускаем обработку всех модов параллельно
                future_to_mod = {executor.submit(process_mod, mod_data): mod_data for mod_data in new_mods}
                
                for future in as_completed(future_to_mod):
                    mod_data = future_to_mod[future]
                    try:
                        mod_record = future.result()
                        processed_mods.append(mod_record)
                        print(f"  ✓ {mod_data.get('title', 'Unknown')}")
                        
                        # Сохраняем чанками по SAVE_CHUNK_SIZE
                        if len(processed_mods) >= SAVE_CHUNK_SIZE:
                            # Фильтруем дубликаты перед сохранением
                            unique_mods = [m for m in processed_mods if m['source_id'] not in existing_ids]
                            if unique_mods:
                                print(f"💾 Сохранение чанка из {len(unique_mods)} модов...")
                                if save_mods_batch(unique_mods):
                                    total_added += len(unique_mods)
                                    print(f"✅ Сохранено {len(unique_mods)} модов")
                                    # Добавляем в список существующих
                                    for mod in unique_mods:
                                        existing_ids.add(mod['source_id'])
                                else:
                                    print(f"⚠️ Не удалось сохранить чанк")
                            else:
                                print(f"⚠️ Все {len(processed_mods)} модов уже есть в БД")
                            processed_mods = []  # Очищаем буфер
                        
                    except Exception as e:
                        print(f"  ✗ {mod_data.get('title', 'Unknown')}: {e}")
            
            # Сохраняем оставшиеся моды
            if processed_mods:
                # Фильтруем дубликаты
                unique_mods = [m for m in processed_mods if m['source_id'] not in existing_ids]
                if unique_mods:
                    print(f"💾 Сохранение оставшихся {len(unique_mods)} модов...")
                    if save_mods_batch(unique_mods):
                        total_added += len(unique_mods)
                        print(f"✅ Сохранено {len(unique_mods)} модов")
                        for mod in unique_mods:
                            existing_ids.add(mod['source_id'])
                    else:
                        print(f"⚠️ Не удалось сохранить оставшиеся")
                else:
                    print(f"⚠️ Все {len(processed_mods)} модов уже есть в БД")
            
            total_processed += len(hits)
            offset += BATCH_SIZE
            
            # Статистика
            print(f"\n📈 Статистика:")
            print(f"   Обработано: {total_processed}")
            print(f"   Добавлено: {total_added}")
            print(f"   Пропущено: {total_skipped}")
            
        except KeyboardInterrupt:
            print("\n⚠️ Прервано пользователем")
            break
        except Exception as e:
            print(f"❌ Критическая ошибка: {e}")
            print("⏸️ Пауза 5 секунд перед продолжением...")
            time.sleep(5)
            continue
    
    print(f"\n🎉 Парсинг завершён!")
    print(f"📊 Итого обработано: {total_processed}")
    print(f"✅ Добавлено новых: {total_added}")
    print(f"⏭️ Пропущено существующих: {total_skipped}")

if __name__ == "__main__":
    main()
