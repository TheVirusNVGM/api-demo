"""
ASTRAL AI API Server
Локальный API для тестирования AI функций
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import sys

# Добавляем текущую директорию в путь для импортов
sys.path.insert(0, os.path.dirname(__file__))

from ai_organize import organize_board
from ai_build import build_modpack

app = Flask(__name__)
CORS(app)  # Разрешаем запросы из лаунчера

# Конфигурация
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY', 'sk-305f15dc2ea84da187673c4359eea764')
SUPABASE_URL = os.getenv('SUPABASE_URL', 'https://kopetvvxlxihbmyqgpjd.supabase.co')
SUPABASE_KEY = os.getenv('SUPABASE_KEY', 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImtvcGV0dnZ4bHhpaGJteXFncGpkIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc1NzIyODY5MywiZXhwIjoyMDcyODA0NjkzfQ.Vh_-EGLIuKRVgbl_VqNKZRSwFJBmSTlDFt40FfeWaa4')


@app.route('/health', methods=['GET'])
def health():
    """Проверка здоровья сервера"""
    return jsonify({
        'status': 'ok',
        'service': 'ASTRAL AI API',
        'version': '1.0.0'
    })


@app.route('/api/ai/organize', methods=['POST'])
def api_organize_board():
    """
    AI организация доски
    
    Принимает список модов, анализирует их и создаёт категории
    """
    try:
        data = request.json
        
        # Валидация
        if not data or 'mods' not in data:
            return jsonify({
                'error': 'Invalid request',
                'message': 'mods array is required'
            }), 400
        
        mods = data['mods']
        
        if len(mods) == 0:
            return jsonify({
                'error': 'No mods provided',
                'message': 'At least one mod is required'
            }), 400
        
        print(f"📦 Organizing {len(mods)} mods...")
        
        # Вызываем AI логику
        result = organize_board(
            mods=mods,
            deepseek_key=DEEPSEEK_API_KEY
        )
        
        print(f"✅ Created {len(result['categories'])} categories")
        
        return jsonify({
            'success': True,
            'organization': result,
            'stats': {
                'total_mods': len(mods),
                'categories_created': len(result['categories'])
            }
        })
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        
        return jsonify({
            'error': 'Internal server error',
            'message': str(e)
        }), 500


@app.route('/api/ai/build', methods=['POST'])
def api_build_modpack():
    """
    AI сборка модпака
    
    Принимает промпт пользователя и текущие моды на доске,
    подбирает подходящие моды из БД
    """
    try:
        data = request.json
        
        # Валидация
        if not data or 'prompt' not in data:
            return jsonify({
                'error': 'Invalid request',
                'message': 'prompt is required'
            }), 400
        
        prompt = data['prompt']
        mc_version = data.get('mc_version', '1.21.1')
        mod_loader = data.get('mod_loader', 'fabric')
        current_mods = data.get('current_mods', [])
        max_mods = data.get('max_mods', 30)
        
        print(f"🤖 Building modpack for: {prompt}")
        print(f"   Version: {mc_version}, Loader: {mod_loader}")
        print(f"   Current mods: {len(current_mods)}")
        
        # Вызываем AI логику
        result = build_modpack(
            prompt=prompt,
            mc_version=mc_version,
            mod_loader=mod_loader,
            current_mods=current_mods,
            max_mods=max_mods,
            deepseek_key=DEEPSEEK_API_KEY,
            supabase_url=SUPABASE_URL,
            supabase_key=SUPABASE_KEY
        )
        
        print(f"✅ Selected {len(result['mods'])} mods")
        
        return jsonify({
            'success': True,
            'modpack': result,
            'stats': {
                'selected_mods': len(result['mods']),
                'new_mods': len([m for m in result['mods'] if m.get('is_new', True)])
            }
        })
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        
        return jsonify({
            'error': 'Internal server error',
            'message': str(e)
        }), 500


@app.route('/api/ai/build-board', methods=['POST'])
def api_build_board_state():
    """
    AI сборка модпака в формате board_state.json
    
    Создаёт готовый файл который можно импортировать в лаунчер
    """
    try:
        data = request.json
        
        # Валидация
        if not data or 'prompt' not in data:
            return jsonify({
                'error': 'Invalid request',
                'message': 'prompt is required'
            }), 400
        
        prompt = data['prompt']
        mc_version = data.get('mc_version', '1.21.1')
        mod_loader = data.get('mod_loader', 'fabric')
        current_mods = data.get('current_mods', [])
        max_mods = data.get('max_mods', 30)
        project_id = data.get('project_id', 'ai-generated-modpack')
        
        print(f"🤖 Building board_state.json for: {prompt}")
        
        # Вызываем AI логику
        result = build_modpack(
            prompt=prompt,
            mc_version=mc_version,
            mod_loader=mod_loader,
            current_mods=current_mods,
            max_mods=max_mods,
            deepseek_key=DEEPSEEK_API_KEY,
            supabase_url=SUPABASE_URL,
            supabase_key=SUPABASE_KEY
        )
        
        # Конвертируем в формат board_state.json
        from datetime import datetime
        import uuid
        
        board_state = {
            "project_id": project_id,
            "camera": {
                "scale": 1.0,
                "tx": 0.0,
                "ty": 0.0
            },
            "mods": [],
            "categories": [],
            "updated_at": datetime.utcnow().isoformat() + "Z"
        }
        
        # Добавляем моды с позициями
        spacing_x = 300
        spacing_y = 250
        cols = 5
        
        for i, mod in enumerate(result['mods']):
            row = i // cols
            col = i % cols
            
            mod_node = {
                "project_id": mod.get('source_id', mod['slug']),
                "position": {
                    "x": col * spacing_x,
                    "y": row * spacing_y
                },
                "title": mod['name'],
                "icon_url": mod.get('icon_url'),
                "description": mod.get('description', ''),
                "file_name": None,
                "unique_id": f"{mod['slug']}_{int(datetime.utcnow().timestamp())}",
                "is_disabled": False,
                "cached_dependencies": [],
                "dependencies_fetched": False,
                "category_id": None,
                "category_index": None
            }
            
            board_state['mods'].append(mod_node)
        
        print(f"✅ Generated board_state.json with {len(board_state['mods'])} mods")
        
        return jsonify({
            'success': True,
            'board_state': board_state,
            'explanation': result.get('explanation', ''),
            'stats': {
                'total_mods': len(board_state['mods']),
                'prompt': prompt,
                'mc_version': mc_version,
                'mod_loader': mod_loader
            }
        })
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        
        return jsonify({
            'error': 'Internal server error',
            'message': str(e)
        }), 500


# Экспортируем app для Vercel
# Vercel автоматически запустит Flask app
if __name__ != '__main__':
    # Production mode (Vercel)
    pass
else:
    # Local development
    print("=" * 60)
    print("🚀 ASTRAL AI API Server")
    print("=" * 60)
    print(f"Server running on: http://localhost:5000")
    print(f"Health check: http://localhost:5000/health")
    print(f"\nEndpoints:")
    print(f"  POST /api/ai/organize    - Organize mods into categories")
    print(f"  POST /api/ai/build       - Build modpack from prompt")
    print(f"  POST /api/ai/build-board - Build modpack as board_state.json")
    print("=" * 60)
    
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=True
    )
