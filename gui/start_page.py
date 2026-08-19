"""
首页：选择 Excel + 设置参数 + 队列管理。
"""

import os
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from tkinterdnd2 import DND_FILES

from gui.design import DESIGN
from config.settings import get_setting, save_config, CONFIG_DIR
from services.excel_reader import read_channels
from services.shorts_downloader import export_cookies_from_browser, _detect_browser


class StartPage(ctk.CTkFrame):

    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self._app = app
        self._excel_path: str | None = None
        self._output_dir: str = get_setting("output_dir", str(Path.home() / "Downloads" / "YT-Shorts"))
        self._max_shorts: int = get_setting("max_shorts_per_channel", 150)
        self._cookies_mode: str = get_setting("cookies_mode", "off")
        self._cookies_browser: str = get_setting("cookies_browser", "chrome")
        self._cookies_file: str = get_setting("cookies_file", "")
        self._speed_mode: str = get_setting("speed_mode", "stable")
        self._build()

    def _build(self):
        d = DESIGN

        # ── 顶部：标题 + 右侧提示 ──
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=48, pady=(20, 0))

        left_h = ctk.CTkFrame(header, fg_color="transparent")
        left_h.pack(side="left", anchor="w")

        ctk.CTkLabel(left_h, text="TG下载器", font=d["font_display"], text_color=d["text_primary"]).pack(anchor="w")
        ctk.CTkLabel(left_h, text="YouTube Shorts 批量下载 · 按播放量排序 · 自动归档",
                     font=d["font_body"], text_color=d["text_secondary"]).pack(anchor="w", pady=(2, 0))

        # 右侧提示（横排）
        right_h = ctk.CTkFrame(header, fg_color="transparent")
        right_h.pack(side="right", anchor="e")

        tips = [
            ("📊", "按播放量排序"),
            ("📂", "自动归档"),
            ("🔄", "断点续传"),
        ]
        for icon, desc in tips:
            ctk.CTkLabel(right_h, text=f"{icon} {desc}",
                         font=d["font_small"], text_color=d["text_muted"]).pack(side="left", padx=(12, 0))

        # ── 三栏内容区 ──
        content_row = ctk.CTkFrame(self, fg_color="transparent")
        content_row.pack(fill="both", expand=True, padx=48, pady=12)

        # 提前检测浏览器（col3 需要）
        self._detected_browser = _detect_browser()
        _browser_label = {"chrome": "Chrome", "edge": "Edge", "brave": "Brave", "firefox": "Firefox", "opera": "Opera"}
        _browser_name = _browser_label.get(self._detected_browser, "浏览器")

        # ═══════ 第1栏：Excel 文件 ═══════
        col1 = ctk.CTkFrame(content_row, fg_color=d["surface"], corner_radius=d["radius"],
                            border_width=1, border_color=d["border_light"])
        col1.pack(side="left", fill="both", expand=True)

        ctk.CTkLabel(col1, text="📂  选择表格", font=d["font_subhead"], text_color=d["text_primary"]).pack(anchor="w", padx=20, pady=(16, 0))

        self._drop_frame = ctk.CTkFrame(col1, fg_color=d["surface_elevated"], corner_radius=d["radius_sm"],
                                        border_width=2, border_color=d["border"])
        self._drop_frame.pack(fill="x", padx=20, pady=10, ipady=16)
        self._drop_frame.bind("<Button-1>", lambda e: self._pick_excel())
        self._drop_frame.drop_target_register(DND_FILES)
        self._drop_frame.dnd_bind("<<Drop>>", self._on_drop)

        self._drop_icon = ctk.CTkLabel(self._drop_frame, text="📁", font=("Microsoft YaHei", 24), text_color=d["text_muted"])
        self._drop_icon.pack(pady=(16, 0))
        self._drop_icon.bind("<Button-1>", lambda e: self._pick_excel())
        self._drop_label = ctk.CTkLabel(self._drop_frame, text="点击或拖入 Excel 文件", font=d["font_body"], text_color=d["text_secondary"])
        self._drop_label.pack(pady=(2, 0))
        self._drop_label.bind("<Button-1>", lambda e: self._pick_excel())
        ctk.CTkLabel(self._drop_frame, text="A 列 = 频道链接  |  B 列 = 频道名  |  C 列 = 序号",
                     font=d["font_small"], text_color=d["text_muted"]).pack(pady=(2, 12))

        self._file_status = ctk.CTkLabel(col1, text="尚未选择文件", font=d["font_caption"], text_color=d["text_muted"])
        self._file_status.pack(anchor="w", padx=20, pady=(0, 2))
        self._channel_count_label = ctk.CTkLabel(col1, text="", font=d["font_caption"], text_color=d["accent"])
        self._channel_count_label.pack(anchor="w", padx=20, pady=(0, 4))

        ctk.CTkLabel(col1, text="保存到", font=d["font_caption"], text_color=d["text_secondary"]).pack(anchor="w", padx=20, pady=(4, 0))
        out_row = ctk.CTkFrame(col1, fg_color="transparent")
        out_row.pack(fill="x", padx=20, pady=(2, 16))
        self._out_dir_var = ctk.StringVar(value=self._output_dir)
        ctk.CTkEntry(out_row, textvariable=self._out_dir_var, font=d["font_caption"],
                     fg_color=d["surface_elevated"], border_color=d["border"],
                     corner_radius=d["radius_sm"], height=34).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(out_row, text="浏览", command=self._pick_output_dir,
                      font=d["font_caption"], fg_color=d["surface_elevated"], hover_color=d["border"],
                      text_color=d["text_primary"], border_color=d["border"], border_width=1,
                      corner_radius=d["radius_sm"], width=50, height=34).pack(side="right", padx=(6, 0))

        # ═══════ 第2栏：设置 + 操作 ═══════
        col2 = ctk.CTkFrame(content_row, fg_color=d["surface"], corner_radius=d["radius"],
                            border_width=1, border_color=d["border_light"])
        col2.pack(side="left", fill="both", expand=True, padx=(12, 0))

        ctk.CTkLabel(col2, text="⚙️  设置", font=d["font_subhead"], text_color=d["text_primary"]).pack(anchor="w", padx=20, pady=(16, 12))

        ctk.CTkLabel(col2, text="每个频道下载数量", font=d["font_body"], text_color=d["text_secondary"]).pack(anchor="w", padx=20)
        cr = ctk.CTkFrame(col2, fg_color="transparent")
        cr.pack(fill="x", padx=20, pady=(4, 0))
        self._count_var = ctk.StringVar(value=str(self._max_shorts))
        def vc(v):
            return v == "" or (v.isdigit() and 1 <= int(v) <= 999)
        ctk.CTkEntry(cr, textvariable=self._count_var, font=d["font_subhead"],
                     fg_color=d["surface_elevated"], border_color=d["border"],
                     corner_radius=d["radius_sm"], height=38, width=70,
                     validate="key", validatecommand=(self.register(vc), "%P")).pack(side="left")
        ctk.CTkLabel(cr, text="条 Shorts", font=d["font_body"], text_color=d["text_muted"]).pack(side="left", padx=(8, 0))

        ctk.CTkLabel(col2, text="下载画质", font=d["font_body"], text_color=d["text_secondary"]).pack(anchor="w", padx=20, pady=(12, 0))
        self._quality_var = ctk.StringVar(value="1080p")
        ctk.CTkOptionMenu(col2, values=["1080p", "720p", "480p", "最高"], variable=self._quality_var,
                          font=d["font_body"], fg_color=d["surface_elevated"],
                          button_color=d["accent"], button_hover_color=d["accent_hover"],
                          text_color=d["text_primary"], corner_radius=d["radius_sm"], height=36).pack(fill="x", padx=20, pady=(4, 0))

        ctk.CTkLabel(col2, text="下载速度", font=d["font_body"], text_color=d["text_secondary"]).pack(anchor="w", padx=20, pady=(12, 0))
        _speed_labels = {"stable": "稳定模式", "turbo": "极速模式 ⚡", "ultra": "超速模式 🔥"}
        self._speed_var = ctk.StringVar(value=_speed_labels.get(self._speed_mode, "稳定模式"))
        ctk.CTkOptionMenu(col2, values=["稳定模式", "极速模式 ⚡", "超速模式 🔥"], variable=self._speed_var,
                          font=d["font_body"], fg_color=d["surface_elevated"],
                          button_color=d["accent"], button_hover_color=d["accent_hover"],
                          text_color=d["text_primary"], corner_radius=d["radius_sm"], height=36,
                          command=self._on_speed_change).pack(fill="x", padx=20, pady=(4, 0))
        self._speed_hint = ctk.CTkLabel(
            col2, text="", font=d["font_small"], text_color=d["text_muted"],
        )
        self._speed_hint.pack(anchor="w", padx=20, pady=(2, 0))
        self._update_speed_hint()

        # 操作按钮
        ctk.CTkFrame(col2, fg_color=d["border_light"], height=1).pack(fill="x", padx=20, pady=(16, 0))
        self._queue_btn = ctk.CTkButton(col2, text="下载队列", command=self._on_back_to_queue,
                                        font=d["font_body"], fg_color=d["surface"],
                                        hover_color=d["accent_light"], text_color=d["accent"],
                                        border_color=d["accent"], border_width=1,
                                        corner_radius=d["radius_sm"], height=38)
        self._start_btn = ctk.CTkButton(col2, text="开始下载", command=self._on_start,
                                        font=d["font_subhead"], fg_color=d["accent"],
                                        hover_color=d["accent_hover"], text_color="#FFFFFF",
                                        corner_radius=d["radius_sm"], height=46, state="disabled")
        self._add_task_btn = ctk.CTkButton(col2, text="添加新任务", command=self._on_add_task,
                                           font=d["font_subhead"], fg_color=d["surface"],
                                           hover_color=d["accent_light"], text_color=d["accent"],
                                           border_color=d["accent"], border_width=1,
                                           corner_radius=d["radius_sm"], height=46, state="disabled")

        # ═══════ 第3栏：Cookies ═══════
        col3 = ctk.CTkFrame(content_row, fg_color=d["surface"], corner_radius=d["radius"],
                            border_width=1, border_color=d["border_light"])
        col3.pack(side="left", fill="both", expand=True, padx=(12, 0))

        ctk.CTkLabel(col3, text="🔐  Cookies 验证", font=d["font_subhead"], text_color=d["text_primary"]).pack(anchor="w", padx=20, pady=(16, 0))
        ctk.CTkLabel(col3, text="避免 YouTube 机器人检测", font=d["font_small"], text_color=d["text_muted"]).pack(anchor="w", padx=20, pady=(0, 8))

        self._export_cookies_btn = ctk.CTkButton(
            col3, text=f"📤 一键导出 {_browser_name} Cookies", command=self._on_export_cookies,
            font=d["font_body"], fg_color=d["accent"], hover_color=d["accent_hover"],
            text_color="#FFFFFF", corner_radius=d["radius_sm"], height=36,
        )
        self._export_cookies_btn.pack(fill="x", padx=20, pady=(0, 0))

        cookies_hint_row = ctk.CTkFrame(col3, fg_color="transparent")
        cookies_hint_row.pack(fill="x", padx=20, pady=(2, 0))
        self._cookies_status_label = ctk.CTkLabel(
            cookies_hint_row, text="", font=d["font_small"], text_color=d["text_muted"],
        )
        self._cookies_status_label.pack(side="left")
        self._manual_export_link = ctk.CTkLabel(
            cookies_hint_row, text="手动导出", cursor="hand2",
            font=d["font_small"], text_color=d["accent"],
        )
        self._manual_export_link.pack(side="right")
        self._manual_export_link.bind("<Button-1>", lambda e: self._show_manual_export_guide())
        self._refresh_cookies_status()

        adv_row = ctk.CTkFrame(col3, fg_color="transparent")
        adv_row.pack(fill="x", padx=20, pady=(6, 0))
        _mode_labels = {"off": "不使用", "browser": "Chrome", "file": "自定义文件"}
        _current_label = _mode_labels.get(self._cookies_mode, "不使用")
        self._cookies_mode_var = ctk.StringVar(value=_current_label)
        self._cookies_menu = ctk.CTkOptionMenu(
            adv_row, values=["不使用", "Chrome", "Edge", "Firefox", "Brave", "Opera", "自定义文件"],
            variable=self._cookies_mode_var,
            font=d["font_caption"], fg_color=d["surface_elevated"],
            button_color=d["accent"], button_hover_color=d["accent_hover"],
            text_color=d["text_primary"], corner_radius=d["radius_sm"], height=30,
            command=self._on_cookies_mode_change, width=95,
        )
        self._cookies_menu.pack(side="left")

        self._cookies_browser_warn = ctk.CTkLabel(
            adv_row, text="⚠ 下载前请关闭浏览器", font=d["font_small"], text_color=d["warning"],
        )
        if self._cookies_mode == "browser":
            self._cookies_browser_warn.pack(side="left", padx=(6, 0))

        self._cookies_file_frame = ctk.CTkFrame(col3, fg_color="transparent")
        self._cookies_file_var = ctk.StringVar(value=self._cookies_file)
        ctk.CTkEntry(self._cookies_file_frame, textvariable=self._cookies_file_var,
                     font=d["font_small"], fg_color=d["surface_elevated"],
                     border_color=d["border"], corner_radius=d["radius_sm"], height=28).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(self._cookies_file_frame, text="浏览", command=self._pick_cookies_file,
                      font=d["font_small"], fg_color=d["surface_elevated"], hover_color=d["border"],
                      text_color=d["text_primary"], border_color=d["border"], border_width=1,
                      corner_radius=d["radius_sm"], width=44, height=28).pack(side="right", padx=(4, 0))
        if self._cookies_mode == "file":
            self._cookies_file_frame.pack(fill="x", padx=20, pady=(4, 0))

        # 版本号
        self._ver_label = ctk.CTkLabel(self, text="v1.3", font=d["font_small"], text_color=d["text_muted"])
        self._ver_label.place(relx=1.0, rely=1.0, x=-56, y=-16, anchor="se")

        self._refresh_buttons()

    def on_show(self):
        self._refresh_buttons()

    def _refresh_buttons(self):
        downloading = self._app.is_downloading
        # 下载队列按钮始终可见
        self._queue_btn.pack(fill="x", padx=20, pady=(16, 8))

        if downloading:
            self._start_btn.pack_forget()
            self._add_task_btn.pack(fill="x", padx=20, pady=(0, 8))
            self._add_task_btn.configure(state="normal" if self._excel_path else "disabled")
        else:
            self._add_task_btn.pack_forget()
            self._start_btn.pack(fill="x", padx=20, pady=(0, 8))
            self._start_btn.configure(
                state="normal" if self._excel_path else "disabled",
                text="开始下载")

    def _on_back_to_queue(self):
        self._app.show_page("progress")

    def _on_add_task(self):
        if not self._excel_path:
            return
        out = self._out_dir_var.get().strip() or str(Path.home() / "Downloads" / "YT-Shorts")
        os.makedirs(out, exist_ok=True)
        try:
            ms = int(self._count_var.get())
            ms = max(1, min(ms, 999))
        except ValueError:
            ms = 150
        self._app.add_to_queue(self._excel_path, ms, self._quality_var.get(), self._speed_mode)
        self._excel_path = None
        self._update_after_pick()

    def _on_drop(self, event):
        """处理拖入的文件。"""
        files = self._app.tk.splitlist(event.data)
        if files:
            path = files[0].strip("{}")
            if path.lower().endswith((".xlsx", ".xlsm")):
                self._excel_path = path
                self._update_after_pick()

    def _update_after_pick(self):
        if self._excel_path:
            d = DESIGN
            self._drop_icon.configure(text="✅", text_color=d["accent"])
            self._drop_label.configure(text=Path(self._excel_path).name, text_color=d["text_primary"])
            self._file_status.configure(text=f"已选择 {self._excel_path}", text_color=d["text_secondary"])
            # 预读取 Excel 显示频道数
            try:
                channels = read_channels(self._excel_path)
                self._channel_count_label.configure(text=f"读取到 {len(channels)} 条频道链接")
            except Exception:
                self._channel_count_label.configure(text="")
        else:
            d = DESIGN
            self._drop_icon.configure(text="📁", text_color=d["text_muted"])
            self._drop_label.configure(text="点击或拖入 Excel 文件", text_color=d["text_secondary"])
            self._file_status.configure(text="尚未选择文件", text_color=d["text_muted"])
            self._channel_count_label.configure(text="")
        self._refresh_buttons()

    def _pick_excel(self):
        path = filedialog.askopenfilename(title="选择 Excel 文件", filetypes=[("Excel 文件", "*.xlsx *.xlsm"), ("所有文件", "*.*")])
        if path:
            self._excel_path = path
            self._update_after_pick()

    def _pick_output_dir(self):
        path = filedialog.askdirectory(title="选择保存目录", initialdir=self._out_dir_var.get())
        if path:
            self._out_dir_var.set(path)
            self._output_dir = path

    def _on_cookies_mode_change(self, choice: str):
        """cookies 方式切换：显示/隐藏文件选择器和提示。"""
        if choice == "自定义文件":
            self._cookies_mode = "file"
            self._cookies_browser_warn.pack_forget()
            self._cookies_file_frame.pack(fill="x", padx=24, pady=(4, 0))
        elif choice in ("Chrome", "Edge", "Firefox", "Brave", "Opera"):
            self._cookies_mode = "browser"
            self._cookies_browser = choice.lower()
            self._cookies_file_frame.pack_forget()
            self._cookies_browser_warn.pack(side="left", padx=(8, 0))
        else:  # 不使用
            self._cookies_mode = "off"
            self._cookies_file_frame.pack_forget()
            self._cookies_browser_warn.pack_forget()
        # 立即保存 cookies 配置
        save_config({
            "cookies_mode": self._cookies_mode,
            "cookies_browser": self._cookies_browser,
            "cookies_file": self._cookies_file if self._cookies_mode == "file" else "",
        })
        self._refresh_cookies_status()

    def _show_manual_export_guide(self):
        """显示手动导出 cookies 的操作指南。"""
        _browser_label = {"chrome": "Chrome", "edge": "Edge", "brave": "Brave", "firefox": "Firefox", "opera": "Opera"}
        _browser_name = _browser_label.get(self._detected_browser, "Chrome")
        messagebox.showinfo(
            "手动导出 Cookies",
            f"自动导出不可用时，请手动操作（只需一次）：\n\n"
            f"1. 在 {_browser_name} 中打开 Chrome 应用商店\n"
            f"   搜索「Get cookies.txt LOCALLY」并安装\n\n"
            f"2. 打开 youtube.com，确保已登录\n\n"
            f"3. 点击右上角扩展图标 → Export cookies.txt\n"
            f"   文件会保存到下载文件夹\n\n"
            f"4. 回到本软件 → 下方高级选项\n"
            f"   选择「自定义文件」→ 浏览选择 cookies.txt\n\n"
            f"完成后状态栏会显示「✅ Cookies 已就绪」。",
        )

    def _refresh_cookies_status(self):
        """刷新 cookies 状态显示。"""
        d = DESIGN
        cookie_file = CONFIG_DIR / "cookies.txt"
        if self._cookies_mode == "file" and self._cookies_file and os.path.exists(self._cookies_file):
            self._cookies_status_label.configure(text="✅ Cookies 已就绪", text_color=d["success"])
        elif cookie_file.exists() and cookie_file.stat().st_size > 100:
            self._cookies_status_label.configure(text="✅ Cookies 已就绪 (Chrome)", text_color=d["success"])
        else:
            self._cookies_status_label.configure(text="未配置 — 点击上方按钮一键导出", text_color=d["text_muted"])

    def _on_export_cookies(self):
        """一键导出浏览器 cookies。"""
        _browser_label = {"chrome": "Chrome", "edge": "Edge", "brave": "Brave", "firefox": "Firefox", "opera": "Opera"}
        _browser_name = _browser_label.get(self._detected_browser, "浏览器")

        if not self._detected_browser:
            messagebox.showerror(
                "未检测到浏览器",
                "未在电脑上检测到 Chrome / Edge / Brave 等浏览器。\n\n"
                "请先安装 Chrome 浏览器并登录 YouTube。",
            )
            return

        ok = messagebox.askokcancel(
            "导出 Cookies",
            f"即将从 {_browser_name} 浏览器导出 YouTube 登录信息。\n\n"
            f"操作步骤：\n"
            f"1. 确认已在 {_browser_name} 中登录 YouTube\n"
            f"2. 关闭所有 {_browser_name} 窗口\n"
            f"3. 回到本软件，点击「确定」\n\n"
            f"之后无需重复此操作。",
        )
        if not ok:
            return

        output_path = str(CONFIG_DIR / "cookies.txt")
        self._export_cookies_btn.configure(text="导出中...", state="disabled")
        self.update_idletasks()

        success, error_msg = export_cookies_from_browser(self._detected_browser, output_path)

        if success:
            self._cookies_mode = "file"
            self._cookies_file = output_path
            self._cookies_file_var.set(output_path)
            save_config({
                "cookies_mode": "file",
                "cookies_file": output_path,
            })
            self._refresh_cookies_status()
            messagebox.showinfo("导出成功", "Cookies 已保存！\n\n以后下载无需重复此操作。\n如遇下载失败，重新导出即可。")
        elif "dpapi" in error_msg.lower() or "decrypt" in error_msg.lower():
            # DPAPI 失败 → 引导用户手动导出
            messagebox.showwarning(
                "自动导出失败",
                f"无法自动读取 {_browser_name} 的 Cookies（Windows 安全策略限制）。\n"
                f"请改用下方「如自动导出失败 → 点此查看手动方法」链接中的步骤。",
            )
        else:
            messagebox.showerror("导出失败", error_msg)

        self._export_cookies_btn.configure(text=f"📤 一键导出 {_browser_name} Cookies", state="normal")

    def _on_speed_change(self, choice: str):
        """速度模式切换：保存配置并更新提示。"""
        if choice.startswith("超速"):
            self._speed_mode = "ultra"
        elif choice.startswith("极速"):
            self._speed_mode = "turbo"
        else:
            self._speed_mode = "stable"
        save_config({"speed_mode": self._speed_mode})
        self._update_speed_hint()

    def _update_speed_hint(self):
        d = DESIGN
        # ⚠️ 生产版本各档位的精确并发/连接参数已脱敏
        if self._speed_mode == "ultra":
            self._speed_hint.configure(
                text="最高并发、失败即跳过；适合高带宽网络环境",
                text_color=d["warning"],
            )
        elif self._speed_mode == "turbo":
            self._speed_hint.configure(
                text="较高并发，速度快；可能触发平台临时限流",
                text_color=d["warning"],
            )
        else:
            self._speed_hint.configure(
                text="低并发，稳定不易被限流（推荐）",
                text_color=d["text_muted"],
            )

    def _pick_cookies_file(self):
        path = filedialog.askopenfilename(
            title="选择 Cookies 文件",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
        )
        if path:
            self._cookies_file = path
            self._cookies_file_var.set(path)
            save_config({"cookies_file": path})

    def _on_start(self):
        if not self._excel_path:
            return
        out = self._out_dir_var.get().strip() or str(Path.home() / "Downloads" / "YT-Shorts")
        os.makedirs(out, exist_ok=True)
        try:
            ms = int(self._count_var.get())
            ms = max(1, min(ms, 999))
        except ValueError:
            ms = 150
        save_config({
            "output_dir": out,
            "max_shorts_per_channel": ms,
            "cookies_mode": self._cookies_mode,
            "cookies_browser": self._cookies_browser,
            "cookies_file": self._cookies_file if self._cookies_mode == "file" else "",
            "speed_mode": self._speed_mode,
        })
        self._app.start_download(self._excel_path, out, ms, self._quality_var.get(), self._speed_mode)
        self._refresh_buttons()
