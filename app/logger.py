import os
from datetime import datetime
from typing import Optional

class Logger:
    channel = "app"
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs")
    
    LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]

    @staticmethod
    def _get_log_filename(channel: Optional[str] = None):
        if channel is None:
            channel = Logger.channel
        date_str = datetime.now().strftime("%Y-%m-%d")
        if not os.path.exists(Logger.log_dir):
            os.makedirs(Logger.log_dir)
        return os.path.join(Logger.log_dir, f"{date_str}.{channel}.log")

    @staticmethod
    def _format_message(level: str, message: str, context: Optional[str] = None):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ctx = f" [{context}]" if context else ""
        return f"{now} [{level}]{ctx} {message}"

    @classmethod
    def log(cls, message: str, level: str = "INFO", context: Optional[str] = None, to_console: bool = True):
        if level not in cls.LEVELS:
            level = "INFO"
        formatted = cls._format_message(level, message, context)
        if to_console:
            print(formatted)
        with open(cls._get_log_filename(cls.channel), "a", encoding="utf-8") as f:
            f.write(formatted + "\n")

    @classmethod
    def debug(cls, message: str, context: Optional[str] = None, to_console: bool = True):
        cls.log(message, "DEBUG", context, to_console)

    @classmethod
    def info(cls, message: str, context: Optional[str] = None, to_console: bool = True):
        cls.log(message, "INFO", context, to_console)

    @classmethod
    def warning(cls, message: str, context: Optional[str] = None, to_console: bool = True):
        cls.log(message, "WARNING", context, to_console)

    @classmethod
    def error(cls, message: str, context: Optional[str] = None, to_console: bool = True):
        cls.log(message, "ERROR", context, to_console)
