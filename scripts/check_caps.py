import sys
import os

# Добавляем текущую директорию в путь
sys.path.insert(0, os.path.dirname(__file__))

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

from config import SUPABASE_URL, SUPABASE_KEY
import requests

# Проблемные моды из логов
problem_mods = [
    'modernfix', 'lithium', 'sodium', 'iris',
    'yungs-api', 'azurelib-armor', 'structure-pool-api',
    'cristel-lib', 'lithostitched', 'terrablender',
    'entity-model-features'
]

print('🔍 Fetching capabilities from database...\n')

for slug in problem_mods:
    response = requests.get(
        f'{SUPABASE_URL}/rest/v1/mods',
        headers={
            'apikey': SUPABASE_KEY,
            'Authorization': f'Bearer {SUPABASE_KEY}'
        },
        params={
            'slug': f'eq.{slug}',
            'select': 'slug,name,capabilities,tags'
        }
    )
    
    if response.status_code == 200 and response.json():
        mod = response.json()[0]
        caps = mod.get('capabilities', [])
        tags = mod.get('tags', [])
        
        print(f'📦 {slug}')
        print(f'   Name: {mod.get("name", "N/A")}')
        print(f'   Capabilities: {caps if caps else "EMPTY"}')
        print(f'   Tags (first 10): {tags[:10] if tags else "EMPTY"}')
        print()
    else:
        print(f'❌ {slug} - not found or error')
        print()
