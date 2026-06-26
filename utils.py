"""工具函数模块 — 时间格式化、日志、路径等"""

import os
import sys
import logging
import re


def format_duration(seconds: float) -> str:
    """将秒数格式化为 MM:SS 或 HH:MM:SS 字符串"""
    total_seconds = int(seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_timestamp(seconds: float) -> str:
    """将秒数格式化为 HH:MM:SS 时间戳（用于输出文件）"""
    total_seconds = int(seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def get_app_dir() -> str:
    """获取应用数据目录路径（Windows: %APPDATA%/xfyun_transcriber/）"""
    if sys.platform == 'win32':
        base = os.environ.get('APPDATA', os.path.expanduser('~'))
    else:
        base = os.path.expanduser('~')
    app_dir = os.path.join(base, 'xfyun_transcriber')
    os.makedirs(app_dir, exist_ok=True)
    return app_dir


def get_config_path() -> str:
    """获取配置文件路径"""
    return os.path.join(get_app_dir(), 'config.json')


def get_log_path() -> str:
    """获取日志文件路径"""
    return os.path.join(get_app_dir(), 'app.log')


def setup_logging(level=logging.INFO) -> None:
    """配置日志系统（控制台+文件）"""
    log_dir = get_app_dir()
    log_file = get_log_path()

    # 文件日志（轮转，最大5MB，3个备份）
    from logging.handlers import RotatingFileHandler
    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3,
        encoding='utf-8'
    )
    file_handler.setLevel(level)
    file_formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )
    file_handler.setFormatter(file_formatter)

    # 控制台日志
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_formatter = logging.Formatter(
        '[%(levelname)s] %(message)s'
    )
    console_handler.setFormatter(console_formatter)

    # 配置根logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    # 清除已有handler避免重复
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)


def validate_time_input(value: str) -> float:
    """验证并转换用户输入的时间字符串为秒数

    支持格式:
      - "90" → 90秒
      - "1:30" → 90秒
      - "0:01:30" → 90秒
    """
    value = value.strip()
    if not value:
        raise ValueError("时间值不能为空")

    # 纯数字格式
    if re.match(r'^\d+(\.\d+)?$', value):
        return float(value)

    # HH:MM:SS 或 MM:SS 格式
    parts = value.split(':')
    if len(parts) == 2:
        try:
            minutes, seconds = int(parts[0]), float(parts[1])
            return minutes * 60 + seconds
        except ValueError:
            raise ValueError(f"无法解析时间格式: {value}")
    elif len(parts) == 3:
        try:
            hours, minutes, seconds = int(parts[0]), int(parts[1]), float(parts[2])
            return hours * 3600 + minutes * 60 + seconds
        except ValueError:
            raise ValueError(f"无法解析时间格式: {value}")

    raise ValueError(f"不支持的时间格式: {value}，请使用秒数、MM:SS或HH:MM:SS格式")


def safe_filename(original_path: str, suffix: str) -> str:
    """根据原始文件路径生成安全的输出文件名

    例如: audio.mp3 + _transcribed → audio_transcribed.txt
    """
    base_name = os.path.splitext(os.path.basename(original_path))[0]
    output_dir = os.path.dirname(original_path)
    filename = f"{base_name}{suffix}.txt"
    return os.path.join(output_dir, filename)


def get_resource_path(relative_path: str) -> str:
    """获取资源文件的绝对路径（兼容PyInstaller打包模式）

    开发模式: 相对于脚本目录
    打包模式: 相对于sys._MEIPASS临时目录
    """
    if getattr(sys, 'frozen', False):
        # PyInstaller打包模式
        base_path = sys._MEIPASS
    else:
        # 开发模式
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)