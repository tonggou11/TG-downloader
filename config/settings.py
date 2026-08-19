"""
配置层：本地 JSON 配置读写。

当前仅本地配置，未来可扩展 RemoteConfigProvider，
从后端拉取配置（如会员等级对应的频道上限、并发数等）。
"""

import json
import os
from pathlib import Path
from typing import Any

APP_NAME = "YT-Shorts-Downloader"
CONFIG_DIR = Path.home() / f".{APP_NAME}"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "output_dir": str(Path.home() / "Downloads" / "YT-Shorts"),
    "max_shorts_per_channel": 150,
    "sleep_min": 1.0,
    "sleep_max": 3.0,
    "download_concurrency": 2,
    "cache_expire_days": 7,
    "ffmpeg_path": "",  # 为空则自动从 PATH 查找
    "language": "zh",
    "cookies_mode": "off",     # "off" / "browser" / "file"
    "cookies_browser": "chrome",  # chrome / edge / firefox / brave / opera
    "cookies_file": "",        # cookies.txt 文件路径（cookies_mode=file 时使用）
    "speed_mode": "stable",    # "stable" 稳定 / "turbo" 极速
}


def ensure_config_dir() -> None:
    """确保配置目录存在。"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict[str, Any]:
    """加载配置，不存在则使用默认值。"""
    ensure_config_dir()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            return {**DEFAULT_CONFIG, **saved}
        except (json.JSONDecodeError, OSError):
            pass
    return DEFAULT_CONFIG.copy()


def save_config(config: dict[str, Any]) -> None:
    """保存配置到文件。"""
    ensure_config_dir()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def get_setting(key: str, default=None):
    """快捷读取单项配置。"""
    config = load_config()
    return config.get(key, default)
