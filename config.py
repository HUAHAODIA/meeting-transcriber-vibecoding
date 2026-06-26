"""配置管理模块 — API凭证加载/保存/校验

使用讯飞非实时语音转写大模型 (ifasr_llm)，凭据为 accessKeyId + accessKeySecret。
"""

import json
import os
import logging
from utils import get_config_path, get_app_dir
from exceptions import CredentialError

logger = logging.getLogger(__name__)

# 默认配置值
DEFAULT_CONFIG = {
    "access_key_id": "",
    "access_key_secret": "",
    "speaker_number": "自动",
    "last_audio_dir": "",
    "convert_to_wav": True,
    "enable_diarization": True,
}


def load_config() -> dict:
    """从JSON配置文件加载配置，文件不存在时返回默认值"""
    config_path = get_config_path()

    if not os.path.exists(config_path):
        logger.info("配置文件不存在，使用默认配置")
        return DEFAULT_CONFIG.copy()

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        logger.info("配置文件加载成功")

        # 迁移旧配置: appid→access_key_id, api_secret→access_key_secret
        if "appid" in config and "access_key_id" not in config:
            config["access_key_id"] = config.pop("appid", "")
        if "api_secret" in config and "access_key_secret" not in config:
            config["access_key_secret"] = config.pop("api_secret", "")

        # 合合默认值中缺失的字段
        for key, value in DEFAULT_CONFIG.items():
            if key not in config:
                config[key] = value
        return config
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"配置文件读取失败: {e}，使用默认配置")
        return DEFAULT_CONFIG.copy()


def save_config(config: dict) -> None:
    """将配置保存到JSON文件"""
    config_path = get_config_path()

    try:
        # 确保目录存在
        os.makedirs(os.path.dirname(config_path), exist_ok=True)

        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        logger.info("配置文件保存成功")
    except IOError as e:
        logger.error(f"配置文件保存失败: {e}")
        raise


def validate_credentials(access_key_id: str, access_key_secret: str) -> bool:
    """校验API凭证是否有效

    讯飞非实时语音转写大模型使用 accessKeyId + accessKeySecret。
    """
    if not access_key_id or not access_key_id.strip():
        raise CredentialError("AccessKeyId不能为空")
    if not access_key_secret or not access_key_secret.strip():
        raise CredentialError("AccessKeySecret不能为空")

    logger.info("API凭证格式校验通过")
    return True


def get_last_audio_dir() -> str:
    """获取上次选择音频文件的目录"""
    config = load_config()
    last_dir = config.get("last_audio_dir", "")
    if last_dir and os.path.isdir(last_dir):
        return last_dir
    # 默认返回用户桌面路径
    desktop = os.path.join(os.path.expanduser('~'), 'Desktop')
    return desktop if os.path.isdir(desktop) else os.path.expanduser('~')
