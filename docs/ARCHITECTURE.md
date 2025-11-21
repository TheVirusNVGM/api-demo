# 🏗️ ASTRAL AI - Technical Architecture

## Table of Contents
- [System Overview](#system-overview)
- [AI Modpack Builder Pipeline](#ai-modpack-builder-pipeline)
- [Crash Doctor Agent](#crash-doctor-agent)
- [Database Schema](#database-schema)
- [Authentication & Security](#authentication--security)
- [Performance Optimizations](#performance-optimizations)
- [Deployment Architecture](#deployment-architecture)

---

## System Overview

ASTRAL AI is a **multi-layered AI pipeline** that transforms natural language prompts into fully-functional Minecraft modpacks. The system combines:

- **Large Language Models** (DeepSeek) for understanding and planning
- **Semantic Search** (sentence-transformers + pgvector) for mod discovery  
- **Structured Filtering** (capability system) for precision matching
- **Autonomous Agents** (Crash Doctor) for error recovery

### Key Design Principles

1. **Architecture-First**: Plan modpack structure before selecting mods
2. **Reference Learning**: Learn from existing modpacks
3. **Hybrid Search**: Combine semantic + keyword search for best results
4. **Fail-Safe**: Always include dependencies and optimization mods
5. **Streaming**: Real-time progress updates via SSE

---

## AI Modpack Builder Pipeline

### Layer 0: Query Planner

**Purpose**: Understand user intent and generate search queries

**Input**: User prompt (e.g., "Create a medieval magic modpack")

**Process**:
```python
def plan_query(user_prompt, mc_version, mod_loader):
    system_prompt = """
    You are a Minecraft modpack expert. Analyze the user's request
    and create a search plan.
    
    Generate:
    1. 5-6 semantic search queries (diverse aspects)
    2. Keywords for exact matching
    3. Required capabilities (must-have features)
    4. Preferred capabilities (nice-to-have features)
    """
    
    response = deepseek.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
    )
    
    return parse_search_plan(response)
```

**Output Example**:
```json
{
  "queries": [
    {"text": "magic spells wizardry medieval fantasy", "weight": 0.9},
    {"text": "combat swords knights armor weapons", "weight": 0.8},
    {"text": "medieval structures castles villages", "weight": 0.7}
  ],
  "keywords": ["magic", "medieval", "fantasy", "combat"],
  "required_capabilities": [
    "magic.spellcasting",
    "combat.melee",
    "worldgen.structures"
  ],
  "preferred_capabilities": [
    "magic.rituals",
    "crafting.expansion"
  ]
}
```

---

### Layer 1.5: Architecture Planner

**Purpose**: Create modpack structure based on reference modpacks

**Innovation**: This is the **secret sauce** of ASTRAL AI. Instead of blindly selecting mods, we first plan the modpack architecture.

**Process**:

1. **Find Similar Modpacks**:
```sql
-- Semantic search for reference modpacks
SELECT 
    name, 
    summary, 
    architecture,
    1 - (embedding <=> query_embedding) AS similarity
FROM modpacks
WHERE architecture IS NOT NULL
ORDER BY embedding <=> query_embedding
LIMIT 5
```

2. **Extract Capability Patterns**:
```python
def extract_patterns(reference_modpacks):
    """
    Analyzes which capabilities frequently appear together
    Example: magic.spellcasting often pairs with crafting.expansion
    """
    capability_cooccurrence = defaultdict(int)
    
    for modpack in reference_modpacks:
        for cat in modpack['architecture']['categories']:
            caps = cat['required_capabilities']
            for cap1, cap2 in combinations(caps, 2):
                capability_cooccurrence[(cap1, cap2)] += 1
    
    return capability_cooccurrence
```

3. **Plan Categories**:
```python
def plan_architecture(user_prompt, reference_patterns, max_mods):
    system_prompt = f"""
    Based on {len(reference_modpacks)} similar modpacks, plan categories.
    
    Reference patterns:
    {format_patterns(reference_patterns)}
    
    Create 15-25 categories with:
    - Descriptive name
    - Target mod count
    - Required capabilities
    - Preferred capabilities
    
    Total target: {max_mods} mods
    """
    
    response = deepseek_api.call(system_prompt, user_prompt)
    return parse_architecture(response)
```

**Output Example**:
```json
{
  "categories": [
    {
      "name": "Arcane Foundation",
      "description": "Core magic libraries and APIs",
      "target_mods": 8,
      "required_capabilities": ["api.exposed", "magic.core"],
      "preferred_capabilities": ["dependency.library"]
    },
    {
      "name": "Spellcasting & Rituals",
      "description": "Magic systems and spell progression",
      "target_mods": 12,
      "required_capabilities": ["magic.spellcasting", "magic.rituals"],
      "preferred_capabilities": ["progression.system"]
    }
  ]
}
```

---

### Layer 1: Hybrid Search

**Purpose**: Find candidate mods using multiple search strategies

**Process**:

1. **Vector Search** (Semantic):
```python
def vector_search(query_text, required_caps, limit=40):
    # Generate embedding for query
    query_embedding = sentence_transformer.encode(query_text)
    
    # Search database with capability filter
    sql = """
    SELECT 
        *,
        1 - (embedding <=> %s::vector) AS similarity
    FROM mods
    WHERE 
        -- Capability filter
        capabilities && %s::text[]
        -- Loader compatibility
        AND (%s = ANY(loaders) OR 'universal' = ANY(loaders))
        -- Minimum downloads
        AND downloads > 5000
    ORDER BY embedding <=> %s::vector
    LIMIT %s
    """
    
    return execute_query(sql, [
        query_embedding, 
        required_caps,
        mod_loader,
        query_embedding,
        limit
    ])
```

2. **Keyword Search** (Full-Text):
```python
def keyword_search(keywords, required_caps, limit=150):
    sql = """
    SELECT *,
        ts_rank(
            to_tsvector('english', name || ' ' || summary || ' ' || description),
            plainto_tsquery('english', %s)
        ) AS rank
    FROM mods
    WHERE
        to_tsvector('english', name || ' ' || summary) 
        @@ plainto_tsquery('english', %s)
        AND capabilities && %s::text[]
    ORDER BY rank DESC
    LIMIT %s
    """
    
    return execute_query(sql, [keywords, keywords, required_caps, limit])
```

3. **Result Fusion**:
```python
def fuse_results(vector_results, keyword_results, query_weight):
    """
    Combines results using Reciprocal Rank Fusion (RRF)
    """
    scores = defaultdict(float)
    
    for rank, mod in enumerate(vector_results, 1):
        scores[mod['slug']] += query_weight / (60 + rank)
    
    for rank, mod in enumerate(keyword_results, 1):
        scores[mod['slug']] += (1 - query_weight) / (60 + rank)
    
    # Merge and deduplicate
    all_mods = {mod['slug']: mod for mod in vector_results + keyword_results}
    
    # Sort by combined score
    return sorted(
        all_mods.values(),
        key=lambda m: scores[m['slug']],
        reverse=True
    )
```

**Output**: 200-300 candidate mods, ranked by relevance

---

### Layer 2: Final Selector

**Purpose**: Select best mods using AI with architecture awareness

**Key Innovation**: Local pre-filtering before AI

**Process**:

1. **Pre-Filter by Architecture** (300 → 50 mods):
```python
def preselect_candidates(candidates, architecture, max_mods):
    """
    Reduces candidate list using architecture-based scoring
    WITHOUT calling AI (fast!)
    """
    picked = []
    
    for category in architecture['categories']:
        # Score each candidate for this category
        scored = []
        for mod in candidates:
            score = calculate_match_score(mod, category)
            if score > 0:
                scored.append((score, mod))
        
        # Take top N for this category
        scored.sort(reverse=True)
        top_mods = [mod for _, mod in scored[:6]]
        picked.extend(top_mods)
    
    # Deduplicate and limit
    return deduplicate(picked)[:50]

def calculate_match_score(mod, category):
    """
    Scores mod relevance to category without AI
    """
    mod_caps = set(mod['capabilities'])
    req_caps = set(category['required_capabilities'])
    pref_caps = set(category['preferred_capabilities'])
    
    # Required capabilities match (most important)
    req_match = len(mod_caps & req_caps) * 5.0
    
    # Preferred capabilities match (bonus)
    pref_match = len(mod_caps & pref_caps) * 2.0
    
    # Popularity (normalized)
    popularity = min(mod['downloads'] / 100_000, 3.0)
    
    return req_match + pref_match + popularity
```

2. **AI Final Selection** (50 → max_mods):
```python
def ai_select_mods(preselected_candidates, architecture, max_mods):
    system_prompt = f"""
    You are selecting mods for a modpack.
    
    Architecture plan:
    {format_architecture(architecture)}
    
    Rules:
    1. Select EXACTLY {max_mods} mods
    2. Fill each category according to its target count
    3. Prioritize mods with required capabilities
    4. Ensure diversity (don't pick too many similar mods)
    5. ALWAYS include library/API mods
    6. Check for conflicts in descriptions
    
    Output JSON with selected mod slugs and reasons.
    """
    
    candidates_text = format_candidates(preselected_candidates)
    
    response = deepseek_api.call(
        system_prompt,
        f"Candidates:\n{candidates_text}\n\nSelect {max_mods} best mods."
    )
    
    return parse_selection(response)
```

**Why This Works**:
- **Pre-filtering**: Reduces AI input from 300 to 50 mods (faster, cheaper)
- **Architecture awareness**: AI sees the planned structure, selects coherently
- **Quality over quantity**: 50 highly relevant mods > 300 mediocre ones

---

### Dependency Resolution

**Purpose**: Add required dependencies automatically

**Process**:

```python
def resolve_dependencies(selected_mods, mc_version, mod_loader):
    all_deps = set()
    
    # Collect dependencies
    for mod in selected_mods:
        for dep in mod['dependencies']:
            if dep['dependency_type'] == 'required':
                # Check version compatibility
                if is_version_compatible(dep, mc_version):
                    all_deps.add(dep['project_id'])
    
    # Fetch dependency mods from database
    dep_mods = fetch_mods_batch(list(all_deps))
    
    # Filter by loader
    compatible_deps = [
        mod for mod in dep_mods
        if mod_loader in mod['loaders'] or 'universal' in mod['loaders']
    ]
    
    # Check for conflicts
    resolve_conflicts(compatible_deps)
    
    return compatible_deps
```

**Result**: +30-50 dependencies added automatically

---

### Architecture Refiner

**Purpose**: Organize final mods into categories and generate descriptions

**Process**:

```python
def refine_architecture(initial_architecture, final_mods):
    """
    AI organizes mods into categories and generates descriptions
    """
    # Classify mods
    gameplay_mods = [m for m in final_mods if not is_library(m)]
    library_mods = [m for m in final_mods if is_library(m)]
    
    system_prompt = f"""
    Organize {len(gameplay_mods)} gameplay mods into categories.
    
    Initial plan had {len(initial_architecture['categories'])} categories.
    You may merge/split categories if needed.
    
    For each category:
    1. Choose descriptive name
    2. Write 1-2 sentence description
    3. Assign appropriate mods
    
    Output JSON with refined architecture.
    """
    
    response = deepseek_api.call(system_prompt, format_mods(gameplay_mods))
    refined = parse_refined_architecture(response)
    
    # Add library category automatically
    refined['categories'].insert(0, {
        'name': 'Libraries & APIs',
        'description': 'Core dependencies required by other mods',
        'mods': library_mods
    })
    
    return refined
```

---

## Crash Doctor Agent

### Overview

Crash Doctor is an **autonomous AI agent** that analyzes Minecraft crash logs and suggests fixes.

**Pipeline**: Log → Sanitize → Analyze → Plan → Patch → Record

### Components

#### 1. Log Sanitizer

**Purpose**: Clean crash log, extract relevant information

```python
def sanitize_crash_log(crash_log):
    """
    Removes:
    - Personal paths (C:/Users/YourName/...)
    - IP addresses
    - UUIDs
    - Timestamps (keep relative time only)
    
    Extracts:
    - Error message
    - Stack trace
    - Mod list
    - Minecraft version
    - Loader version
    """
    # Remove PII
    sanitized = remove_user_paths(crash_log)
    sanitized = remove_ip_addresses(sanitized)
    
    # Extract structured info
    error_info = extract_error_trace(sanitized)
    mod_list = extract_mod_list(sanitized)
    
    return {
        'sanitized_log': sanitized,
        'error_message': error_info['message'],
        'stack_trace': error_info['stack'],
        'mods_in_log': mod_list,
        'extracted_info': {
            'mc_version': extract_mc_version(crash_log),
            'mod_loader': detect_loader(crash_log)
        }
    }
```

#### 2. Crash Analyzer (AI)

**Purpose**: Identify root cause and problematic mods

```python
def analyze_crash(sanitized_log, board_state, deepseek_key):
    system_prompt = """
    You are a Minecraft crash expert. Analyze crash logs and identify:
    
    1. Root cause (what went wrong)
    2. Problematic mods (which mods caused it)
    3. Error type:
       - mod_conflict: Two mods are incompatible
       - missing_dependency: Required mod not installed
       - outdated_mod: Mod version too old
       - mixin_error: Mixin transformation failed
       - memory: Out of memory
       - fabric_on_forge: Fabric mod on Forge loader
    
    Output JSON with structured analysis.
    """
    
    user_prompt = f"""
    Crash log:
    {sanitized_log[:5000]}
    
    Current mods:
    {format_board_state(board_state)}
    
    Analyze this crash.
    """
    
    response = deepseek_api.call(system_prompt, user_prompt)
    return parse_crash_analysis(response)
```

**Output Example**:
```json
{
  "root_cause": "Mod conflict between OptiFine and Sodium",
  "confidence": 0.95,
  "problematic_mods": [
    {
      "mod_name": "OptiFine",
      "reason": "Conflicts with Sodium (both modify rendering)"
    }
  ],
  "error_type": "mod_conflict",
  "suggested_fixes": [
    {
      "action": "remove_mod",
      "target_mod": "OptiFine",
      "priority": "critical"
    }
  ]
}
```

#### 3. Fix Planner

**Purpose**: Validate fixes and create executable plan

**Key Feature**: **Modrinth Integration** for real-time validation

```python
def plan_fixes(ai_analysis, board_state, mc_version, mod_loader):
    operations = []
    warnings = []
    
    for fix in ai_analysis['suggested_fixes']:
        if fix['action'] == 'add_mod':
            # Validate mod exists on Modrinth
            modrinth_info = search_modrinth(
                query=fix['target_mod'],
                version=mc_version,
                loader=mod_loader
            )
            
            if modrinth_info:
                operations.append({
                    'action': 'add_mod',
                    'target_mod': modrinth_info['title'],
                    'mod_source_id': modrinth_info['project_id'],
                    'mod_slug': modrinth_info['slug'],
                    'reason': fix['reason'],
                    'priority': fix['priority']
                })
            else:
                warnings.append(f"Mod '{fix['target_mod']}' not found on Modrinth")
        
        elif fix['action'] == 'remove_mod':
            # Validate mod exists in board_state
            if mod_exists_in_board(fix['target_mod'], board_state):
                operations.append(fix)
            else:
                warnings.append(f"Mod '{fix['target_mod']}' not in current modpack")
    
    return {
        'operations': operations,
        'warnings': warnings
    }
```

#### 4. Board Patcher

**Purpose**: Apply fixes to `board_state.json`

```python
def patch_board_state(board_state, operations):
    patched_board = deepcopy(board_state)
    applied_ops = []
    
    for op in operations:
        if op['action'] == 'remove_mod':
            # Find and remove mod
            patched_board['mods'] = [
                m for m in patched_board['mods']
                if m['name'].lower() != op['target_mod'].lower()
            ]
            applied_ops.append(op)
        
        elif op['action'] == 'disable_mod':
            # Mark mod as disabled
            for mod in patched_board['mods']:
                if mod['name'].lower() == op['target_mod'].lower():
                    mod['enabled'] = False
                    applied_ops.append(op)
                    break
        
        # NOTE: add_mod is handled by launcher UI, not here
        # (launcher downloads from Modrinth using provided mod_source_id)
    
    return {
        'patched_board_state': patched_board,
        'applied_operations': applied_ops
    }
```

---

## Database Schema

### Mods Table

```sql
CREATE TABLE mods (
    id SERIAL PRIMARY KEY,
    source_id TEXT UNIQUE NOT NULL,  -- Modrinth project_id
    slug TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    summary TEXT,
    description TEXT,
    downloads BIGINT DEFAULT 0,
    followers INTEGER DEFAULT 0,
    
    -- Minecraft compatibility
    versions TEXT[] DEFAULT '{}',
    loaders TEXT[] DEFAULT '{}',  -- forge, fabric, neoforge, quilt
    
    -- Semantic search
    embedding vector(384),  -- sentence-transformers embedding
    
    -- Capability system (80+ structured capabilities)
    capabilities TEXT[] DEFAULT '{}',
    
    -- Tags (user-defined)
    tags TEXT[] DEFAULT '{}',
    
    -- Modrinth categories
    modrinth_categories TEXT[] DEFAULT '{}',
    
    -- Dependencies (JSONB for complex structure)
    dependencies JSONB DEFAULT '[]',
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_mods_embedding ON mods USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_mods_capabilities ON mods USING gin (capabilities);
CREATE INDEX idx_mods_versions ON mods USING gin (versions);
CREATE INDEX idx_mods_loaders ON mods USING gin (loaders);
CREATE INDEX idx_mods_downloads ON mods (downloads DESC);
```

### Modpacks Table

```sql
CREATE TABLE modpacks (
    id SERIAL PRIMARY KEY,
    user_id UUID REFERENCES auth.users(id),
    name TEXT NOT NULL,
    summary TEXT,
    
    -- Minecraft info
    mc_version TEXT NOT NULL,
    mod_loader TEXT NOT NULL,
    
    -- Semantic search
    embedding vector(384),
    
    -- Modpack architecture (planned categories)
    architecture JSONB,
    
    -- Mods in modpack
    mods JSONB NOT NULL,  -- Array of mod objects
    
    -- Metadata
    mod_count INTEGER DEFAULT 0,
    downloads BIGINT DEFAULT 0,
    
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_modpacks_embedding ON modpacks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_modpacks_user_id ON modpacks (user_id);
```

### Crash Doctor Sessions Table

```sql
CREATE TABLE crash_doctor_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id),
    
    -- Input
    crash_log TEXT NOT NULL,
    game_log TEXT,
    mc_version TEXT,
    mod_loader TEXT,
    
    -- Analysis result
    root_cause TEXT,
    confidence FLOAT,
    suggestions JSONB,  -- Array of fix suggestions
    warnings JSONB DEFAULT '[]',
    
    -- Board state (before/after)
    board_state JSONB,
    
    -- Metadata
    total_tokens INTEGER,
    analysis_time FLOAT,
    
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_crash_sessions_user_id ON crash_doctor_sessions (user_id);
CREATE INDEX idx_crash_sessions_created_at ON crash_doctor_sessions (created_at DESC);
```

---

## Authentication & Security

### JWT Verification

```python
def verify_jwt_token(token):
    """
    Verifies JWT token from Supabase Auth
    """
    try:
        # Get Supabase JWT secret
        jwt_secret = SUPABASE_KEY
        
        # Decode and verify
        payload = jwt.decode(
            token,
            jwt_secret,
            algorithms=['HS256'],
            audience='authenticated'
        )
        
        return {
            'valid': True,
            'user_id': payload['sub'],
            'role': payload['role']
        }
    except jwt.ExpiredSignatureError:
        return {'valid': False, 'error': 'Token expired'}
    except jwt.InvalidTokenError:
        return {'valid': False, 'error': 'Invalid token'}
```

### Rate Limiting

```python
def check_rate_limit(user_id, endpoint):
    """
    Checks if user has exceeded their daily/monthly token limit
    """
    # Get user subscription tier
    subscription = get_user_subscription(user_id)
    
    # Get current usage
    usage = get_token_usage(user_id)
    
    # Check limits
    daily_limit = RATE_LIMITS[subscription]['daily_tokens']
    monthly_limit = RATE_LIMITS[subscription]['monthly_tokens']
    
    if usage['daily'] >= daily_limit:
        raise RateLimitError('Daily limit exceeded')
    
    if usage['monthly'] >= monthly_limit:
        raise RateLimitError('Monthly limit exceeded')
    
    return True
```

---

## Performance Optimizations

### 1. Batch Database Queries

```python
# BAD: N+1 queries
for mod in mods:
    dependencies = db.query("SELECT * FROM mods WHERE source_id = %s", [mod['dep_id']])

# GOOD: Single batch query
dep_ids = [mod['dep_id'] for mod in mods]
dependencies = db.query("SELECT * FROM mods WHERE source_id = ANY(%s)", [dep_ids])
```

### 2. HNSW Index for Vector Search

```sql
-- Creates approximate nearest neighbor index
CREATE INDEX idx_mods_embedding 
ON mods 
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
```

**Performance**:
- Exact search (brute force): ~500ms for 100k mods
- HNSW index: ~5ms for 100k mods (100x faster!)
- Recall: ~95% (acceptable trade-off)

### 3. SSE Streaming for Long Operations

```python
def generate_sse_stream():
    """
    Sends progress updates as SSE events
    Keeps connection alive, bypasses Cloudflare 100s timeout
    """
    yield send_sse('progress', {'stage': 'planning', 'percent': 10})
    
    # Long AI operation
    result = call_deepseek_api()
    
    yield send_sse('progress', {'stage': 'searching', 'percent': 50})
    
    # More work...
    
    yield send_sse('complete', {'result': final_result})
```

### 4. Pre-Filtering Before AI

```python
# Reduces AI input from 300 → 50 mods
# Saves ~70% tokens, faster response
preselected = preselect_by_architecture(candidates, architecture)
final = ai_select_mods(preselected, max_mods)
```

---

## Deployment Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     CLOUDFLARE                          │
│  - DDoS Protection                                      │
│  - SSL/TLS                                              │
│  - Cloudflare Tunnel (secure connection to origin)     │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│              ORIGIN SERVER (VPS/Dedicated)              │
│                                                         │
│  ┌───────────────────────────────────────────────────┐ │
│  │         Waitress WSGI Server (Python)             │ │
│  │  - 8 worker threads                               │ │
│  │  - Handles concurrent requests                    │ │
│  └─────────────────┬─────────────────────────────────┘ │
│                    │                                   │
│  ┌─────────────────▼─────────────────────────────────┐ │
│  │           Flask Application                       │ │
│  │  - REST API endpoints                             │ │
│  │  - SSE streaming                                  │ │
│  │  - JWT authentication                             │ │
│  └─────────────────┬─────────────────────────────────┘ │
│                    │                                   │
└────────────────────┼───────────────────────────────────┘
                     │
        ┌────────────┴────────────┐
        ▼                         ▼
┌────────────────┐      ┌──────────────────┐
│   SUPABASE     │      │   DEEPSEEK AI    │
│ - PostgreSQL   │      │ - LLM API        │
│ - pgvector     │      │ - GPT-compatible │
│ - Auth (JWT)   │      │ - 0.14¢/1M tokens│
│ - RLS          │      └──────────────────┘
└────────────────┘
```

---

## Conclusion

ASTRAL AI demonstrates:

1. **Architecture-First Planning**: Novel approach to modpack generation
2. **Hybrid AI System**: Combines LLMs, semantic search, and structured filtering
3. **Production-Ready**: Authentication, rate limiting, error handling, monitoring
4. **Autonomous Agents**: Crash Doctor as a multi-tool AI agent
5. **Performance**: Optimized for speed (streaming, indexing, batch operations)

This system showcases advanced AI engineering, database optimization, and real-world production considerations.

---

**Want to learn more?** Check out:
- [README.md](../README.md) - Project overview
- [CRASH_DOCTOR_PLAN.md](CRASH_DOCTOR_PLAN.md) - Autonomous agent design
- [API_INTEGRATION.md](../API_INTEGRATION.md) - Frontend integration guide

