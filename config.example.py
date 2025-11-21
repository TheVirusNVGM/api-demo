"""
Configuration Template for ASTRAL AI API
Copy this file to config.py and fill in your credentials
"""

# =============================================================================
# API KEYS (DO NOT COMMIT REAL KEYS TO GIT)
# =============================================================================

# DeepSeek AI API Key
# Get your key from: https://platform.deepseek.com/
DEEPSEEK_API_KEY = "your-deepseek-api-key-here"

# Supabase Configuration
# Get from: https://supabase.com/dashboard/project/_/settings/api
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_KEY = "your-supabase-anon-key-here"

# =============================================================================
# RATE LIMITING & PRICING
# =============================================================================

# DeepSeek Pricing (as of 2024)
DEEPSEEK_INPUT_COST = 0.14  # USD per 1M input tokens
DEEPSEEK_OUTPUT_COST = 0.28  # USD per 1M output tokens

# Token Limits per Subscription Tier
RATE_LIMITS = {
    'free': {
        'daily_tokens': 500_000,  # ~$0.07/day
        'monthly_tokens': 10_000_000,  # ~$1.40/month
    },
    'premium': {
        'daily_tokens': 2_000_000,  # ~$0.28/day
        'monthly_tokens': 50_000_000,  # ~$7.00/month
    },
    'pro': {
        'daily_tokens': 10_000_000,  # ~$1.40/day
        'monthly_tokens': 200_000_000,  # ~$28.00/month
    },
    'test': {
        'daily_tokens': 100_000_000,  # Unlimited for testing
        'monthly_tokens': 1_000_000_000,
    }
}

# =============================================================================
# MOD DATABASE
# =============================================================================

# Essential Libraries (automatically added to all modpacks)
ESSENTIAL_LIBRARIES = [
    'fabric-api',  # Fabric API (for Fabric loader)
    'cloth-config',  # Config library
    'architectury-api',  # Cross-loader API
]

# Baseline Mods (performance optimizations, added by default)
# These are tagged in database with 'baseline-mod' tag
# Examples: Sodium, Lithium, ModernFix, FerriteCore

# =============================================================================
# AI MODEL CONFIGURATION
# =============================================================================

# Embedding Model for Semantic Search
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIMENSIONS = 384

# DeepSeek Model
LLM_MODEL = "deepseek-chat"
LLM_TIMEOUT = 90  # seconds

# =============================================================================
# FEATURE FLAGS
# =============================================================================

# Enable Fabric Compatibility Mode (Connector/Sinytra)
FABRIC_COMPAT_ENABLED = True

# Enable Crash Doctor
CRASH_DOCTOR_ENABLED = True

# Enable Build Recording (save all builds to database)
BUILD_RECORDING_ENABLED = True

# Enable Request Logging
REQUEST_LOGGING_ENABLED = True

# =============================================================================
# SERVER CONFIGURATION
# =============================================================================

# Flask Server
FLASK_HOST = "127.0.0.1"
FLASK_PORT = 5000
FLASK_DEBUG = False

# CORS (Cross-Origin Resource Sharing)
# Add your frontend URLs here
ALLOWED_ORIGINS = [
    "http://localhost:5173",  # Vite dev server
    "http://localhost:3000",  # React dev server
    "tauri://localhost",  # Tauri app (production)
    "http://tauri.localhost",  # Tauri app (dev)
]

# =============================================================================
# MODRINTH API
# =============================================================================

MODRINTH_API_URL = "https://api.modrinth.com/v2"

# =============================================================================
# LOGGING
# =============================================================================

LOG_LEVEL = "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_FILE = "api.log"
LOG_MAX_BYTES = 10_000_000  # 10 MB
LOG_BACKUP_COUNT = 5

# =============================================================================
# NOTES
# =============================================================================

"""
SETUP INSTRUCTIONS:

1. Copy this file to config.py:
   cp config.example.py config.py

2. Get DeepSeek API Key:
   - Visit: https://platform.deepseek.com/
   - Create account & generate API key
   - Paste into DEEPSEEK_API_KEY

3. Get Supabase Credentials:
   - Visit: https://supabase.com/dashboard
   - Create new project
   - Go to Settings > API
   - Copy URL and anon key
   - Paste into SUPABASE_URL and SUPABASE_KEY

4. Setup Database:
   - Run database/schema.sql in Supabase SQL Editor
   - Enable pgvector extension
   - Configure Row Level Security (RLS)

5. Install Dependencies:
   pip install -r requirements.txt

6. Run Server:
   python api/index.py

For detailed setup guide, see: SETUP.md
"""

