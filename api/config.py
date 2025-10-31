"""
Centralized configuration for AI API
"""
import os

# API Keys (from environment variables)
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

# ASTRAL OAuth server URL больше не используется - проверка токенов через Supabase Auth API

# Validate environment variables
if not DEEPSEEK_API_KEY:
    raise ValueError("❌ DEEPSEEK_API_KEY not found in environment variables. Please set it in .env file")
if not SUPABASE_URL:
    raise ValueError("❌ SUPABASE_URL not found in environment variables. Please set it in .env file")
if not SUPABASE_KEY:
    raise ValueError("❌ SUPABASE_KEY not found in environment variables. Please set it in .env file")

# DeepSeek API pricing (per 1M tokens)
DEEPSEEK_INPUT_COST = 0.14
DEEPSEEK_OUTPUT_COST = 0.28

# Essential libraries (auto-added if missing)
ESSENTIAL_LIBRARIES = [
    'fabric-api',
    'cloth-config',
]

# Fabric compatibility connector mods
CONNECTOR_MODS = ['u58R1TMW', 'Aqlf1Shp', 'FYpiwiBR']

# BM25 search parameters
BM25_K1 = 1.5  # Saturation parameter
BM25_B = 0.75  # Length normalization parameter

# Category synonyms for smart matching
CATEGORY_SYNONYMS = {
    'optimization': {
        'optimization', 'performance', 'fps-boost', 'performance-required',
        'lightweight', 'memory-optimizations', 'culling', 'client-performance',
        'performance-friendly', 'lag-reduction'
    },
    'graphics': {
        'graphics', 'shaders', 'visual', 'rendering', 'lighting-effects',
        'post-processing', 'aesthetic-enhancement'
    },
    'utility': {
        'utility', 'quality-of-life', 'qol', 'convenience', 'utility-mod'
    },
    'worldgen': {
        'world-generation', 'worldgen', 'biomes', 'terrain', 'terrain-features'
    },
}

# Board positioning constants (synced with boardConstants.ts)
BOARD_LAYOUT = {
    'MOD_WIDTH': 240,
    'MOD_HEIGHT': 80,
    'MOD_GAP': 10,
    'CATEGORY_HEADER': 40,
    'CATEGORY_PADDING_TOP': 8,
    'CATEGORY_PADDING_BOTTOM': 8,
    'CATEGORY_WIDTH': 255,
    'CATEGORY_SPACING_X': 350,
    'CATEGORY_SPACING_Y': 100,
    'START_X': 100,
    'START_Y': 100,
    'CATEGORIES_PER_ROW': 4,
}

# Category colors
CATEGORY_COLORS = {
    'fabric': ('#ff9500', '#000000'),
    'performance': ('#22c55e', '#16a34a'),
    'library': ('#3b82f6', '#2563eb'),
    'utility': ('#f59e0b', '#d97706'),
    'graphics': ('#ec4899', '#db2777'),
    'world': ('#10b981', '#059669'),
    'gameplay': ('#8b5cf6', '#7c3aed'),
    'combat': ('#ef4444', '#dc2626'),
    'technology': ('#06b6d4', '#0891b2'),
    'magic': ('#a855f7', '#9333ea'),
    'food': ('#84cc16', '#65a30d'),
    'building': ('#f97316', '#ea580c'),
    'transportation': ('#14b8a6', '#0d9488'),
    'adventure': ('#eab308', '#ca8a04'),
    'quality': ('#f59e0b', '#d97706'),
    'multiplayer': ('#8b5cf6', '#7c3aed'),
    'other': ('#6b7280', '#4b5563')
}
