"""
SSE Streaming версия crash-doctor endpoint
Анализ крашлогов с прогрессом
"""

import time
import json
import threading
from crash_doctor.log_cache import get_log_cache
from crash_doctor.log_validator import validate_mods_match
from crash_doctor_recorder import save_crash_doctor_session


def analyze_crash_with_sse(
    data, user_id, DEEPSEEK_API_KEY, SUPABASE_URL, SUPABASE_KEY,
    analyze_and_fix_crash
):
    """
    SSE стриминг для анализа крашлогов
    
    Args:
        data: Данные запроса (crash_log, board_state, game_log, etc.)
        user_id: ID пользователя (передаётся напрямую, не через g, так как g недоступен в генераторе)
        DEEPSEEK_API_KEY: API ключ DeepSeek
        SUPABASE_URL: URL Supabase
        SUPABASE_KEY: Ключ Supabase
        analyze_and_fix_crash: Функция анализа краша
    
    События:
    - progress: {stage, message, percent}
    - complete: {suggestions, patched_board_state, confidence}
    - error: {error, message}
    """
    try:
        start_time = time.time()
        last_heartbeat = time.time()
        
        def send_sse(event_type, data_dict):
            """Форматирует SSE событие"""
            event_data = json.dumps(data_dict)
            return f"event: {event_type}\ndata: {event_data}\n\n"
        
        def send_heartbeat():
            """Keepalive для Cloudflare"""
            return f": heartbeat {int(time.time())}\n\n"
        
        # Валидация
        yield send_sse('progress', {'stage': 'validation', 'message': 'Validating crash log...', 'percent': 5})
        
        if not data or 'crash_log' not in data or 'board_state' not in data:
            yield send_sse('error', {'error': 'Invalid request', 'message': 'crash_log and board_state are required'})
            return
        
        crash_log = data['crash_log']
        board_state = data['board_state']
        game_log = data.get('game_log')
        mc_version = data.get('mc_version')
        mod_loader = data.get('mod_loader')
        
        # Валидация соответствия модов в crash_log и board_state
        previous_warning_hash = data.get('previous_warning_hash')  # Для отслеживания повторений
        is_valid, warning_message, warning_hash = validate_mods_match(
            crash_log=crash_log,
            board_state=board_state,
            game_log=game_log,
            previous_warning_hash=previous_warning_hash
        )
        
        if not is_valid and warning_message:
            print(f"⚠️  [CRASH DOCTOR] Mod mismatch detected: {warning_message[:100]}...")
            yield send_sse('error', {
                'error': 'Outdated crash log',
                'message': warning_message,
                'warning_hash': warning_hash,
                'suggestion': 'Please restart the game to generate a fresh crash log if the issue persists.'
            })
            return
        
        # Генерируем хеш для отслеживания (но не блокируем дубликаты)
        log_hash = None
        if user_id:
            log_cache = get_log_cache()
            # Проверяем, но НЕ блокируем - только для статистики
            is_duplicate, log_hash = log_cache.check_and_mark(user_id, crash_log, game_log)
            
            if is_duplicate:
                print(f"ℹ️  [CRASH DOCTOR] Duplicate log detected (hash: {log_hash[:8]}...), but proceeding anyway")
        
        print(f"\n{'='*80}")
        print(f"[CRASH DOCTOR] Starting crash analysis...")
        print(f"   Crash log size: {len(crash_log)} chars")
        print(f"   Board mods: {len(board_state.get('mods', []))}")
        print(f"   Version: {mc_version}, Loader: {mod_loader}")
        print(f"{'='*80}\n")
        
        # Sanitization
        yield send_sse('progress', {'stage': 'sanitization', 'message': 'Cleaning crash log...', 'percent': 15})
        yield send_heartbeat()
        
        # Analysis (долгая операция - DeepSeek) с heartbeat
        yield send_sse('progress', {'stage': 'analysis', 'message': 'AI is analyzing crash (may take 30-60 seconds)...', 'percent': 30})
        
        print("[CRASH DOCTOR] 🤖 Calling analyze_and_fix_crash...")
        print("[CRASH DOCTOR] ⏰ Starting heartbeat thread to keep QUIC connection alive...")
        
        # Run analyze_and_fix_crash in thread while sending heartbeats
        result_container = {'result': None, 'exception': None}
        
        def run_analysis():
            try:
                result_container['result'] = analyze_and_fix_crash(
                    crash_log=crash_log,
                    board_state=board_state,
                    game_log=game_log,
                    mc_version=mc_version,
                    mod_loader=mod_loader,
                    deepseek_key=DEEPSEEK_API_KEY
                )
            except Exception as e:
                result_container['exception'] = e
        
        analysis_thread = threading.Thread(target=run_analysis, daemon=True)
        analysis_thread.start()
        
        # Send heartbeats every 15 seconds while analysis is running
        while analysis_thread.is_alive():
            time.sleep(15)
            yield send_heartbeat()
            last_heartbeat = time.time()
        
        # Wait for thread to complete
        analysis_thread.join(timeout=1)
        
        if result_container['exception']:
            raise result_container['exception']
        
        result = result_container['result']
        
        yield send_heartbeat()
        
        if not result.get('success'):
            error_msg = result.get('error', 'Analysis failed')
            print(f"❌ [CRASH DOCTOR] Analysis failed: {error_msg}")
            # НЕ помечаем как успешный - можно повторить попытку
            yield send_sse('error', {'error': 'Analysis failed', 'message': error_msg})
            return
        
        # Planning fixes
        yield send_sse('progress', {'stage': 'planning', 'message': 'Planning fixes...', 'percent': 70})
        yield send_heartbeat()
        
        # Finalizing
        yield send_sse('progress', {'stage': 'finalizing', 'message': 'Creating fixed board state...', 'percent': 90})
        
        total_time = time.time() - start_time
        
        print(f"\n[CRASH DOCTOR] ✅ Analysis complete in {total_time:.1f}s")
        print(f"   Confidence: {result.get('confidence', 0.0):.2f}")
        print(f"   Suggestions: {len(result.get('suggestions', []))}")
        
        # Increment rate limiter usage после успешного анализа
        if user_id:
            try:
                from rate_limiter import get_rate_limiter
                rate_limiter = get_rate_limiter(SUPABASE_URL, SUPABASE_KEY)
                # Получаем количество токенов из результата
                token_usage = result.get('token_usage', {})
                total_tokens = token_usage.get('total_tokens', 0)
                rate_limiter.increment_usage(user_id, tokens_used=total_tokens)
                print(f"   📊 Rate limiter updated: {total_tokens} tokens")
            except Exception as e:
                print(f"   ⚠️  Failed to update rate limiter: {e}")
        
        # Сохраняем сессию в БД
        session_id = None
        if user_id:
            try:
                session_id = save_crash_doctor_session(
                    user_id=user_id,
                    crash_log=crash_log,
                    game_log=game_log,
                    mc_version=mc_version,
                    mod_loader=mod_loader,
                    root_cause=result.get('root_cause', ''),
                    confidence=result.get('confidence', 0.0),
                    suggestions=result.get('suggestions', []),
                    warnings=result.get('warnings', []),
                    board_state=board_state,
                    supabase_url=SUPABASE_URL,
                    supabase_key=SUPABASE_KEY
                )
                if session_id:
                    print(f"   💾 Session saved to DB: {session_id}")
            except Exception as e:
                print(f"   ⚠️  Failed to save session to DB: {e}")
                import traceback
                traceback.print_exc()
        
        # Помечаем лог как успешно обработанный (только после успешного анализа)
        if user_id and log_hash:
            try:
                log_cache = get_log_cache()
                log_cache.mark_as_success(user_id, log_hash)
                print(f"   ✅ Log marked as successfully processed (hash: {log_hash[:8]}...)")
            except Exception as e:
                print(f"   ⚠️  Failed to mark log as success: {e}")
        
        # Complete!
        yield send_sse('complete', {
            'success': True,
            'suggestions': result.get('suggestions', []),
            'patched_board_state': result.get('patched_board_state'),
            'confidence': result.get('confidence', 0.0),
            'root_cause': result.get('root_cause', ''),
            'warnings': result.get('warnings', []),
            'total_time': round(total_time, 2),
            'session_id': session_id,  # ID сессии в БД
            'percent': 100
        })
        
    except Exception as e:
        print(f"❌ [CRASH DOCTOR SSE] Error: {e}")
        import traceback
        traceback.print_exc()
        
        yield send_sse('error', {
            'error': 'Internal server error',
            'message': str(e)
        })

