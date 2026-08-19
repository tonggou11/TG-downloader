"""
进度页：实时任务队列 + 统计 + 暂停/清空。
"""

import logging
import shutil
import time
from tkinter import messagebox

import customtkinter as ctk

from gui.design import DESIGN
from config.settings import CONFIG_DIR

logger = logging.getLogger(__name__)


def _fmt_duration(seconds: float) -> str:
    """秒数 → MM:SS 字符串。"""
    s = int(seconds)
    return f"{s // 60:02d}:{s % 60:02d}"


class ChannelCard(ctk.CTkFrame):

    def __init__(self, parent, seq: int, name: str, url: str):
        d = DESIGN
        super().__init__(parent, fg_color=d["surface"], corner_radius=d["radius_sm"],
                         border_width=1, border_color=d["border_light"])
        self.seq = seq
        self.name = name
        self.url = url
        self._status = "waiting"
        self._start_time: float | None = None  # 开始处理时间（用于频道用时）
        self._build()

    def _build(self):
        d = DESIGN
        top_row = ctk.CTkFrame(self, fg_color="transparent")
        top_row.pack(fill="x", padx=16, pady=(12, 0))

        self._icon_label = ctk.CTkLabel(top_row, text=f"{self.seq:02d}  ⏳", font=d["font_body"], text_color=d["text_muted"])
        self._icon_label.pack(side="left")

        self._name_label = ctk.CTkLabel(top_row, text=self.name, font=("Microsoft YaHei", 14, "bold"),
                                        text_color=d["text_primary"], anchor="w")
        self._name_label.pack(side="left", padx=(10, 0))

        self._status_label = ctk.CTkLabel(top_row, text="等待中", font=d["font_caption"], text_color=d["text_muted"])
        self._status_label.pack(side="right")

        cr = ctk.CTkFrame(self, fg_color="transparent")
        cr.pack(fill="x", padx=16, pady=(2, 0))
        self._count_label = ctk.CTkLabel(cr, text="", font=d["font_small"], text_color=d["text_muted"])
        self._count_label.pack(side="left")

        br = ctk.CTkFrame(self, fg_color="transparent")
        br.pack(fill="x", padx=16, pady=(6, 12))
        self._progress = ctk.CTkProgressBar(br, fg_color=d["surface_elevated"], progress_color=d["accent"], height=6, corner_radius=3)
        self._progress.pack(fill="x")
        self._progress.set(0)

    def _update(self, icon, icon_color, status_text, status_color, count_text, count_color=None,
                bar_val=None, bar_color=None, border=None):
        self._icon_label.configure(text=icon, text_color=icon_color)
        self._status_label.configure(text=status_text, text_color=status_color)
        self._count_label.configure(text=count_text, text_color=count_color or status_color)
        if bar_val is not None:
            self._progress.set(bar_val)
        if bar_color:
            self._progress.configure(progress_color=bar_color)
        if border:
            self.configure(border_color=border)

    def update_discover(self, done: int, total: int, message: str):
        self._status = "discover"
        self._update(f"{self.seq:02d}  🔍", DESIGN["accent"], "分析中", DESIGN["accent"], f"已发现 {done} 条 Shorts")

    def update_download(self, done: int, total: int, message: str):
        self._status = "download"
        d = DESIGN
        ratio = done / total if total > 0 else 0
        self._update(f"{self.seq:02d}  📥", d["accent"], f"{int(ratio*100)}%", d["accent"],
                     f"已下载 {done} / {total}", d["text_secondary"], bar_val=ratio)

    def _elapsed_text(self) -> str:
        """频道用时文本（未开始则空）。"""
        if self._start_time is None:
            return ""
        return f" · 用时 {_fmt_duration(time.time() - self._start_time)}"

    def mark_done(self, success: int, skip: int, failed: int):
        self._status = "done"
        d = DESIGN
        total = success + failed
        fail_rate = failed / total if total > 0 else 0
        count_text = f"下载 {success} · 跳过 {skip} · 失败 {failed}{self._elapsed_text()}"
        if fail_rate >= 0.10:
            self._update(f"{self.seq:02d}  ⚠️", d["warning"], f"完成 (失败 {failed})", d["warning"],
                         count_text, d["text_secondary"],
                         bar_val=1.0, bar_color=d["warning"], border=d["warning"])
        else:
            self._update(f"{self.seq:02d}  ✅", d["success"], "完成", d["success"],
                         count_text, d["text_secondary"],
                         bar_val=1.0, bar_color=d["success"], border=d["success"])

    def mark_error(self, error: str):
        self._status = "error"
        d = DESIGN
        self._update(f"{self.seq:02d}  ❌", d["error"], "失败", d["error"],
                     f"{error[:50]}{self._elapsed_text()}",
                     bar_color=d["error"], border=d["error"])


class ProgressPage(ctk.CTkFrame):

    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self._app = app
        self._cards: dict[int, ChannelCard] = {}
        self._stat_labels: dict[str, ctk.CTkLabel] = {}
        self._total_channels = 0
        self._paused = False
        self._task_start_time: float | None = None
        self._timer_id = None
        self._build()

    def _build(self):
        d = DESIGN

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=48, pady=(36, 0))
        self._title = ctk.CTkLabel(header, text="下载进度", font=d["font_display"], text_color=d["text_primary"])
        self._title.pack(anchor="w")

        # 统计条
        sb = ctk.CTkFrame(self, fg_color=d["surface"], corner_radius=d["radius_sm"], border_width=1, border_color=d["border_light"])
        sb.pack(fill="x", padx=48, pady=(16, 0))
        si = ctk.CTkFrame(sb, fg_color="transparent")
        si.pack(fill="x", padx=24, pady=14)

        for key, label, color in [("done", "已完成", d["success"]), ("running", "进行中", d["accent"]),
                                   ("waiting", "等待中", d["text_muted"]), ("failed", "失败", d["error"])]:
            col = ctk.CTkFrame(si, fg_color="transparent")
            col.pack(side="left", padx=(0, 40))
            num = ctk.CTkLabel(col, text="0", font=d["font_stat"], text_color=color)
            num.pack()
            ctk.CTkLabel(col, text=label, font=d["font_small"], text_color=d["text_muted"]).pack()
            self._stat_labels[key] = num

        # 总用时计时器
        tcol = ctk.CTkFrame(si, fg_color="transparent")
        tcol.pack(side="left")
        self._elapsed_label = ctk.CTkLabel(tcol, text="⏱ 00:00", font=d["font_stat"], text_color=d["text_secondary"])
        self._elapsed_label.pack()
        ctk.CTkLabel(tcol, text="总用时", font=d["font_small"], text_color=d["text_muted"]).pack()

        qh = ctk.CTkFrame(self, fg_color="transparent")
        qh.pack(fill="x", padx=48, pady=(16, 0))
        ctk.CTkLabel(qh, text="任务队列", font=d["font_subhead"], text_color=d["text_primary"]).pack(side="left")
        self._queue_summary = ctk.CTkLabel(qh, text="", font=d["font_caption"], text_color=d["text_muted"])
        self._queue_summary.pack(side="right")

        self._scroll_frame = ctk.CTkScrollableFrame(self, fg_color="transparent", corner_radius=0, border_width=0)
        self._scroll_frame.pack(fill="both", expand=True, padx=48, pady=(8, 0))

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=48, pady=20)

        lb = ctk.CTkFrame(footer, fg_color="transparent")
        lb.pack(side="left")

        self._clear_btn = ctk.CTkButton(lb, text="清空记录", command=self._clear_cache,
                                        font=d["font_caption"], fg_color=d["surface"], hover_color=d["border"],
                                        text_color=d["text_muted"], border_color=d["border"], border_width=1,
                                        corner_radius=d["radius_sm"], height=36, width=80)
        self._clear_btn.pack(side="left", padx=(0, 8))

        self._pause_btn = ctk.CTkButton(lb, text="暂停", command=self._toggle_pause,
                                        font=d["font_body"], fg_color=d["surface"], hover_color=d["accent_light"],
                                        text_color=d["accent"], border_color=d["border"], border_width=1,
                                        corner_radius=d["radius_sm"], height=36, width=80)
        self._pause_btn.pack(side="left", padx=(0, 8))

        self._cancel_task_btn = ctk.CTkButton(lb, text="取消任务", command=self._cancel_all_tasks,
                                              font=d["font_body"], fg_color=d["surface"], hover_color=d["error"],
                                              text_color=d["error"], border_color=d["border"], border_width=1,
                                              corner_radius=d["radius_sm"], height=36, width=80)
        self._cancel_task_btn.pack(side="left")

        # 右侧
        self._back_btn = ctk.CTkButton(footer, text="返回首页", command=lambda: self._app.show_page("start"),
                                       font=d["font_body"], fg_color=d["accent"], hover_color=d["accent_hover"],
                                       text_color="#FFFFFF", corner_radius=d["radius_sm"], height=36, width=100)
        self._back_btn.pack(side="right")

    def _refresh_stats(self):
        counts = {"done": 0, "running": 0, "waiting": 0, "failed": 0}
        for c in self._cards.values():
            if c._status == "done":
                counts["done"] += 1
            elif c._status == "error":
                counts["failed"] += 1
            elif c._status in ("discover", "download"):
                counts["running"] += 1
            elif c._status == "waiting":
                counts["waiting"] += 1
        for k, lbl in self._stat_labels.items():
            lbl.configure(text=str(counts.get(k, 0)))
        self._queue_summary.configure(text=f"已完成 {counts['done'] + counts['failed']}/{self._total_channels} 个频道")

    def _start_timer(self):
        """任务开始计时。"""
        self._stop_timer()
        self._task_start_time = time.time()
        self._elapsed_label.configure(text="⏱ 00:00")
        self._tick_timer()

    def _stop_timer(self):
        if self._timer_id:
            self.after_cancel(self._timer_id)
            self._timer_id = None

    def _tick_timer(self):
        if self._task_start_time is not None:
            self._elapsed_label.configure(text=f"⏱ {_fmt_duration(time.time() - self._task_start_time)}")
            self._timer_id = self.after(1000, self._tick_timer)

    def _reset_timer(self):
        """清空计时归零。"""
        self._stop_timer()
        self._task_start_time = None
        self._elapsed_label.configure(text="⏱ 00:00")

    def _toggle_pause(self):
        self._paused = not self._paused
        d = DESIGN
        if self._paused:
            self._pause_btn.configure(text="继续", fg_color=d["accent"], text_color="#FFFFFF")
            if self._app._orchestrator:
                self._app._orchestrator.pause()
        else:
            self._pause_btn.configure(text="暂停", fg_color=d["surface"], text_color=d["accent"])
            if self._app._orchestrator:
                self._app._orchestrator.resume()

    def _cancel_all_tasks(self):
        """取消当前和所有待处理任务。"""
        if self._app._orchestrator:
            self._app._orchestrator.cancel()
        logger.info("所有任务已取消")

    def _clear_cache(self):
        # 下载中清空会连带取消任务（用户预期：清空 = 全部停止）
        if self._app.is_downloading:
            if not messagebox.askyesno("确认", "当前有下载任务正在运行。\n清空记录将同时取消下载任务，确定？"):
                return
            self._app.cancel_download()
        cd = CONFIG_DIR / "cache"
        if cd.exists():
            shutil.rmtree(cd)
            cd.mkdir(parents=True, exist_ok=True)
        # 同时清空界面卡片
        for card in self._cards.values():
            card.destroy()
        self._cards.clear()
        self._total_channels = 0
        self._title.configure(text="下载进度")
        self._queue_summary.configure(text="")
        self._reset_timer()
        self._refresh_stats()
        logger.info("缓存和任务队列已清空")

    def init_channels(self, count: int, channels: list[tuple] = None):
        self._total_channels = count
        self._title.configure(text=f"下载进度 (共 {count} 个频道)")
        if channels:
            for c in self._cards.values():
                c.destroy()
            self._cards.clear()
            for seq, url, name in channels:
                card = ChannelCard(self._scroll_frame, seq, name, url)
                card.pack(fill="x", pady=(0, 8))
                self._cards[seq] = card
        self._start_timer()  # 任务开始计时
        self._refresh_stats()

    def append_channels(self, channels: list[tuple], total: int):
        """追加新频道卡片到队列末尾。"""
        self._total_channels = total
        self._title.configure(text=f"下载进度 (共 {total} 个频道)")
        for seq, url, name in channels:
            card = ChannelCard(self._scroll_frame, seq, name, url)
            card.pack(fill="x", pady=(0, 8))
            self._cards[seq] = card
        self._refresh_stats()

    def add_channel_card(self, seq: int, name: str, url: str):
        card = self._cards.get(seq)
        if card:
            card._status = "discover"
        else:
            card = ChannelCard(self._scroll_frame, seq, name, url)
            card.pack(fill="x", pady=(0, 8))
            self._cards[seq] = card
        if card._start_time is None:
            card._start_time = time.time()  # 频道开始处理，记录起始时间
        self._refresh_stats()

    def update_channel_card(self, seq: int, phase: str, done: int, total: int, message: str):
        card = self._cards.get(seq)
        if not card:
            return
        if phase == "discover":
            card.update_discover(done, total, message)
        elif phase == "download":
            card.update_download(done, total, message)
        self._refresh_stats()

    def update_channel_card_status(self, seq: int, status: str, success: int = 0,
                                   skip: int = 0, failed: int = 0, error: str = ""):
        card = self._cards.get(seq)
        if not card:
            return
        if status == "done":
            card.mark_done(success, skip, failed)
        elif status == "error":
            card.mark_error(error)
        self._refresh_stats()

    def show_summary(self, stats: dict):
        self._stop_timer()  # 停止走动，保留最终用时
        if stats.get("cancelled"):
            self._title.configure(text="已取消")
        else:
            self._title.configure(text="全部完成 🎉")
        self._pause_btn.pack_forget()
        self._cancel_task_btn.pack_forget()
        self._refresh_stats()
        try:
            self._scroll_frame._parent_canvas.yview_moveto(0)
        except AttributeError:
            pass
