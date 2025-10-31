"""
AI Sort Feedback - endpoint to submit star ratings for AI auto-sort sessions
"""

from flask import jsonify, request
import requests
from config import SUPABASE_URL, SUPABASE_KEY


def submit_sort_feedback(session_id: str, rating: int) -> dict:
    """
    Сохраняет оценку пользователя для AI sort session
    
    Args:
        session_id: ID сессии сортировки
        rating: Оценка 1-5 звёзд
    
    Returns:
        Dict с результатом операции
    """
    
    print(f"⭐ [AI Sort Feedback] Submitting rating for session {session_id}: {rating}/5")
    
    try:
        # Обновляем rating в БД
        headers = {
            'apikey': SUPABASE_KEY,
            'Authorization': f'Bearer {SUPABASE_KEY}',
            'Content-Type': 'application/json'
        }
        
        payload = {
            'rating': rating,
            'feedback_submitted_at': 'now()'
        }
        
        response = requests.patch(
            f"{SUPABASE_URL}/rest/v1/ai_sort_sessions?id=eq.{session_id}",
            headers=headers,
            json=payload,
            timeout=10
        )
        
        if response.status_code in [200, 204]:
            print(f"✅ [AI Sort Feedback] Rating saved successfully")
            return {
                'success': True,
                'message': 'Feedback submitted successfully'
            }
        else:
            print(f"⚠️  [AI Sort Feedback] Failed to save rating: {response.status_code}")
            print(f"   Response: {response.text}")
            return {
                'success': False,
                'error': 'Failed to save feedback',
                'status_code': response.status_code
            }
    
    except Exception as e:
        print(f"❌ [AI Sort Feedback] Error: {e}")
        import traceback
        traceback.print_exc()
        return {
            'success': False,
            'error': str(e)
        }
