"""Logging configuration and setup."""
import os 
import sys
import logging
from logging import Logger
try:
    from colorlog import ColoredFormatter
    HAS_COLORLOG = True
except ImportError:  # pragma: no cover - fallback for minimal test environments
    HAS_COLORLOG = False

    class ColoredFormatter(logging.Formatter):
        """Fallback formatter when ``colorlog`` is unavailable."""

        def __init__(self, fmt=None, datefmt=None, **kwargs):
            super().__init__(fmt=fmt, datefmt=datefmt)


import io
# Force UTF-8 encoding for stdout to handle emojis in logs on Windows
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except (AttributeError, io.UnsupportedOperation):
        pass

def init_logger(name: str) -> Logger:
    """
    Initialize and return a logger instance.
    Deletes the old log file if it exists and creates a new one.
    
    Args:
        name: Name of the logger
        
    Returns:
        Configured logger instance
    """
    logging.root.handlers = []  # Clear existing handlers to avoid duplicates

    handler = logging.StreamHandler(sys.stdout)
    if HAS_COLORLOG:
        handler.setFormatter(
            ColoredFormatter(
                "%(cyan)s[%(asctime)s]%(reset)s %(log_color)s[%(levelname)s]%(reset)s %(blue)s%(name)s%(reset)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
                log_colors={
                    "DEBUG": "purple",
                    "INFO": "green",
                    "WARNING": "yellow",
                    "ERROR": "red",
                    "CRITICAL": "bold_red",
                },
                secondary_log_colors={},
                reset=True,
            )
        )
    else:
        handler.setFormatter(
            logging.Formatter(
                "[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
        )

    file_path = os.path.join("logs", f"{name}.log")
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    
    # Try to delete old log file, but don't fail if it's locked (parallel processes)
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
        file_mode = 'w'
    except (PermissionError, OSError):
        # File is locked by another process, use append mode
        file_mode = 'a'

    file_handler = logging.FileHandler(file_path, mode=file_mode, encoding='utf-8')
    file_handler.setFormatter(
        logging.Formatter(
            "[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
    )
    
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    logger.addHandler(file_handler)
    
    return logger
    

def get_logger(name: str) -> Logger:
    """
    Get a logger instance by name.
    
    Args:
        name: Name of the logger
        
    Returns:
        Logger instance
    """
    logger = logging.getLogger(name)
    
    # Check if logger already has handlers
    if not logger.handlers:
        return init_logger(name)
    
    return logger
