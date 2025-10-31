"""
Request Logger
Сохраняет каждый AI запрос в отдельный лог файл
Структура: logs/YYYY-Www/YYYYMMDD_HHMMSS_BuildID.log
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Optional


class RequestLogger:
    def __init__(self, base_dir: str = "logs"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(exist_ok=True)
    
    def get_week_folder(self) -> Path:
        """Получает папку для текущей недели (например: 2025-W44)"""
        now = datetime.now()
        year = now.year
        week = now.isocalendar()[1]  # ISO week number
        folder_name = f"{year}-W{week:02d}"
        
        week_folder = self.base_dir / folder_name
        week_folder.mkdir(exist_ok=True)
        return week_folder
    
    def create_log_file(self, build_id: Optional[str] = None) -> Path:
        """
        Создаёт файл лога для запроса
        
        Args:
            build_id: ID сборки из БД (например: "0000011")
        
        Returns:
            Path к созданному файлу
        """
        now = datetime.now()
        
        # Формат: YYYYMMDD_HHMMSS
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        
        # Формат имени файла
        if build_id:
            filename = f"{timestamp}_{build_id}.log"
        else:
            filename = f"{timestamp}_no-build-id.log"
        
        week_folder = self.get_week_folder()
        log_file = week_folder / filename
        
        return log_file
    
    def write_log(self, build_id: Optional[str], content: str) -> str:
        """
        Записывает лог в файл
        
        Args:
            build_id: ID сборки из БД
            content: Текст лога (весь stdout/stderr)
        
        Returns:
            Путь к созданному файлу
        """
        log_file = self.create_log_file(build_id)
        
        with open(log_file, 'w', encoding='utf-8') as f:
            # Header
            f.write("="*80 + "\n")
            f.write(f"ASTRAL AI API - Request Log\n")
            f.write(f"Build ID: {build_id or 'N/A'}\n")
            f.write(f"Timestamp: {datetime.now().isoformat()}\n")
            f.write("="*80 + "\n\n")
            
            # Content
            f.write(content)
        
        return str(log_file)
    
    def cleanup_old_logs(self, weeks_to_keep: int = 4):
        """
        Удаляет логи старше N недель
        
        Args:
            weeks_to_keep: Сколько недель хранить (по умолчанию 4)
        """
        if not self.base_dir.exists():
            return
        
        current_year = datetime.now().year
        current_week = datetime.now().isocalendar()[1]
        
        for folder in self.base_dir.iterdir():
            if not folder.is_dir():
                continue
            
            # Парсим название папки (YYYY-Www)
            try:
                parts = folder.name.split('-W')
                if len(parts) != 2:
                    continue
                
                year = int(parts[0])
                week = int(parts[1])
                
                # Вычисляем разницу в неделях (приблизительно)
                week_diff = (current_year - year) * 52 + (current_week - week)
                
                if week_diff > weeks_to_keep:
                    print(f"🗑️  Cleaning up old logs: {folder.name}")
                    import shutil
                    shutil.rmtree(folder)
            except:
                continue


# Singleton instance
_logger_instance = None

def get_request_logger() -> RequestLogger:
    """Получить глобальный экземпляр логгера"""
    global _logger_instance
    if _logger_instance is None:
        # Создаём папку logs в корне проекта
        base_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
        _logger_instance = RequestLogger(base_dir)
    return _logger_instance
