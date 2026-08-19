"""
应用编排层：串联 Excel 读取 → Shorts 发现 → Shorts 下载全流程。

GUI 和 CLI 共用此层，通过 progress_hook 回调来适配不同界面的进度展示。
"""

import logging
import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from config import settings
from license.base import LicenseManager
from license.stub import StubLicenseManager
from services.excel_reader import read_channels
from services.shorts_discoverer import discover_shorts
from services.shorts_downloader import download_shorts

logger = logging.getLogger("orchestrator")


class Orchestrator:
    """
    任务编排器。

    用法:
        orch = Orchestrator()
        orch.set_license_manager(StubLicenseManager())
        orch.set_excel("channels.xlsx")
        orch.set_progress_hook(my_hook)

        result = orch.run()
    """

    def __init__(self):
        self._excel_path: str | None = None
        self._output_dir: str = settings.get_setting("output_dir")
        self._max_shorts_per_channel: int | None = None
        self._quality: str = "1080p"
        self._cookies_mode: str = settings.get_setting("cookies_mode", "off")
        self._cookies_browser: str = settings.get_setting("cookies_browser", "chrome")
        self._cookies_file: str = settings.get_setting("cookies_file", "")
        self._speed_mode: str = settings.get_setting("speed_mode", "stable")
        self._license_mgr: LicenseManager = StubLicenseManager()
        self._progress_hook: callable = None
        self._cancel_flag = False
        self._cancel_event = threading.Event()  # set = 取消
        self._pause_event = threading.Event()
        self._pause_event.set()  # 初始为非暂停状态

        # 运行时状态
        self.channels: list[tuple[int, str, str]] = []
        self.results: dict[str, Any] = {}
        self.stats: dict[str, Any] = {
            "total_channels": 0,
            "success_channels": 0,
            "failed_channels": 0,
            "total_videos": 0,
            "failed_videos": 0,
            "started_at": None,
            "finished_at": None,
        }

    # ── 配置方法 ──

    def set_excel(self, path: str) -> None:
        self._excel_path = path

    def set_output_dir(self, path: str) -> None:
        self._output_dir = path

    def set_max_shorts(self, count: int) -> None:
        """设置每个频道下载数量（覆盖 config 默认值）。"""
        self._max_shorts_per_channel = count

    def set_quality(self, quality: str) -> None:
        """设置画质: 1080p / 720p / 480p / 最高"""
        self._quality = quality

    def set_cookies(self, mode: str, browser: str = "chrome", file_path: str = "") -> None:
        """设置 cookies 验证: mode = "off" / "browser" / "file" """
        self._cookies_mode = mode
        self._cookies_browser = browser
        self._cookies_file = file_path

    def set_speed_mode(self, mode: str) -> None:
        """设置速度模式: "stable" / "turbo" """
        self._speed_mode = mode

    def set_license_manager(self, mgr: LicenseManager) -> None:
        self._license_mgr = mgr

    def set_progress_hook(self, hook: callable) -> None:
        """
        设置进度回调。

        hook 签名:
            (event_type: str, data: dict) -> None

        event_type 可能值:
          - "license_checked"    → data: permission dict
          - "channels_loaded"    → data: {"count": int}
          - "channel_start"      → data: {"seq": int, "name": str, "url": str, "total": int}
          - "channel_discover"   → data: {"seq": int, "name": str, "done": int, "total": int, "message": str}
          - "channel_download"   → data: {"seq": int, "name": str, "done": int, "total": int, "message": str}
          - "channel_done"       → data: {"seq": int, "name": str, "success": int, "skip": int, "failed": int, "failed_urls": list}
          - "channel_error"      → data: {"seq": int, "name": str, "error": str}
          - "all_done"           → data: stats dict
          - "log"                → data: {"level": str, "message": str}
        """
        self._progress_hook = hook

    def cancel(self) -> None:
        self._cancel_flag = True
        self._cancel_event.set()
        self.resume()  # 取消时自动恢复暂停，避免死锁

    def pause(self) -> None:
        """暂停下载。"""
        self._pause_event.clear()

    def resume(self) -> None:
        """继续下载。"""
        self._pause_event.set()

    @property
    def is_paused(self) -> bool:
        return not self._pause_event.is_set()

    def add_channels(self, channels: list[tuple[int, str, str]]) -> int:
        """追加新频道到当前任务队列末尾。返回新增数量。"""
        if not channels:
            return 0
        # 重新编号：按当前最大序号继续
        max_seq = max((s for s, _, _ in self.channels), default=0)
        new_channels = []
        for i, (_, url, name) in enumerate(channels, 1):
            new_channels.append((max_seq + i, url, name))
        self.channels.extend(new_channels)
        self.stats["total_channels"] = len(self.channels)
        logger.info(f"追加 {len(new_channels)} 个频道到队列，总数 {len(self.channels)}")
        return len(new_channels)

    # ── 运行 ──

    def run(self) -> dict:
        """执行完整流程，返回统计字典。"""
        self._cancel_flag = False
        self._cancel_event.clear()

        if not self._excel_path:
            raise ValueError("未设置 Excel 文件路径")

        self.stats["started_at"] = datetime.now().isoformat()
        self.results = {}

        # --- 1. License 检查 ---
        permission = self._license_mgr.check_permission()
        self._emit("license_checked", permission)

        if not permission.get("allowed"):
            self._emit("log", {"level": "error", "message": f"使用权限被拒绝: {permission.get('reason', '未知原因')}"})
            return self.stats

        # --- 2. 读取 Excel ---
        self._emit("log", {"level": "info", "message": f"读取 Excel: {self._excel_path}"})

        try:
            self.channels = read_channels(self._excel_path)
        except (FileNotFoundError, ValueError) as e:
            self._emit("log", {"level": "error", "message": f"读取 Excel 失败: {e}"})
            return self.stats

        self.stats["total_channels"] = len(self.channels)
        self._emit("channels_loaded", {
            "count": len(self.channels),
            "channels": [(s, u, n) for s, u, n in self.channels],
        })
        self._emit("log", {"level": "info", "message": f"识别到 {len(self.channels)} 个频道"})

        # --- 3. 遍历频道: 发现 + 下载 ---
        for idx, (seq, url, name) in enumerate(self.channels):
            if self._cancel_flag:
                self._emit("log", {"level": "warn", "message": "用户取消操作"})
                break

            # 暂停等待
            if not self._pause_event.is_set():
                self._emit("log", {"level": "info", "message": "任务已暂停"})
                self._pause_event.wait()

            # 检查会员限制（未来 free 用户可能有限额）
            remaining = permission.get("remaining_channels")
            if remaining is not None and idx >= remaining:
                self._emit("log", {
                    "level": "warn",
                    "message": f"会员限制: 已处理 {idx}/{len(self.channels)} 个频道，剩余 {len(self.channels) - idx} 个需要升级"
                })
                break

            self._emit("channel_start", {
                "seq": seq, "name": name, "url": url,
                "index": idx + 1, "total": len(self.channels),
            })

            logger.info(f"[{idx+1}/{len(self.channels)}] 开始处理: {name}")

            # --- 3a. 发现 Shorts ---
            try:
                shorts = discover_shorts(
                    channel_url=url,
                    channel_name=name,
                    max_count=self._max_shorts_per_channel,
                    progress_hook=lambda phase, done, total, msg: (
                        self._emit("channel_discover", {
                            "seq": seq, "name": name,
                            "done": done, "total": total, "message": msg,
                        })
                    ),
                )
            except RuntimeError as e:
                self.stats["failed_channels"] += 1
                self._emit("channel_error", {"seq": seq, "name": name, "error": str(e)})
                continue

            # --- 3b. 下载 ---
            ffmpeg_path = settings.get_setting("ffmpeg_path", "")
            success, skipped, failed = download_shorts(
                shorts=shorts,
                output_dir=self._output_dir,
                channel_name=name,
                seq_num=seq,
                ffmpeg_path=ffmpeg_path,
                quality=self._quality,
                cookies_mode=self._cookies_mode,
                cookies_browser=self._cookies_browser,
                cookies_file=self._cookies_file,
                cancel_event=self._cancel_event,
                pause_event=self._pause_event,
                speed_mode=self._speed_mode,
                progress_hook=lambda phase, done, total, msg: (
                    self._emit("channel_download", {
                        "seq": seq, "name": name,
                        "done": done, "total": total, "message": msg,
                    })
                ),
            )

            if failed:
                self.stats["failed_channels"] += 1
            else:
                self.stats["success_channels"] += 1

            self.stats["total_videos"] += success
            self.stats["failed_videos"] += len(failed)

            self._emit("channel_done", {
                "seq": seq, "name": name,
                "success": success, "skip": skipped,
                "failed": len(failed), "failed_urls": failed,
            })

        # --- 4. 完成 ---
        self.stats["finished_at"] = datetime.now().isoformat()
        self._emit("all_done", {**self.stats, "cancelled": self._cancel_flag})
        self._emit("log", {
            "level": "info",
            "message": (
                f"全部完成 — 成功 {self.stats['success_channels']} 个频道, "
                f"下载 {self.stats['total_videos']} 个视频, "
                f"失败 {self.stats['failed_channels']} 个频道"
            ),
        })

        return self.stats

    # ── 内部方法 ──

    def _emit(self, event_type: str, data: dict) -> None:
        """发送进度事件。"""
        if self._progress_hook:
            try:
                self._progress_hook(event_type, data)
            except Exception:
                pass  # 回调异常不应中断主流程
