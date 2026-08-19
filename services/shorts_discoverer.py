"""
Shorts 发现服务：用 yt-dlp 获取频道 Shorts 列表 + 按播放量排序。

核心流程:
  1. yt-dlp --flat-playlist 获取 Shorts 专区全部视频元数据
  2. 过滤掉 view_count 为 None 的项
  3. 按 view_count 降序排序
  4. 取前 N 条
  5. 缓存结果到本地 JSON（过期时间可配置）

输出: [(video_id, title, view_count, url), ...]
"""

import json
import logging
import time
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yt_dlp

from config.settings import get_setting, CONFIG_DIR

logger = logging.getLogger(__name__)


CACHE_DIR = CONFIG_DIR / "cache"


def _ensure_cache_dir() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cache_path(channel_name: str) -> Path:
    """给定频道名，返回缓存文件路径。"""
    safe = channel_name.replace(" ", "_")
    return CACHE_DIR / f"{safe}_shorts.json"


def _cache_valid(cache_file: Path) -> bool:
    """检查缓存是否在有效期内。"""
    if not cache_file.exists():
        return False
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        cached_at = data.get("cached_at", 0)
        expire_days = get_setting("cache_expire_days", 7)
        return (time.time() - cached_at) < (expire_days * 86400)
    except (json.JSONDecodeError, OSError):
        return False


def _load_cache(cache_file: Path) -> list[dict] | None:
    """从缓存加载 Shorts 列表，有效返回数据，无效返回 None。"""
    if not _cache_valid(cache_file):
        return None
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("shorts", [])
    except (json.JSONDecodeError, OSError):
        return None


def _save_cache(cache_file: Path, shorts: list[dict]) -> None:
    """保存 Shorts 列表到缓存。"""
    _ensure_cache_dir()
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(
            {"cached_at": time.time(), "shorts": shorts},
            f,
            ensure_ascii=False,
        )


def discover_shorts(
    channel_url: str,
    channel_name: str,
    max_count: int | None = None,
    use_cache: bool = True,
    progress_hook: callable = None,
) -> list[dict]:
    """
    获取频道 Shorts 元数据，按播放量降序排列。

    参数:
        channel_url: 频道的 Shorts 专区 URL（含 /shorts）
        channel_name: 频道名（用于缓存文件命名）
        max_count: 返回数量上限，None 则用配置默认值
        use_cache: 是否使用本地缓存
        progress_hook: 可选进度回调，签名: (phase: str, done: int, total: int, message: str)

    返回:
        [{"id": str, "title": str, "view_count": int, "url": str, "duration": int|None}, ...]
        按 view_count 降序排列

    异常:
        RuntimeError: yt-dlp 解析完全失败
    """
    if max_count is None:
        max_count = get_setting("max_shorts_per_channel", 150)

    # --- 1. 检查缓存 ---
    cache_file = _cache_path(channel_name)
    if use_cache:
        cached = _load_cache(cache_file)
        if cached:
            logger.info(f"[{channel_name}] 使用缓存，{len(cached)} 条 Shorts")
            if progress_hook:
                progress_hook("discover", len(cached), len(cached), "从缓存加载")
            return cached[:max_count]

    # --- 2. 从 yt-dlp 抓取 ---
    if progress_hook:
        progress_hook("discover", 0, 0, "正在获取 Shorts 列表...")

    sleep_min = get_setting("sleep_min", 1.0)
    sleep_max = get_setting("sleep_max", 3.0)

    shorts_entries: list[dict] = []

    def _yt_progress(d):
        """yt-dlp 进度回调（flat-playlist 模式下 status='downloading' 即解析中）。"""
        if progress_hook and d.get("status") == "downloading":
            total = d.get("playlist_count") or d.get("total_bytes") or 0
            idx = d.get("playlist_index") or d.get("downloaded_bytes") or 0
            progress_hook("discover", idx, total, "解析中...")

    ydl_opts = {
        "extract_flat": True,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "progress_hooks": [_yt_progress],
        "sleep_interval": int(sleep_min),
        "max_sleep_interval": int(sleep_max),
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(channel_url, download=False)
    except yt_dlp.utils.DownloadError as e:
        raise RuntimeError(f"yt-dlp 解析失败 [{channel_name}]: {e}") from e

    if info is None:
        raise RuntimeError(f"无法访问频道页面 [{channel_name}]，请检查链接是否有效")

    entries = info.get("entries") or []

    for entry in entries:
        if entry is None:
            continue
        vid = entry.get("id")
        title = entry.get("title", "")
        view_count = entry.get("view_count")
        url = entry.get("url") or f"https://www.youtube.com/shorts/{vid}"

        if not vid:
            continue

        # --flat-playlist 可能不返回 view_count，跳过 None 的项
        if view_count is None:
            continue

        shorts_entries.append(
            {
                "id": vid,
                "title": title,
                "view_count": int(view_count),
                "url": url,
                "duration": entry.get("duration"),  # flat 模式可能为 None
            }
        )

    if not shorts_entries:
        raise RuntimeError(
            f"频道 [{channel_name}] 未获取到任何 Shorts。"
            f"可能原因：无 Shorts 内容、页面被限制、或 region 限制"
        )

    # --- 3. 排序 + 截取 ---
    shorts_entries.sort(key=lambda v: v["view_count"], reverse=True)

    # 缓存完整列表，取用时才截断（避免不同 max_count 之间互相覆盖）
    _save_cache(cache_file, shorts_entries)

    result = shorts_entries[:max_count]

    if progress_hook:
        progress_hook("discover", len(result), len(result), f"获取到 {len(shorts_entries)} 条，取 Top {len(result)}")

    # 频道间随机延迟
    time.sleep(random.uniform(sleep_min, sleep_max))

    return result
