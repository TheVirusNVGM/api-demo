"""
Очищает все поля incompatibilities в базе данных модов
Использует централизованный config.py
"""
from dotenv import load_dotenv
load_dotenv()

from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY

print('🗑️  Clearing all incompatibilities...')
print(f'📍 URL: {SUPABASE_URL}')

client = create_client(SUPABASE_URL, SUPABASE_KEY)
result = client.table('mods').update({'incompatibilities': None}).neq('id', 0).execute()

print(f'✅ Done! Cleared incompatibilities from {len(result.data)} mods')
