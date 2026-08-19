"""
GUI 主窗口 + 页面路由。

线程模型：下载线程 → queue.Queue → 主线程 after() 轮询 → 更新 UI
"""

import logging
import queue
import threading

import customtkinter as ctk
from tkinterdnd2 import TkinterDnD

from app.orchestrator import Orchestrator
from gui.design import DESIGN
from gui.start_page import StartPage
from gui.progress_page import ProgressPage

logger = logging.getLogger(__name__)


class App(ctk.CTk):

    def __init__(self):
        super().__init__()

        # 注入文件拖拽支持
        TkinterDnD._require(self)

        self.title("TG下载器")
        self.geometry("960x620")
        self.minsize(700, 520)

        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")
        self.configure(fg_color=DESIGN["bg"])

        self._progress_queue = queue.Queue()
        self._poll_id = None

        self._orchestrator: Orchestrator | None = None
        self._worker_thread: threading.Thread | None = None

        self._container = ctk.CTkFrame(self, fg_color="transparent")
        self._container.pack(fill="both", expand=True)

        self._pages: dict[str, ctk.CTkFrame] = {}
        self._current_page: str | None = None

        self._pages["start"] = StartPage(self._container, self)
        self._pages["progress"] = ProgressPage(self._container, self)

        self.show_page("start")
        self._poll_progress_queue()

        logger.info("GUI 初始化完成")

    @property
    def is_downloading(self) -> bool:
        return (self._orchestrator is not None
                and self._worker_thread is not None
                and self._worker_thread.is_alive())

    def show_page(self, name: str):
        if self._current_page == name:
            return
        if self._current_page and self._current_page in self._pages:
            self._pages[self._current_page].pack_forget()
        page = self._pages.get(name)
        if page:
            page.pack(fill="both", expand=True)
            self._current_page = name
            if hasattr(page, "on_show"):
                page.on_show()

    def start_download(self, excel_path: str, output_dir: str,
                       max_shorts: int = 150, quality: str = "1080p",
                       speed_mode: str = "stable"):
        logger.info(f"开始下载: excel={excel_path}, output={output_dir}, max={max_shorts}, quality={quality}, speed={speed_mode}")
        self.show_page("progress")
        self._orchestrator = Orchestrator()
        self._orchestrator.set_excel(excel_path)
        self._orchestrator.set_output_dir(output_dir)
        self._orchestrator.set_max_shorts(max_shorts)
        self._orchestrator.set_quality(quality)
        self._orchestrator.set_speed_mode(speed_mode)
        self._orchestrator.set_progress_hook(self._on_progress_event)
        self._worker_thread = threading.Thread(target=self._orchestrator.run, daemon=True)
        self._worker_thread.start()

    def add_to_queue(self, excel_path: str, max_shorts: int = 150, quality: str = "1080p",
                     speed_mode: str = "stable"):
        """向正在运行的队列追加新频道。"""
        if not self.is_downloading or not self._orchestrator:
            return

        from services.excel_reader import read_channels
        try:
            channels = read_channels(excel_path)
        except Exception as e:
            logger.error(f"读取 Excel 失败: {e}")
            return

        if self._orchestrator:
            self._orchestrator.set_speed_mode(speed_mode)
        added = self._orchestrator.add_channels(channels)
        if added > 0:
            # 通知进度页追加卡片
            self._progress_queue.put(("channels_added", {
                "channels": self._orchestrator.channels[-added:],
                "total": self._orchestrator.stats["total_channels"],
            }))
            logger.info(f"已追加 {added} 个频道到队列")

    def cancel_download(self):
        if self._orchestrator:
            self._orchestrator.cancel()

    def _on_progress_event(self, event_type: str, data: dict):
        self._progress_queue.put((event_type, data))

    def _poll_progress_queue(self):
        try:
            while True:
                event_type, data = self._progress_queue.get_nowait()
                try:
                    self._handle_event(event_type, data)
                except Exception:
                    logger.exception(f"事件处理失败: {event_type}")
        except queue.Empty:
            pass
        finally:
            self._poll_id = self.after(100, self._poll_progress_queue)

    def _handle_event(self, event_type: str, data: dict):
        pp = self._pages.get("progress")
        if not isinstance(pp, ProgressPage):
            return
        if event_type == "log" or event_type == "license_checked":
            pass
        elif event_type == "channels_added":
            pp.append_channels(data["channels"], data["total"])
        elif event_type == "channels_loaded":
            pp.init_channels(data["count"], data.get("channels"))
        elif event_type == "channel_start":
            pp.add_channel_card(seq=data["seq"], name=data["name"], url=data["url"])
        elif event_type == "channel_discover":
            pp.update_channel_card(seq=data["seq"], phase="discover", done=data["done"], total=data["total"], message=data["message"])
        elif event_type == "channel_download":
            pp.update_channel_card(seq=data["seq"], phase="download", done=data["done"], total=data["total"], message=data["message"])
        elif event_type == "channel_done":
            pp.update_channel_card_status(seq=data["seq"], status="done", success=data["success"], skip=data["skip"], failed=data["failed"])
        elif event_type == "channel_error":
            pp.update_channel_card_status(seq=data["seq"], status="error", error=data["error"])
        elif event_type == "all_done":
            pp.show_summary(data)

    def destroy(self):
        if self._poll_id:
            self.after_cancel(self._poll_id)
        if self._orchestrator:
            self._orchestrator.cancel()
        super().destroy()
