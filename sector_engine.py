"""
DAILY SIGNAL — Structured Logger
Logging ke console DAN Supabase database secara bersamaan.
"""

import sys
import uuid
import traceback
from datetime import datetime
from typing import Any, Optional
from loguru import logger as _loguru_logger

# UUID untuk satu run session
_RUN_ID = str(uuid.uuid4())
_supabase_client = None  # Lazy init


def _get_supabase():
    """Lazy import untuk menghindari circular dependency."""
    global _supabase_client
    if _supabase_client is None:
        try:
            from src.core.database import get_db
            _supabase_client = get_db()
        except Exception:
            pass  # Database belum tersedia saat init
    return _supabase_client


class DailySignalLogger:
    """
    Logger wrapper yang menulis ke console dan database.
    """

    def __init__(self, module_name: str):
        self.module = module_name
        self._run_id = _RUN_ID

    def _log_to_db(self, level: str, message: str, details: Optional[dict] = None):
        """Simpan log ke Supabase (best-effort, tidak crash jika gagal)."""
        try:
            db = _get_supabase()
            if db is None:
                return
            db.table("system_logs").insert({
                "log_time": datetime.utcnow().isoformat(),
                "level": level,
                "module": self.module,
                "message": message,
                "details": details,
                "run_id": self._run_id,
            }).execute()
        except Exception:
            pass  # Log failure tidak boleh crash sistem utama

    def debug(self, message: str, **kwargs):
        _loguru_logger.debug(f"[{self.module}] {message}")

    def info(self, message: str, details: Optional[dict] = None, **kwargs):
        _loguru_logger.info(f"[{self.module}] {message}")
        self._log_to_db("INFO", message, details)

    def warning(self, message: str, details: Optional[dict] = None, **kwargs):
        _loguru_logger.warning(f"[{self.module}] {message}")
        self._log_to_db("WARNING", message, details)

    def error(self, message: str, details: Optional[dict] = None,
              exc: Optional[Exception] = None, **kwargs):
        tb = traceback.format_exc() if exc else None
        if tb and tb.strip() != "NoneType: None":
            _loguru_logger.error(f"[{self.module}] {message}\n{tb}")
            if details is None:
                details = {}
            details["traceback"] = tb
        else:
            _loguru_logger.error(f"[{self.module}] {message}")
        self._log_to_db("ERROR", message, details)

    def critical(self, message: str, details: Optional[dict] = None, **kwargs):
        _loguru_logger.critical(f"[{self.module}] {message}")
        self._log_to_db("CRITICAL", message, details)

    def success(self, message: str, **kwargs):
        _loguru_logger.success(f"[{self.module}] {message}")
        self._log_to_db("INFO", f"✓ {message}")


def setup_logging(log_level: str = "INFO"):
    """Konfigurasi loguru untuk output yang rapi."""
    _loguru_logger.remove()
    _loguru_logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>",
        level=log_level,
        colorize=True,
    )
    # Juga log ke file
    _loguru_logger.add(
        "logs/daily_signal_{time:YYYY-MM-DD}.log",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
        level="DEBUG",
        rotation="1 day",
        retention="7 days",
        compression="gz",
    )


def get_logger(module_name: str) -> DailySignalLogger:
    """Factory function untuk mendapatkan logger per modul."""
    return DailySignalLogger(module_name)


def get_run_id() -> str:
    """Dapatkan run ID saat ini."""
    return _RUN_ID
