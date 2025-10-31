# 🧠 ASTRAL AI API - Technical Architecture

## 📋 System Overview

ASTRAL AI API is an **intelligent modpack builder** using advanced **Conditional RAG Architecture**. The system automatically adapts its processing pipeline based on request complexity and type.

### **Key Innovation: Conditional Flow Routing**

Unlike traditional fixed-pipeline systems, ASTRAL uses **intelligent routing** that chooses the optimal architecture based on user intent:

- **Architecture-First Flow** → Complex themed modpacks (50-200+ mods)
- **Classic Flow** → Simple additions and performance packs (5-50 mods)

---

## 🏗️ V3 Architecture - Conditional Pipeline

### **High-Level Flow**

```
┌─────────────────────────────────────────────────────────────┐
│                     USER REQUEST                             │
│  "Create a medieval fantasy modpack with 100+ mods"         │
└────────────────────┬────────────────────────────────────────┘
                     ↓
┌────────────────────────────────────────────────────────────┐
│  LAYER 0: Query Planner (DeepSeek AI)                      │
│  ────────────────────────────────────────────────          │
│  • Analyzes user intent and complexity                     │
│  • Determines request_type:                                │
│    - simple_add: "add sodium and lithium"                  │
│    - performance: "optimize for low-end PC"                │
│    - themed_pack: "medieval RPG modpack"                   │
│  • Sets use_architecture_matcher flag                      │
│  • Creates optimized search plan                           │
└────────────────────┬───────────────────────────────────────┘
                     ↓
           ┌─────────┴─────────┐
           ↓                   ↓
    ┌──────────────┐    ┌─────────────────┐
    │ THEMED PACK  │    │ SIMPLE/PERF     │
    │ (Architecture│    │ (Classic Flow)  │
    │  -First)     │    │                 │
    └──────┬───────┘    └────────┬────────┘
           ↓                     ↓
       [FLOW A]              [FLOW B]
```

---

## 🎭 Flow A: Architecture-First (Themed Modpacks)

**Triggered when:**
- request_type = `themed_pack`
- use_architecture_matcher = `true`
- User describes complex theme/style
- Requests 20+ mods

### **Step-by-Step Process:**

#### **1️⃣ Architecture Matcher**

Finds similar reference modpacks for pattern learning.

```python
# api/architecture_matcher.py
find_reference_modpacks(
    user_prompt="medieval fantasy with magic",
    mc_version="1.21.1",
    mod_loader="fabric",
    limit=10
)
```

**What it does:**
- Semantic search through 1000+ parsed modpacks
- Uses vector embeddings to find thematically similar packs
- Returns top 10 most relevant reference modpacks

**Output:**
```json
{
  "reference_modpacks": [
    {
      "title": "Medieval Minecraft",
      "architecture": {
        "capabilities": ["combat.weapons", "building.medieval", ...],
        "providers": { "combat.weapons": ["Epic Knights", ...] }
      }
    }
  ]
}
```

---

#### **2️⃣ Capability Pattern Extraction**

Analyzes reference modpacks to understand common patterns.

```python
# api/architecture_planner.py
extract_capability_patterns(
    reference_modpacks=[...],
    mc_version="1.21.1",
    mod_loader="fabric"
)
```

**What it does:**
- Counts capability frequencies across reference packs
- Identifies "baseline mods" (present in 70%+ of similar packs)
- Builds capability → mod provider mappings

**Output:**
```json
{
  "top_capabilities": [
    "combat.weapons", "building.medieval", "magic.spells", ...
  ],
  "baseline_mods": [
    {"name": "Epic Knights", "source_id": "...", "capabilities": [...]},
    ...
  ],
  "capability_frequency": {
    "combat.weapons": 8,
    "building.medieval": 7
  }
}
```

---

#### **3️⃣ Architecture Planner**

Plans the modpack's category structure using AI.

```python
# api/architecture_planner.py
plan_architecture(
    user_prompt="medieval fantasy",
    reference_modpacks=[...],
    capability_patterns={...},
    max_mods=100
)
```

**What it does:**
- DeepSeek AI analyzes user request + reference patterns
- Plans 5-12 themed categories
- Assigns required/preferred capabilities to each category
- Estimates mods per category

**Output:**
```json
{
  "categories": [
    {
      "name": "Knight's Armory",
      "description": "Weapons, armor and combat equipment",
      "required_capabilities": ["combat.weapons", "combat.armor"],
      "preferred_capabilities": ["combat.enchantment"],
      "target_mods": 12
    },
    {
      "name": "Castle Building",
      "description": "Medieval building blocks and structures",
      "required_capabilities": ["building.medieval", "building.castle"],
      "preferred_capabilities": ["decoration.medieval"],
      "target_mods": 15
    }
  ],
  "meta": {
    "pack_archetype": "medieval.combat_focused",
    "estimated_total_mods": 80
  }
}
```

---

#### **4️⃣ Capability-Based Search**

Searches for mods matching planned capabilities.

```python
# api/hybrid_search.py (enhanced mode)
execute_search_plan(
    search_plan={
        "capabilities_focus": ["combat.weapons", "building.medieval"],
        "baseline_mods": [...],
        ...
    }
)
```

**What it does:**
- Searches mods by **capabilities** (not just keywords)
- Gives priority boost to **baseline mods**
- Uses semantic + keyword search hybrid
- Filters by loader compatibility

**Output:** 80-150 candidate mods ranked by relevance

---

#### **5️⃣ Architecture-Aware Selection**

AI selects mods with category awareness.

```python
# api/final_selector.py
select_final_mods(
    candidates=[...],
    planned_architecture={...},
    max_mods=100
)
```

**What it does:**
- **Local prefiltering**: Reduces candidates from ~100 to ~50 using capability matching
- **AI selection**: DeepSeek picks best mods for each category
- Ensures balanced distribution across categories
- Avoids overloading any single category

**Output:** 50-100 selected mods with category assignments

---

#### **6️⃣ Dependency Resolution**

Adds required dependencies automatically.

```python
# api/dependency_resolver.py
resolve_dependencies(
    selected_mods=[...],
    mc_version="1.21.1",
    mod_loader="fabric"
)
```

**What it does:**
- Fetches dependency info from database
- Recursively resolves all `required` dependencies
- Checks loader compatibility
- Handles version requirements
- **No limit on dependencies** - all required deps are added

**Output:** Mods + dependencies (typically +10-20 mods)

---

#### **7️⃣ Architecture Refiner**

Adjusts categories based on actual mod selection.

```python
# api/architecture_refiner.py
refine_architecture(
    initial_architecture={...},
    mods=[...],  # after selection + dependencies
    user_prompt="medieval fantasy"
)
```

**What it does:**
- Analyzes **actual mods** that were selected
- Identifies overloaded categories (15+ mods) → splits them
- Merges tiny categories (1-3 mods) → combines related ones
- Separates libraries from gameplay mods
- Uses thematic naming based on user's request

**Example refinement:**
```
BEFORE:
- Combat (23 mods) ← overloaded
- Building (8 mods)

AFTER:
- Knight's Armory (10 mods) ← split
- Combat Mechanics (8 mods) ← split  
- Battle Skills (5 mods) ← split
- Castle Building (8 mods)
```

---

## ⚡ Flow B: Classic (Simple/Performance Requests)

**Triggered when:**
- request_type = `simple_add` or `performance`
- use_architecture_matcher = `false`
- User requests specific mods or simple optimization

### **Step-by-Step Process:**

#### **1️⃣ Hybrid Search**

Direct search without architecture planning.

```python
# api/hybrid_search.py
execute_search_plan(
    search_plan={
        "search_queries": [
            {"type": "keyword", "text": "sodium lithium iris", "weight": 0.9},
            {"type": "semantic", "text": "performance optimization", "weight": 0.6}
        ]
    }
)
```

**Search strategies:**
- **Keyword search** (BM25): Exact mod name matching
- **Semantic search** (Vector): Conceptual similarity
- **Reciprocal Rank Fusion**: Combines both results

---

#### **2️⃣ Final Selector**

AI picks best mods from candidates.

```python
# api/final_selector.py
select_final_mods(
    candidates=[...],
    user_prompt="add optimization mods",
    max_mods=15,
    planned_architecture=None  # No architecture
)
```

**Without architecture:**
- Simple scoring by relevance + popularity
- Basic diversity filtering
- Quick single AI call

---

#### **3️⃣ Dependency Resolution**
(Same as Flow A)

---

#### **4️⃣ Smart Categorizer**

Auto-categorizes mods using AI.

```python
# api/smart_categorizer.py
SmartCategorizer.categorize_mods(mods=[...])
```

**What it does:**
- Analyzes each mod's description and tags
- Groups into standard categories: Performance, Graphics, Utility, etc.
- Simpler than Architecture Refiner (no splitting/merging)

---

## 🔧 Support Systems

### **Pipeline Transparency**

Tracks everything for debugging and cost analysis.

```python
# api/pipeline_transparency.py
pipeline = create_pipeline(prompt, mc_version, mod_loader)
pipeline.track_ai_call(tokens=1234, cost=0.05)
pipeline.finalize()
```

**Tracks:**
- AI token usage (input + output)
- API costs (DeepSeek pricing)
- Search scores and rankings
- Mod selection reasoning
- Timing for each stage

---

### **Dependency Resolver**

Smart dependency management.

**Features:**
- Batch fetching (reduces DB calls)
- Loader compatibility checks
- Incompatibility detection (bidirectional)
- Recursive resolution
- No limit on dependency count

**Incompatibility checking:**
```python
# Checks both directions:
# 1. Does mod A conflict with existing mods?
# 2. Do existing mods conflict with mod A?

# Loader-specific:
# forge mod X incompatible with fabric mod Y only on forge
```

---

### **Fabric Compatibility Manager**

Auto-handles cross-loader mods.

```python
# api/fabric_compat.py
get_fabric_compat_manager().fetch_compatibility_mods(
    mod_loader="fabric",
    mc_version="1.21.1"
)
```

**Auto-adds when needed:**
- Connector (Fabric ↔ Forge bridge)
- Forgified Fabric API
- Other compatibility mods

**Triggers:**
- Detects Forge/NeoForge mods in Fabric modpack
- Checks `fabric_compat_mode` flag
- Automatically includes required bridge mods

---

### **Performance Optimizer**

Loader-specific optimization recommendations.

```python
# api/performance_optimizer.py
PerformanceOptimizer.get_recommended_mods(
    mod_loader="neoforge",
    mc_version="1.21.1"
)
```

**Handles:**
- Loader equivalents (Sodium → Embeddium on Forge)
- Version-specific mods (NeoForge 1.21.1 has Sodium, 1.20.1 doesn't)
- Core optimization stacks
- Coverage checking (render, memory, culling layers)

---

### **Feedback Learning**

System learns from user feedback.

```python
# api/feedback_processor.py
process_feedback(
    feedback_text="Sodium conflicts with Iris on 1.21.1",
    board_state={...}
)
```

**Learning mechanisms:**
1. **Incompatibility detection**: AI parses user reports, updates DB
2. **Categorization rating**: Tracks 1-5 star ratings for auto-sort quality
3. **Build tracking**: Saves all AI builds with architecture and selections
4. **Pattern analysis**: (Future) Learns from successful builds

---

## 📊 Database Schema

### **`mods` Table**

Core mods database with AI-enriched data.

```sql
CREATE TABLE mods (
    id UUID PRIMARY KEY,
    source_id TEXT UNIQUE NOT NULL,  -- Modrinth project ID
    slug TEXT,
    name TEXT,
    description TEXT,
    
    -- Vector embeddings (for semantic search)
    embedding VECTOR(384),  -- pgvector
    
    -- AI-enriched metadata
    capabilities TEXT[],    -- ["combat.weapons", "api.exposed", ...]
    tags TEXT[],           -- Custom AI tags
    semantic_tags TEXT[],  -- For clustering
    
    -- Compatibility
    loaders TEXT[],        -- ["fabric", "forge", "neoforge"]
    game_versions TEXT[],  -- ["1.21.1", "1.21", ...]
    dependencies JSONB,    -- {required: [...], optional: [...]}
    incompatibilities JSONB,  -- {forge: ["mod1"], fabric: ["mod2"]}
    
    -- Stats
    downloads INTEGER,
    updated_at TIMESTAMPTZ,
    
    -- Index
    INDEX idx_embedding ON mods USING ivfflat (embedding vector_cosine_ops)
);
```

---

### **`modpacks` Table**

Reference modpacks for pattern matching.

```sql
CREATE TABLE modpacks (
    id UUID PRIMARY KEY,
    source_id TEXT,
    title TEXT,
    slug TEXT,
    description TEXT,
    
    -- Parsed architecture
    architecture JSONB,  -- {capabilities: [...], providers: {...}}
    mc_version TEXT,
    mod_loader TEXT,
    
    -- For semantic search
    embedding VECTOR(384),
    
    -- Stats
    downloads INTEGER,
    categories TEXT[],
    
    INDEX idx_modpack_embedding ON modpacks USING ivfflat (embedding vector_cosine_ops)
);
```

---

### **`modpack_builds` Table**

User-generated builds for feedback learning.

```sql
CREATE TABLE modpack_builds (
    id UUID PRIMARY KEY,
    title TEXT,
    prompt TEXT,  -- Original user request
    mc_version TEXT,
    mod_loader TEXT,
    pack_archetype TEXT,  -- "medieval.combat_focused"
    
    -- Generated architecture
    architecture JSONB,
    
    -- User feedback
    feedback JSONB,  -- {rating: 4, issues: [...]}
    created_at TIMESTAMPTZ
);
```

---

### **`ai_sort_sessions` Table**

Tracks auto-sort quality for learning.

```sql
CREATE TABLE ai_sort_sessions (
    id UUID PRIMARY KEY,
    mc_version TEXT,
    mod_loader TEXT,
    creativity FLOAT,
    user_prompt TEXT,
    
    -- Input/output
    input_mods TEXT[],  -- Source IDs
    categories JSONB,   -- Generated categories
    
    -- Feedback
    rating INTEGER,  -- 1-5 stars
    feedback_submitted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ
);
```

---

## 🎯 AI Integration Points

### **DeepSeek API Usage**

The system uses DeepSeek for 4 key AI calls:

#### **1. Query Planner** (Always)
```
Input: User prompt + context
Output: JSON search plan
Tokens: ~800-1500
Cost: ~$0.001
```

#### **2. Architecture Planner** (Themed packs only)
```
Input: Prompt + reference modpack patterns
Output: JSON category structure
Tokens: ~2000-4000
Cost: ~$0.003-$0.006
```

#### **3. Final Selector** (Always)
```
Input: Candidate mods + architecture (if themed)
Output: JSON selected mods with reasoning
Tokens: ~3000-8000
Cost: ~$0.005-$0.012
```

#### **4. Architecture Refiner** (Themed packs only)
```
Input: Initial architecture + actual mods
Output: JSON refined categories
Tokens: ~2500-5000
Cost: ~$0.004-$0.008
```

**Total cost per request:**
- Simple requests: ~$0.006-$0.013
- Themed modpacks: ~$0.013-$0.026

---

## 🔍 Search Technology

### **Hybrid Search Strategy**

Combines three search methods for optimal results:

#### **1. Vector Search (Semantic)**
```python
# Using sentence-transformers (all-MiniLM-L6-v2)
embedding = model.encode(query)
results = supabase.rpc('search_mods_semantic', {
    'query_embedding': embedding,
    'match_count': 100
})
```

**Advantages:**
- Understands meaning and context
- Finds conceptually similar mods
- Language-agnostic (works with Russian, English, etc.)

**Used for:**
- Themed requests ("medieval", "cyberpunk")
- Conceptual queries ("survival progression", "magic spells")

---

#### **2. BM25 Search (Keyword)**
```python
# Custom BM25 implementation
score = (idf * tf * (k1 + 1)) / (tf + k1 * (1 - b + b * doc_len / avg_doc_len))
```

**Advantages:**
- Exact term matching
- Works for specific mod names
- Fast and efficient

**Used for:**
- Specific mod requests ("sodium", "create mod")
- Performance keywords ("fps boost", "optimization")

---

#### **3. Reciprocal Rank Fusion**
```python
# Combines semantic + keyword results
for mod in semantic_results:
    score += 1 / (60 + semantic_rank[mod])
for mod in keyword_results:
    score += 1 / (60 + keyword_rank[mod])
```

**Advantages:**
- Best of both worlds
- Balanced ranking
- Reduces bias from single method

---

## 🧪 Advanced Features

### **Capability-Based Matching**

Unlike traditional keyword matching, capabilities provide **semantic mod classification**.

**Example capabilities:**
```
combat.weapons         → Weapons mods
combat.armor          → Armor mods
building.medieval     → Medieval building blocks
magic.spells          → Spell systems
api.exposed           → Libraries providing APIs
performance.render    → Rendering optimization
```

**Why better than tags:**
- More granular (50+ capabilities vs 20 tags)
- Hierarchical (combat.weapons.melee)
- AI-generated from mod descriptions
- Enables precise category planning

---

### **Baseline Mod Detection**

Automatically includes "essential" mods for themed packs.

**Detection:**
- Mod appears in 70%+ of similar reference modpacks
- Tagged as `baseline-mod` in database
- Examples: Epic Knights for medieval combat, Create for tech packs

**Behavior:**
- Baseline mods get priority in search
- Always included if relevant to theme
- Ensures quality foundation for modpack

---

### **Cross-Loader Compatibility**

Intelligent handling of mod loader differences.

**Scenarios:**

1. **Fabric → NeoForge equivalents:**
   ```
   Sodium (Fabric) → Sodium (NeoForge 1.21.1+) or Embeddium (1.20.1)
   ```

2. **Fabric mods on NeoForge:**
   ```
   If fabric_compat_mode=true:
   → Add Connector + Forgified Fabric API
   → Allow Fabric mods that don't use Fabric API
   ```

3. **Hard exclusions:**
   ```
   Fabric API itself → NEVER added on Forge/NeoForge
   (even with compat mode enabled)
   ```

---

## 📈 Performance Optimizations

### **Final Selector Optimization**

Reduced AI processing time from ~20s to ~5s:

**Before:**
- Sent 100+ mods to AI
- Single monolithic prompt
- Long processing time

**After:**
- Local prefiltering: 100 → 50 mods using capability scores
- Reduced AI candidates to MAX_AI_CANDIDATES (50)
- Per-category limits (6 mods max per category during prefilter)
- Faster AI response with better quality

---

### **Batch Database Queries**

Minimizes database round-trips:

```python
# Before: 50 individual queries
for mod_id in dependency_ids:
    fetch_mod(mod_id)  # 50 DB calls

# After: 1 batch query
fetch_mods_batch(dependency_ids)  # 1 DB call
```

**Reduces dependency resolution time by 80%**

---

## 🎨 Categorization Systems

The system uses **two different categorization approaches** based on flow:

### **Architecture Refiner** (Themed packs - Flow A)

**Characteristics:**
- Plans categories BEFORE mod selection
- Uses capabilities for matching
- AI refines categories after seeing actual mods
- Splits/merges categories dynamically
- Thematic naming based on user request

**Example:**
```
User: "Medieval fantasy modpack"
→ Categories: "Knight's Armory", "Castle Building", "Mystical Arts"
```

---

### **Smart Categorizer** (Simple packs - Flow B)

**Characteristics:**
- Categorizes AFTER mod selection
- Uses standard category names
- Simpler AI analysis
- Fixed category set

**Example:**
```
User: "Performance optimization"
→ Categories: "Performance", "Graphics", "Utility"
```

---

## 🚀 Future Improvements

### **Planned Features:**

1. **Semantic Clusters** (from SEMANTIC_ARCHITECTURE.md v1)
   - Pre-built "skeletons" for common modpack types
   - Faster building for known themes
   - Database table: `semantic_clusters`

2. **Co-occurrence Graph**
   - "Mods that go well together" recommendations
   - Learn from successful modpack combinations
   - Database table: `mod_cooccurrence`

3. **User Preference Learning**
   - Track individual user's modpack building history
   - Personalized recommendations
   - Adaptive category naming

4. **Multi-stage Architecture Planning**
   - Iterative refinement with user feedback
   - "Show me the plan, then build" workflow
   - Interactive category adjustment

---

## 🛠️ Development Notes

### **Code Organization**

```
api/
├── Core Pipeline
│   ├── query_planner.py          # Entry point, request analysis
│   ├── hybrid_search.py           # Search execution
│   └── final_selector.py          # Mod selection
│
├── Architecture System (Flow A)
│   ├── architecture_matcher.py    # Reference modpack search
│   ├── architecture_planner.py    # Category planning
│   └── architecture_refiner.py    # Category refinement
│
├── Build Versions
│   ├── ai_build_v3.py             # Main (Conditional architecture)
│   ├── ai_build_v2.py             # Fallback (Classic flow)
│   └── ai_build.py                # Legacy fallback
│
├── Support Systems
│   ├── dependency_resolver.py     # Dependency management
│   ├── fabric_compat.py           # Cross-loader support
│   ├── performance_optimizer.py   # Optimization rules
│   ├── pipeline_transparency.py   # Tracking & metrics
│   ├── smart_categorizer.py       # Flow B categorization
│   ├── modpack_summary.py         # AI summaries
│   ├── feedback_processor.py      # Learning from feedback
│   └── build_recorder.py          # Build tracking
│
└── API & Config
    ├── index.py                   # Flask server
    └── config.py                  # Configuration
```

---

### **Testing & Debugging**

**Scripts:**
```
scripts/
├── check_caps.py                  # Check mod capabilities in DB
└── clear_incompatibilities.py     # Clear incompatibility data
```

**Transparency:**
```python
# Every build includes detailed tracking:
{
  "_pipeline": {
    "pipeline_id": "...",
    "total_tokens": 8234,
    "total_cost": 0.018,
    "stages": [...],
    "ai_calls": [...]
  }
}
```

---

## 💡 Key Design Decisions

### **Why Conditional Architecture?**

**Problem:** One-size-fits-all pipelines don't work well for both:
- Simple requests ("add 3 mods")
- Complex requests ("create 100-mod themed modpack")

**Solution:** Route based on request analysis
- Simple → Fast classic flow
- Complex → Comprehensive architecture planning

**Benefits:**
- ⚡ Fast for simple requests (~3-5s)
- 🎯 High quality for complex requests (~10-15s)
- 💰 Cost-efficient (only use heavy AI when needed)

---

### **Why Capabilities over Tags?**

**Tags** (Modrinth):
- Broad categories (20-30 tags)
- Multiple mods share same tag
- Hard to differentiate

**Capabilities** (AI-generated):
- Granular classification (50+ capabilities)
- Hierarchical structure
- Enables precise matching

**Example:**
```
Tag: "combat"
→ Too broad (weapons? armor? mechanics?)

Capabilities: ["combat.weapons.melee", "combat.armor.heavy", "combat.mechanics.dodge"]
→ Precise and actionable for categorization
```

---

### **Why Reference Modpack Matching?**

**Insight:** Popular modpacks represent **proven combinations** that work well together.

**Approach:**
1. Parse 1000+ successful modpacks from Modrinth
2. Extract capability patterns
3. Use as templates for new builds

**Benefits:**
- Learn from community expertise
- Avoid common incompatibilities
- Ensure baseline quality

---

## 📚 Further Reading

- **Query Planner**: See `api/query_planner.py` for request analysis logic
- **Architecture Planning**: See `api/architecture_planner.py` for category planning
- **Hybrid Search**: See `api/hybrid_search.py` for search implementation
- **Dependency Resolution**: See `api/dependency_resolver.py` for dependency logic

---

**Author:** ASTRAL Team  
**Version:** V3 (Conditional Architecture)  
**Last Updated:** 2025-10-31
