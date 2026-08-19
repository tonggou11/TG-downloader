#!/usr/bin/env python3
"""
YouTube Shorts 批量下载工具 — GUI 入口。

用法:
    python main.py

打包:
    pyinstaller --onefile --windowed --name "YT-Shorts下载工具" main.py
"""

import logging
import sys
from pathlib import Path

# 把项目根目录加到路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config.settings import CONFIG_DIR, ensure_config_dir

# ── 日志配置 ──
ensure_config_dir()

# 日志文件放在 .exe 同目录下
if getattr(sys, "frozen", False):
    _exe_dir = Path(sys.executable).resolve().parent
else:
    _exe_dir = Path(__file__).resolve().parent
LOG_FILE = _exe_dir / "TG下载器.log"

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("main")
logger.info(f"应用启动 — 日志文件: {LOG_FILE}")

from gui.app import App


def main():
    try:
        app = App()
        app.mainloop()
    except Exception:
        logger.exception("应用异常退出")
        raise


if __name__ == "__main__":
    main()
