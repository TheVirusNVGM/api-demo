"""
SSE Streaming версия build-board endpoint
Полная копия логики из index.py с прогрессом для обхода 100-сек лимита Cloudflare
"""

import time
import uuid
import json
import threading
from collections import defaultdict


def build_board_with_sse_full(
    data, g, DEEPSEEK_API_KEY, SUPABASE_URL, SUPABASE_KEY, 
    CONNECTOR_MODS, BOARD_LAYOUT, CATEGORY_COLORS,
    get_rate_limiter, build_modpack_v2, build_modpack_v3,
    resolve_dependencies, get_fabric_compat_manager,
    save_modpack_build, generate_modpack_summary
):
    """
    Полная копия логики build-board с SSE стримингом
    
    Отправляет события:
    - progress: {stage, message, percent}
    - complete: {success, board_state, build_id, ...}
    - error: {error, message}
    """
    try:
        start_time = time.time()
        stage_timings = {}
        last_heartbeat = time.time()
        
        def send_sse(event_type, data_dict):
            """Форматирует SSE событие"""
            event_data = json.dumps(data_dict)
            return f"event: {event_type}\ndata: {event_data}\n\n"
        
        def send_heartbeat():
            """Отправляет keepalive комментарий для Cloudflare"""
            return f": heartbeat {int(time.time())}\n\n"
        
        # Валидация
        yield send_sse('progress', {'stage': 'validation', 'message': 'Validating request...', 'percent': 2})
        
        if not data or 'prompt' not in data:
            yield send_sse('error', {'error': 'Invalid request', 'message': 'prompt is required'})
            return
        
        prompt = data['prompt']
        mc_version = data.get('mc_version', '1.21.1')
        mod_loader = data.get('mod_loader', 'fabric')
        current_mods = data.get('current_mods', [])
        max_mods = data.get('max_mods', 30)
        project_id = data.get('project_id', 'ai-generated-modpack')
        fabric_compat_mode = data.get('fabric_compat_mode', False)
        
        print(f"\n{'='*80}")
        print(f"[SSE BUILD] Starting SSE stream...")
        print(f"   Prompt: {prompt}")
        print(f"   Current mods: {len(current_mods)}")
        print(f"   Version: {mc_version}, Loader: {mod_loader}, Max: {max_mods}")
        print(f"{'='*80}\n")
        
        # Rate limiting
        yield send_sse('progress', {'stage': 'rate_limit', 'message': 'Checking rate limits...', 'percent': 5})
        
        rate_limiter = get_rate_limiter(SUPABASE_URL, SUPABASE_KEY)
        allowed, error_msg = rate_limiter.check_limit(
            user_id=g.user_id,
            subscription_tier=g.subscription_tier,
            max_mods=max_mods
        )
        
        if not allowed:
            print(f"⛔ [Rate Limit] {g.user_id} blocked: {error_msg}")
            yield send_sse('error', {'error': 'Rate limit exceeded', 'message': error_msg})
            return
        
        # Выбор версии API
        use_v3 = data.get('use_v3_architecture', True)
        use_v2 = data.get('use_v2_architecture', False)
        
        if use_v3:
            build_func = build_modpack_v3
            print("[V3] Using V3 Architecture-First")
        elif use_v2:
            build_func = build_modpack_v2
            print("[V2] Using V2 Enhanced")
        
        # AI Mod Selection (with heartbeat to prevent QUIC timeout)
        yield send_sse('progress', {'stage': 'ai_selection', 'message': 'AI is selecting mods (this may take 1-2 minutes)...', 'percent': 15})
        
        try:
            print(f"[SSE] 🤖 Calling {build_func.__name__}...")
            print(f"[SSE] ⏰ Starting heartbeat thread to keep QUIC connection alive...")
            stage_start = time.time()
            
            # Run build_func in thread while sending heartbeats
            result_container = {'result': None, 'exception': None}
            
            def run_build():
                try:
                    result_container['result'] = build_func(
                        prompt=prompt,
                        mc_version=mc_version,
                        mod_loader=mod_loader,
                        current_mods=current_mods,
                        max_mods=max_mods,
                        fabric_compat_mode=fabric_compat_mode,
                        deepseek_key=DEEPSEEK_API_KEY,
                        supabase_url=SUPABASE_URL,
                        supabase_key=SUPABASE_KEY,
                        pipeline_id=str(uuid.uuid4())
                    )
                except Exception as e:
                    result_container['exception'] = e
            
            build_thread = threading.Thread(target=run_build, daemon=True)
            build_thread.start()
            
            # Send heartbeats every 15 seconds while building (keep connection alive)
            heartbeat_counter = 0
            while build_thread.is_alive():
                build_thread.join(timeout=15.0)
                
                if build_thread.is_alive():
                    heartbeat_counter += 1
                    yield send_heartbeat()
            
            # Check for exception
            if result_container['exception']:
                raise result_container['exception']
            
            result = result_container['result']
            elapsed = time.time() - stage_start
            stage_timings['Mod Selection'] = elapsed
            print(f"[SSE] ✅ AI selection complete in {elapsed:.1f}s: {len(result.get('mods', []))} mods selected")
        except KeyboardInterrupt:
            print(f"❌ [SSE] AI Selection interrupted by user")
            yield send_sse('error', {'error': 'Request cancelled', 'message': 'Build cancelled by user'})
            return
        except Exception as e:
            print(f"❌ [SSE] AI Selection failed: {e}")
            import traceback
            traceback.print_exc()
            yield send_sse('error', {'error': 'AI selection failed', 'message': str(e)})
            return
        
        # Dependency Resolution
        yield send_sse('progress', {'stage': 'dependencies', 'message': 'Resolving dependencies...', 'percent': 40})
        
        stage_start = time.time()
        deps_before = len(result['mods'])
        # Получаем Fabric Compatibility моды для фильтрации
        fabric_compat_manager = get_fabric_compat_manager()
        FABRIC_FIX_IDS = fabric_compat_manager.config['auto_enable_triggers']['connector_mods']
        
        result['mods'] = resolve_dependencies(
            selected_mods=result['mods'],
            mc_version=mc_version,
            mod_loader=mod_loader,
            supabase_url=SUPABASE_URL,
            supabase_key=SUPABASE_KEY,
            fabric_compat_mode=fabric_compat_mode,
            fabric_fix_ids=FABRIC_FIX_IDS
        )
        deps_added = len(result['mods']) - deps_before
        stage_timings['Dependency Resolution'] = time.time() - stage_start
        
        # Architecture Refiner (V3)
        planned_architecture = result.get('planned_architecture')
        
        if planned_architecture:
            yield send_sse('progress', {'stage': 'architecture', 'message': 'Refining architecture...', 'percent': 55})
            
            try:
                from architecture_refiner import refine_architecture
                
                print("\n[ARCHITECTURE REFINER] Refining categories")
                
                refiner_start = time.time()
                refined_architecture = refine_architecture(
                    initial_architecture=planned_architecture,
                    mods=result['mods'],
                    user_prompt=prompt,
                    deepseek_key=DEEPSEEK_API_KEY
                )
                
                if refined_architecture:
                    result['planned_architecture'] = refined_architecture
                    planned_architecture = refined_architecture
                    stage_timings['Architecture Refiner'] = time.time() - refiner_start
            except Exception as e:
                print(f"⚠️ [SSE] Architecture Refiner failed: {e}")
                import traceback
                traceback.print_exc()
                # Не критично - продолжаем без рефайнера
                print("⚠️ Continuing without architecture refinement...")
        
        # Fabric Compatibility
        yield send_sse('progress', {'stage': 'fabric_compat', 'message': 'Adding compatibility mods...', 'percent': 65})
        
        stage_start = time.time()
        fabric_compat_manager = get_fabric_compat_manager()
        FABRIC_FIX_IDS = fabric_compat_manager.config['auto_enable_triggers']['connector_mods']
        
        if fabric_compat_mode:
            print("\n🔧 Fabric Compat Mode enabled...")
            
            fabric_fix_mods = fabric_compat_manager.fetch_compatibility_mods(
                mod_loader=mod_loader,
                mc_version=mc_version,
                supabase_url=SUPABASE_URL,
                supabase_key=SUPABASE_KEY
            )
            
            if fabric_fix_mods:
                result['mods'] = fabric_fix_mods + result['mods']
                print(f"   ✅ Added {len(fabric_fix_mods)} compatibility mods")
        else:
            before_count = len(result['mods'])
            result['mods'] = [mod for mod in result['mods'] if mod.get('source_id', '') not in FABRIC_FIX_IDS]
            filtered_count = before_count - len(result['mods'])
            if filtered_count > 0:
                print(f"\n⚠️  Fabric Compat Mode disabled: filtered out {filtered_count} Fabric Fix mods")
        
        stage_timings['Fabric Compatibility'] = time.time() - stage_start
        
        # Save Build to DB
        yield send_sse('progress', {'stage': 'saving', 'message': 'Saving build...', 'percent': 70})
        
        pack_archetype = planned_architecture.get('meta', {}).get('pack_archetype') if planned_architecture else None
        modpack_title = f'AI Modpack ({prompt[:30]}...)'
        
        build_id = save_modpack_build(
            title=modpack_title,
            prompt=prompt,
            mc_version=mc_version,
            mod_loader=mod_loader,
            pack_archetype=pack_archetype,
            mods=result['mods'],
            supabase_url=SUPABASE_URL,
            supabase_key=SUPABASE_KEY
        )
        print(f"💾 [Build Saved] build_id={build_id}")
        
        # Category Organization
        yield send_sse('progress', {'stage': 'organizing', 'message': 'Organizing into categories...', 'percent': 75})
        
        category_map = {}
        
        if planned_architecture:
            # V3 Architecture-based categorization
            try:
                from architecture_refiner import distribute_mods_to_categories
                
                stage_start = time.time()
                fabric_fix_mods = [mod for mod in result['mods'] if mod.get('source_id', '') in FABRIC_FIX_IDS]
                # КРИТИЧНО: Передаём ВСЕ моды включая зависимости, чтобы они не потерялись
                # distribute_mods_to_categories сам отделит библиотеки от gameplay модов
                all_mods_for_distribution = [mod for mod in result['mods'] if mod.get('source_id', '') not in FABRIC_FIX_IDS]
                
                ai_category_map = distribute_mods_to_categories(
                    categories=planned_architecture['categories'],
                    mods=all_mods_for_distribution,  # ВСЕ моды включая зависимости
                    user_prompt=prompt,
                    deepseek_key=DEEPSEEK_API_KEY
                )
                stage_timings['Mod Distribution'] = time.time() - stage_start
            except Exception as e:
                print(f"⚠️ [SSE] Mod Distribution failed: {e}")
                import traceback
                traceback.print_exc()
                # Fallback to simple categorization
                ai_category_map = {}
                print("⚠️ Using fallback categorization...")
            
            # Initialize all categories
            for category in planned_architecture.get('categories', []):
                cat_name = category['name']
                category_map[cat_name] = ai_category_map.get(cat_name, [])
            
            # Add fallback categories
            for cat_name, mods_list in ai_category_map.items():
                if cat_name not in category_map:
                    category_map[cat_name] = mods_list
            
            category_map['General'] = []
            
            # Fabric Compatibility category
            if fabric_compat_mode and fabric_fix_mods:
                category_map['Fabric Compatibility'] = fabric_fix_mods
            else:
                if fabric_fix_mods:
                    category_map['General'].extend(fabric_fix_mods)
            
            # Unassigned mods go to General
            # Используем source_id для проверки, так как slug может быть None
            assigned_mods = set()
            for mods_list in ai_category_map.values():
                for mod in mods_list:
                    mod_id = mod.get('source_id') or mod.get('slug') or mod.get('project_id')
                    if mod_id:
                        assigned_mods.add(mod_id)
            
            # Проверяем ВСЕ моды из result['mods'], а не только regular_mods
            # чтобы не потерять зависимости
            unassigned_mods = []
            unassigned_dependencies = []
            
            for mod in result['mods']:
                mod_id = mod.get('source_id') or mod.get('slug') or mod.get('project_id')
                if mod_id and mod_id not in assigned_mods:
                    unassigned_mods.append(mod)
                    # Отдельно отслеживаем зависимости
                    if mod.get('_added_as_dependency', False):
                        unassigned_dependencies.append(mod)
            
            if unassigned_mods:
                print(f"   ⚠️  Found {len(unassigned_mods)} unassigned mods")
                
                # КРИТИЧНО: Зависимости должны попасть в библиотечную категорию
                if unassigned_dependencies:
                    print(f"      ⚠️  CRITICAL: {len(unassigned_dependencies)} dependencies not assigned!")
                    for dep in unassigned_dependencies[:5]:
                        dep_name = dep.get('name', dep.get('slug', 'Unknown'))
                        print(f"         - {dep_name} (source_id: {dep.get('source_id', 'unknown')[:8]}...)")
                    if len(unassigned_dependencies) > 5:
                        print(f"         ... and {len(unassigned_dependencies) - 5} more dependencies")
                    
                    # Ищем библиотечную категорию
                    library_category = None
                    for cat_name in category_map.keys():
                        cat_lower = cat_name.lower()
                        if 'library' in cat_lower or 'archive' in cat_lower or 'foundation' in cat_lower or 'api' in cat_lower:
                            library_category = cat_name
                            break
                    
                    if library_category:
                        category_map[library_category].extend(unassigned_dependencies)
                        print(f"      ✅ Auto-placed {len(unassigned_dependencies)} dependencies into '{library_category}'")
                    else:
                        # Создаём библиотечную категорию на основе промпта
                        prompt_lower = prompt.lower()
                        if 'medieval' in prompt_lower or 'fantasy' in prompt_lower or 'castle' in prompt_lower:
                            library_category = 'Castle Foundations'
                        elif 'tech' in prompt_lower or 'automation' in prompt_lower:
                            library_category = 'Core Systems'
                        else:
                            library_category = 'Essential Libraries'
                        category_map[library_category] = unassigned_dependencies
                        print(f"      ✅ Created '{library_category}' category for {len(unassigned_dependencies)} dependencies")
                    
                    # Убираем зависимости из unassigned_mods
                    unassigned_mods = [m for m in unassigned_mods if not m.get('_added_as_dependency', False)]
                
                # Остальные нераспределённые моды идём в General
                if unassigned_mods:
                    category_map['General'].extend(unassigned_mods)
                    print(f"   ✅ Placed {len(unassigned_mods)} unassigned mods into 'General'")
        else:
            # Simple categorization
            category_map = defaultdict(list)
            for mod in result['mods']:
                category = mod.get('_ai_category', 'General')
                category_map[category].append(mod)
        
        # Generate Modpack Summary
        yield send_sse('progress', {'stage': 'summary', 'message': 'Generating modpack summary...', 'percent': 90})
        
        try:
            stage_start = time.time()
            
            # Prepare categories for summary (need to match format expected by generate_modpack_summary)
            summary_categories = []
            for i, (cat_name, cat_mods) in enumerate(category_map.items()):
                if cat_mods:
                    summary_categories.append({
                        'id': f'cat-{i}',  # ← generate_modpack_summary expects 'id' field
                        'title': cat_name,
                        'name': cat_name,
                        'mods': cat_mods
                    })
            
            modpack_summary = generate_modpack_summary(
                prompt=prompt,
                categories=summary_categories,
                mods=result['mods'],
                mc_version=mc_version,
                mod_loader=mod_loader,
                deepseek_key=DEEPSEEK_API_KEY
            )
            stage_timings['Modpack Summary'] = time.time() - stage_start
        except Exception as e:
            print(f"⚠️ [SSE] Modpack Summary generation failed: {e}")
            import traceback
            traceback.print_exc()
            # Fallback to basic summary
            dependencies_count = len([m for m in result['mods'] if m.get('_added_as_dependency', False)])
            gameplay_mods_count = len(result['mods']) - dependencies_count
            
            modpack_summary = {
                'title': f'AI Modpack: {prompt[:50]}',
                'description': 'AI-generated modpack',
                'key_features': [],
                'category_descriptions': [],
                'stats': {
                    'total_mods': len(result['mods']),
                    'gameplay_mods': gameplay_mods_count,  # ← Лаунчер требует это поле!
                    'dependencies': dependencies_count,
                    'categories': len(category_map)
                }
            }
            print("⚠️ Using fallback summary...")
        
        # Update build title
        if build_id and modpack_summary.get('title'):
            try:
                import requests
                headers = {
                    'apikey': SUPABASE_KEY,
                    'Authorization': f'Bearer {SUPABASE_KEY}',
                    'Content-Type': 'application/json'
                }
                url = f"{SUPABASE_URL}/rest/v1/modpack_builds?id=eq.{build_id}"
                requests.patch(url, headers=headers, json={'title': modpack_summary['title']}, timeout=10)
                print(f"✅ [Build Updated] Title: {modpack_summary['title']}")
            except:
                pass
        
        # Create board_state.json with proper positioning
        yield send_sse('progress', {'stage': 'finalizing', 'message': 'Finalizing board state...', 'percent': 95})
        
        from datetime import datetime, UTC
        
        board_state = {
            "project_id": project_id,
            "camera": {
                "scale": 1.0,
                "tx": 0.0,
                "ty": 0.0
            },
            "mods": [],
            "categories": [],
            "updated_at": datetime.now(UTC).isoformat(),
            "_ai_generated": True,
            "_batch_download": True,
            "_ai_build_id": str(build_id) if build_id else None,
            "aiSummary": modpack_summary,  # ← Rust BoardState требует это поле!
            "fabricCompatMode": False  # Will be set to True later if needed
        }
        
        # Category colors mapping
        category_colors = {
            'optimization': ['#fbbf24', '#f59e0b'],
            'performance': ['#fbbf24', '#f59e0b'],
            'library': ['#8b5cf6', '#7c3aed'],
            'libraries': ['#8b5cf6', '#7c3aed'],
            'api': ['#8b5cf6', '#7c3aed'],
            'graphics': ['#10b981', '#059669'],
            'visual': ['#10b981', '#059669'],
            'shader': ['#10b981', '#059669'],
            'content': ['#ec4899', '#db2777'],
            'gameplay': ['#ec4899', '#db2777'],
            'world': ['#3b82f6', '#2563eb'],
            'worldgen': ['#3b82f6', '#2563eb'],
            'utility': ['#6366f1', '#4f46e5'],
            'tool': ['#6366f1', '#4f46e5'],
            'storage': ['#14b8a6', '#0d9488'],
            'tech': ['#06b6d4', '#0891b2'],
            'magic': ['#a855f7', '#9333ea'],
            'adventure': ['#f97316', '#ea580c'],
            'decoration': ['#84cc16', '#65a30d'],
            'building': ['#84cc16', '#65a30d'],
            'general': ['#64748b', '#475569'],
            'fabric': ['#f43f5e', '#e11d48'],
            'compat': ['#f43f5e', '#e11d48'],
            'other': ['#64748b', '#475569']
        }
        
        # Positioning constants (synchronized with boardConstants.ts)
        MOD_WIDTH = 240
        MOD_HEIGHT = 80
        MOD_GAP = 10
        CATEGORY_HEADER = 40
        CATEGORY_PADDING_TOP = 8
        CATEGORY_PADDING_BOTTOM = 8
        CATEGORY_WIDTH = 255
        CATEGORY_SPACING_X = 350
        CATEGORY_SPACING_Y = 100
        START_X = 100
        START_Y = 100
        
        current_x = START_X
        current_y = START_Y
        max_height_in_row = 0
        categories_per_row = 4
        category_index = 0
        
        for category_name, mods_in_category in category_map.items():
            if not mods_in_category:
                continue
            
            # Calculate category height
            mod_count = len(mods_in_category)
            category_height = CATEGORY_HEADER + CATEGORY_PADDING_TOP + \
                            (mod_count * MOD_HEIGHT) + \
                            ((mod_count - 1) * MOD_GAP) + \
                            CATEGORY_PADDING_BOTTOM
            
            # Move to new row if needed
            if category_index > 0 and category_index % categories_per_row == 0:
                current_x = START_X
                current_y += max_height_in_row + CATEGORY_SPACING_Y
                max_height_in_row = 0
            
            # Smart color matching
            category_lower = category_name.lower()
            colors = category_colors['other']  # Default
            
            for key, color_pair in category_colors.items():
                if key in category_lower:
                    colors = color_pair
                    break
            
            # Unique category ID
            category_id = f"ai-category-{category_name.lower().replace(' ', '-')}-{int(datetime.now(UTC).timestamp() * 1000)}"
            
            # Create category
            board_state['categories'].append({
                "id": category_id,
                "title": category_name,
                "position": {"x": current_x, "y": current_y},
                "size": {"width": CATEGORY_WIDTH, "height": category_height},
                "color1": colors[0],
                "color2": colors[1]
            })
            
            # Add mods to category
            for mod_index, mod in enumerate(mods_in_category):
                # Mod position (centered in category)
                mod_x = current_x + (CATEGORY_WIDTH - MOD_WIDTH) / 2
                mod_y = current_y + CATEGORY_HEADER + CATEGORY_PADDING_TOP + \
                        mod_index * (MOD_HEIGHT + MOD_GAP)
                
                mod_node = {
                    "project_id": mod.get('source_id', mod['slug']),
                    "slug": mod['slug'],
                    "position": {"x": mod_x, "y": mod_y},
                    "title": mod['name'],
                    "icon_url": mod.get('icon_url'),
                    "description": mod.get('summary', mod.get('description', '')[:200]),
                    "file_name": None,
                    "unique_id": f"{mod['slug']}_{int(datetime.now(UTC).timestamp())}_{mod_index}",
                    "is_disabled": False,
                    "cached_dependencies": [],
                    "dependencies_fetched": False,
                    "category_id": category_id,
                    "category_index": mod_index
                }
                
                board_state['mods'].append(mod_node)
            
            # Update position for next category
            current_x += CATEGORY_SPACING_X
            max_height_in_row = max(max_height_in_row, category_height)
            category_index += 1
        
        # Auto-enable fabricCompatMode if Fabric Compatibility category exists
        has_fabric_category = any(
            cat['title'] == 'Fabric Compatibility' 
            for cat in board_state['categories']
        )
        
        if has_fabric_category:
            board_state['fabricCompatMode'] = True
            print("🔧 Auto-enabled fabricCompatMode")
        
        print(f"[OK] Generated board_state.json with {len(board_state['mods'])} mods and {len(board_state['categories'])} categories")
        
        # Increment usage counter
        try:
            rate_limiter = get_rate_limiter(SUPABASE_URL, SUPABASE_KEY)
            total_tokens = result.get('_pipeline', {}).get('total_tokens', 0) if '_pipeline' in result else 0
            rate_limiter.increment_usage(g.user_id, tokens_used=total_tokens)
        except Exception as e:
            print(f"⚠️  Failed to increment usage: {e}")
        
        # Timing summary
        total_time = time.time() - start_time
        
        print("\n" + "=" * 80)
        print("⏱️  [TIMING SUMMARY]")
        print("=" * 80)
        
        sorted_stages = sorted(stage_timings.items(), key=lambda x: x[1], reverse=True)
        for stage_name, duration in sorted_stages:
            percentage = (duration / total_time * 100) if total_time > 0 else 0
            print(f"   {stage_name:30s} {duration:6.2f}s ({percentage:5.1f}%)")
        
        print("-" * 80)
        print(f"   {'TOTAL':30s} {total_time:6.2f}s (100.0%)")
        print("=" * 80)
        
        # Complete!
        yield send_sse('complete', {
            'success': True,
            'board_state': board_state,
            'build_id': build_id,
            'explanation': result.get('explanation', ''),
            'summary': modpack_summary,
            'stats': {
                'total_mods': len(board_state['mods']),
                'prompt': prompt,
                'mc_version': mc_version,
                'mod_loader': mod_loader,
                'total_time': round(total_time, 2)
            },
            'percent': 100
        })
        
    except Exception as e:
        print(f"❌ SSE Error: {e}")
        import traceback
        traceback.print_exc()
        
        yield send_sse('error', {
            'error': 'Internal server error',
            'message': str(e)
        })

