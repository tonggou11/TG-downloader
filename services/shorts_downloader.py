"""
Shorts 下载服务：用 yt-dlp 下载视频到指定文件夹。

核心流程:
  1. 创建目标文件夹（{output_dir}/{序号两位}_{频道名}/）
  2. 对每个视频 URL，调用 yt-dlp 下载
  3. 支持断点续传（已存在文件跳过）
  4. 记录失败的视频到 failed.txt

依赖: yt-dlp, ffmpeg（自动检测 PATH / 打包路径 / 指定路径）
"""

import hashlib
import json
import logging
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import yt_dlp

from config.settings import get_setting, CONFIG_DIR

logger = logging.getLogger("downloader")

_DONE_CACHE_DIR = CONFIG_DIR / "cache"


def _done_cache_path(target_dir: Path) -> Path:
    """返回断点续传 _done.json 的缓存路径（基于目标文件夹的 hash）。"""
    _DONE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = hashlib.md5(str(target_dir.resolve()).encode()).hexdigest()[:12]
    return _DONE_CACHE_DIR / f"done_{key}.json"


def _cleanup_temp_files(target_dir: Path) -> None:
    """删除 yt-dlp 残留的临时文件 (.part, 未合并的 f*.mp4/f*.m4a/f*.webm)。"""
    patterns = [
        re.compile(r".*\.part$"),        # 下载中断残留
        re.compile(r".*\.f\d+\..*$"),     # 独立流文件 (f137.mp4, f140.m4a 等)
    ]
    for f in target_dir.iterdir():
        if not f.is_file():
            continue
        for pat in patterns:
            if pat.match(f.name):
                try:
                    f.unlink()
                    logger.debug(f"[cleanup] 删除残留文件: {f.name}")
                except OSError:
                    pass
                break


def _find_node() -> str:
    """在系统 PATH 中查找 node.exe。"""
    import shutil as _shutil
    path = _shutil.which("node")
    return path or ""


def _find_deno() -> str:
    """查找 deno.exe（系统 PATH 或打包的 assets/）。"""
    import shutil as _shutil
    path = _shutil.which("deno")
    if path:
        return path
    # PyInstaller 打包后
    if getattr(sys, "frozen", False):
        bundled = os.path.join(sys._MEIPASS, "assets", "deno.exe")
        if os.path.exists(bundled):
            return bundled
    # 开发环境
    dev_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "assets", "deno.exe",
    )
    if os.path.exists(dev_path):
        return dev_path
    return ""


def _detect_browser() -> str:
    """自动检测可用的浏览器，返回浏览器名或空字符串。"""
    for browser in ("chrome", "edge", "brave", "firefox", "opera"):
        try:
            import shutil as _shutil
            if _shutil.which(browser):
                return browser
        except Exception:
            continue
    # 检查默认路径
    appdata = os.environ.get("LOCALAPPDATA", "")
    for name, subpath in [
        ("chrome", "Google\\Chrome\\User Data"),
        ("edge", "Microsoft\\Edge\\User Data"),
        ("brave", "BraveSoftware\\Brave-Browser\\User Data"),
    ]:
        if os.path.isdir(os.path.join(appdata, subpath)):
            return name
    return ""


def export_cookies_from_browser(browser: str, output_path: str) -> tuple[bool, str]:
    """从浏览器导出 cookies 到指定文件。

    返回 (成功, 错误信息)。错误信息为空字符串表示成功。
    """
    try:
        ydl_opts = {
            "cookiesfrombrowser": (browser,),
            "cookiefile": output_path,
            "quiet": True,
            "no_warnings": True,
            "simulate": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download(["https://www.youtube.com"])
        if os.path.exists(output_path) and os.path.getsize(output_path) > 100:
            return (True, "")
        else:
            return (False, "导出失败：cookies 文件为空，请确认浏览器中已登录 YouTube")
    except yt_dlp.utils.DownloadError as e:
        reason = str(e).split("\n")[0][:300]
        rl = reason.lower()
        if "could not find" in rl:
            return (False, f"未找到 {browser} 浏览器数据目录，请确认已安装 {browser}")
        if "could not copy" in rl or "database is locked" in rl:
            return (False, "浏览器未关闭，请关闭所有浏览器窗口后重试")
        if "dpapi" in rl or "decrypt" in rl:
            return (False, f"{browser} cookies 解密失败（Windows 安全策略限制），"
                           f"请尝试用 Chrome 浏览器登录 YouTube 后重试，或手动导出 cookies 文件")
        if "no login" in rl or "not logged in" in rl:
            return (False, f"未在 {browser} 中找到 YouTube 登录信息，请先登录 YouTube")
        return (False, f"导出失败：{reason}")
    except Exception as e:
        return (False, f"导出异常：{type(e).__name__}: {e!s}"[:300])


def _find_aria2c() -> str:
    """查找 aria2c.exe（PyInstaller 打包 assets / 开发环境 assets / 系统 PATH）。"""
    import shutil as _shutil
    path = _shutil.which("aria2c")
    if path:
        return path
    if getattr(sys, "frozen", False):
        bundled = os.path.join(sys._MEIPASS, "assets", "aria2c.exe")
        if os.path.exists(bundled):
            return bundled
    dev_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "assets", "aria2c.exe",
    )
    if os.path.exists(dev_path):
        return dev_path
    return ""


def _get_system_proxy() -> str:
    """获取系统代理地址（如 http://127.0.0.1:33210）。

    优先级：环境变量 → Windows 注册表（Internet Settings）。
    aria2c 不读系统代理，必须显式传入 --all-proxy。
    """
    # 1. 环境变量
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        val = os.environ.get(key, "").strip()
        if val:
            return val if "://" in val else f"http://{val}"

    # 2. Windows 注册表系统代理
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
            proxy_enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
            if proxy_enable:
                proxy_server, _ = winreg.QueryValueEx(key, "ProxyServer")
                if proxy_server:
                    proxy_server = proxy_server.split(";")[0].strip()  # 取第一个，忽略 per-protocol 配置
                    return proxy_server if "://" in proxy_server else f"http://{proxy_server}"
    except (OSError, ImportError):
        pass
    return ""


def _find_ffmpeg(explicit_path: str = "") -> str:
    """自动查找 ffmpeg 路径。

    优先级:
      1. 显式传入的路径
      2. PyInstaller 打包的 assets/ffmpeg.exe
      3. 开发环境下的 assets/ffmpeg.exe
      4. 留空（yt-dlp 从系统 PATH 查找）
    """
    if explicit_path and os.path.exists(explicit_path):
        return explicit_path

    # PyInstaller 打包后临时目录
    if getattr(sys, "frozen", False):
        bundled = os.path.join(sys._MEIPASS, "assets", "ffmpeg.exe")
        if os.path.exists(bundled):
            return bundled

    # 开发环境
    dev_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "assets", "ffmpeg.exe",
    )
    if os.path.exists(dev_path):
        return dev_path

    return explicit_path  # 留空交给 yt-dlp 自己找


# 画质 → yt-dlp format 字符串映射
#
# ⚠️ 生产配置已脱敏：
# 商用版本使用按编码（H.264/AAC）、分辨率、帧率精细过滤的格式串，
# 并处理了竖屏分辨率、播放器兼容性、特定格式流被服务端限制等边缘情况。
# 以下为演示用通用格式串，架构展示版可运行但不包含生产调优。
_QUALITY_FORMATS = {
    "1080p": "bestvideo[height<=1920]+bestaudio/best[height<=1920]/best",
    "720p": "bestvideo[height<=1280]+bestaudio/best[height<=1280]/best",
    "480p": "bestvideo[height<=854]+bestaudio/best[height<=854]/best",
    "最高": "bestvideo+bestaudio/best",
}

# 内部异常：progress hook 中抛出以立即中止当前下载
class _Cancelled(Exception):
    """用户取消任务。"""


class _Paused(Exception):
    """用户暂停任务（.part 保留，恢复后续传）。"""


# 取消时的返回标记（reason 字段）
_CANCELLED_MARKER = "__cancelled__"


def download_shorts(
    shorts: list[dict],
    output_dir: str | Path,
    channel_name: str,
    seq_num: int,
    progress_hook: callable = None,
    ffmpeg_path: str = "",
    quality: str = "1080p",
    cookies_mode: str = "off",
    cookies_browser: str = "chrome",
    cookies_file: str = "",
    cancel_event: threading.Event = None,
    pause_event: threading.Event = None,
    speed_mode: str = "stable",
) -> tuple[int, int, list[str]]:
    """
    下载一个频道的 Shorts。

    参数:
        shorts: Shorts 元数据列表 [{"id","title","view_count","url",...}]
        output_dir: 输出根目录
        channel_name: 频道名（用于创建子文件夹）
        seq_num: 序号（用于文件夹命名）
        progress_hook: 可选进度回调
        ffmpeg_path: ffmpeg.exe 路径（留空则自动查找）
        quality: 画质 "1080p" / "720p" / "480p" / "最高"
        cancel_event: 取消事件（set 时立即中止所有下载）
        pause_event: 暂停事件（clear 时挂起，set 时继续）

    返回:
        (success_count, skip_count, failed_urls)
    """
    # 文件夹名：{序号两位}_{频道名}
    folder_name = f"{seq_num:02d}_{channel_name}"
    target_dir = Path(output_dir) / folder_name
    target_dir.mkdir(parents=True, exist_ok=True)

    failed_urls: list[str] = []

    turbo = speed_mode == "turbo"
    ultra = speed_mode == "ultra"
    sleep_min = get_setting("sleep_min", 1.0)
    sleep_max = get_setting("sleep_max", 3.0)

    ydl_opts = {
        "outtmpl": str(target_dir / "%(title).100s.%(ext)s"),
        "format": _QUALITY_FORMATS.get(quality, _QUALITY_FORMATS["1080p"]),
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    # 稳定模式加下载间隔；极速/超速模式不睡
    if not (turbo or ultra):
        ydl_opts["sleep_interval"] = int(sleep_min)
        ydl_opts["max_sleep_interval"] = int(sleep_max)

    _speed_label = "超速" if ultra else ("极速" if turbo else "稳定")
    ffmpeg = _find_ffmpeg(ffmpeg_path)
    aria2c = _find_aria2c()
    logger.info(f"[{channel_name}] 开始下载 {len(shorts)} 个视频 → {target_dir}, 画质={quality}"
                f", 速度模式={_speed_label}, ffmpeg={ffmpeg or 'auto'}, aria2c={aria2c or '未找到(回退原生下载)'}, cookies={cookies_mode}" +
                (f"({cookies_browser})" if cookies_mode == "browser" else f"({cookies_file})" if cookies_mode == "file" else ""))
    if ffmpeg:
        ydl_opts["ffmpeg_location"] = ffmpeg

    # aria2c 多连接加速（⚠️ 连接数、超时、重试的具体取值为生产调优结果，已脱敏）
    if aria2c:
        ydl_opts["external_downloader"] = aria2c
        aria2c_args = [
            "--split=2",
            "--max-connection-per-server=2",
            "--min-split-size=1M",
            "--file-allocation=none",
            "--max-tries=2",
            "--connect-timeout=30",
        ]
        # aria2c 不读 Windows 系统代理，必须显式传入（VPN 用户依赖此代理）
        proxy = _get_system_proxy()
        if proxy:
            aria2c_args.append(f"--all-proxy={proxy}")
            logger.info(f"[{channel_name}] aria2c 使用代理 {proxy}")
        ydl_opts["external_downloader_args"] = aria2c_args

    # cookies 验证
    if cookies_mode == "browser":
        ydl_opts["cookiesfrombrowser"] = (cookies_browser,)
    elif cookies_mode == "file" and cookies_file:
        ydl_opts["cookiefile"] = cookies_file

    # 使用 cookies 时 yt-dlp 走 web client，需要 JS 运行时解签名
    if cookies_mode != "off":
        js_runtimes = {}
        node_path = _find_node()
        if node_path:
            js_runtimes["node"] = {"path": node_path}
        else:
            deno_path = _find_deno()
            if deno_path:
                js_runtimes["deno"] = {"path": deno_path}
        if js_runtimes:
            ydl_opts["js_runtimes"] = js_runtimes
            ydl_opts["remote_components"] = ["ejs:github"]
        else:
            logger.warning(f"[{channel_name}] 启用了 cookies 但未找到 Node.js 或 Deno 运行时，"
                           "下载可能因 JavaScript 签名解析失败而无法获取视频格式。"
                           "请安装 Node.js (nodejs.org) 或将 deno.exe 放入 assets/ 目录。")

    total = len(shorts)
    done_before = 0

    # 断点续传：加载已完成列表
    done_ids: set[str] = set()
    done_file = _done_cache_path(target_dir)
    if done_file.exists():
        try:
            with open(done_file, "r", encoding="utf-8") as f:
                done_ids = set(json.load(f))
            done_before = len(done_ids)
        except (json.JSONDecodeError, OSError):
            pass

    # 过滤待下载视频
    pending = [s for s in shorts if s["id"] not in done_ids]
    skip_count = total - len(pending)

    if not pending:
        if progress_hook:
            progress_hook("download", total, total, f"全部已下载 ({total} 个)")
        return 0, total, []

    if progress_hook:
        progress_hook("download", done_before, total, f"准备下载 {len(pending)} 个视频 ({total-done_before} 个待下载)")

    success_count = 0
    failed_items: list[tuple[str, str]] = []  # (url, reason)
    _lock = threading.Lock()

    def _is_network_error(reason: str) -> bool:
        """判断错误是否为网络问题（可重试），而非视频本身问题（不可重试）。"""
        rl = reason.lower()
        if any(kw in rl for kw in ("video unavailable", "private video", "age.restricted",
                                    "not available", "copyright", "removed", "terminated",
                                    "no video formats", "not found")):
            return False
        # ⚠️ 生产版本的网络错误分类关键词表已脱敏：
        # 商用版本对 SSL 中断、流截断、外部下载器退出码等数十种
        # 真实网络异常模式做了精确分类，与"内容级错误"严格区分。
        return any(kw in rl for kw in ("timed out", "connection", "timeout"))

    def _is_server_rejection(reason: str) -> bool:
        """判断错误是否为服务器明确拒绝——有限重试，避免轰炸 IP 触发封禁。"""
        rl = reason.lower()
        # ⚠️ 生产版本的拒绝分类关键词表已脱敏（含各下载器的特定退出码映射）
        return any(kw in rl for kw in ("403", "forbidden"))

    def _is_browser_lock_error(reason: str) -> bool:
        """判断错误是否为浏览器 cookies 数据库锁定。"""
        rl = reason.lower()
        return any(kw in rl for kw in ("could not copy", "cookie database",
                                        "cookies database is locked", "cookies.sqlite",
                                        "cannot open", "database is locked"))

    def _is_cookies_format_error(reason: str) -> bool:
        """判断错误是否为 cookies 文件格式不正确。"""
        rl = reason.lower()
        return "netscape format cookies" in rl

    def _check_events():
        """检查取消/暂停事件。取消则抛 _Cancelled；暂停则阻塞等待恢复。"""
        if cancel_event is not None and cancel_event.is_set():
            raise _Cancelled()
        if pause_event is not None and not pause_event.is_set():
            logger.info(f"[{channel_name}] 任务已暂停，等待继续...")
            pause_event.wait()  # 阻塞直到 resume() 或 cancel() 附带 resume()
            if cancel_event is not None and cancel_event.is_set():
                raise _Cancelled()

    def _download_one(short: dict) -> tuple[str, bool, str]:
        """下载单个视频，返回 (url, 是否成功, 失败原因)。每个线程独立 yt-dlp 实例。"""
        url = short["url"]
        vid = short["id"]
        # ⚠️ 生产版本按速度模式细分的精确重试次数已脱敏（演示版统一简化值）
        if ultra:
            MAX_RETRIES = 0      # 超速：失败不重试
            REJECT_RETRIES = 0
        elif turbo:
            MAX_RETRIES = 2      # 极速：快速放弃
            REJECT_RETRIES = 2
        else:
            MAX_RETRIES = 3      # 稳定：有限重试
            REJECT_RETRIES = 2   # 服务器拒绝始终短重试，避免轰炸 IP
        RETRY_DELAY = 5

        for attempt in range(MAX_RETRIES + 1):
            _check_events()  # 每次尝试前检查暂停/取消
            error_msgs: list[str] = []
            finished = False

            def _progress_hook(d):
                nonlocal finished
                # 取消：立即中止
                if cancel_event is not None and cancel_event.is_set():
                    raise _Cancelled()
                # 暂停：挂起下载（.part 保留）
                if pause_event is not None and not pause_event.is_set() \
                        and d.get("status") == "downloading":
                    raise _Paused()
                if d.get("status") == "finished":
                    finished = True
                elif d.get("status") == "error":
                    reason = d.get("msg") or str(d.get("error", ""))
                    if reason:
                        error_msgs.append(reason)

            thread_opts = ydl_opts.copy()
            thread_opts["progress_hooks"] = thread_opts.get("progress_hooks", []) + [_progress_hook]

            try:
                with yt_dlp.YoutubeDL(thread_opts) as ydl:
                    ydl.download([url])

                if finished:
                    return (url, True, "")
                else:
                    # 优先使用进度回调收集到的错误信息
                    if error_msgs:
                        reason = error_msgs[0][:300]
                        if _is_browser_lock_error(reason):
                            reason = "浏览器 cookies 读取失败，请关闭所有浏览器窗口（含任务管理器中的后台进程）后重试，或改用\"自定义文件\"模式"
                    else:
                        reason = "终止但无错误信息"
                    logger.warning(f"[{channel_name}] 下载失败 ({reason}): {url}")
                    return (url, False, reason)

            except _Cancelled:
                logger.info(f"[{channel_name}] 已取消下载: {url}")
                return (url, False, _CANCELLED_MARKER)
            except _Paused:
                # 等待继续后重试同一视频（.part 自动续传）
                if pause_event is not None:
                    pause_event.wait()
                if cancel_event is not None and cancel_event.is_set():
                    return (url, False, _CANCELLED_MARKER)
                logger.info(f"[{channel_name}] 已继续，续传: {url}")
                continue
            except yt_dlp.utils.DownloadError as e:
                reason = str(e).split("\n")[0][:300]
                if _is_cookies_format_error(reason):
                    reason = "cookies 文件格式不正确，可能被其他程序覆盖，请重新导出 cookies 后重试"
                    logger.warning(f"[{channel_name}] 下载失败 ({reason}): {url}")
                    return (url, False, reason)
                if _is_browser_lock_error(reason):
                    reason = f"浏览器 cookies 读取失败，请关闭所有浏览器窗口（含任务管理器中的后台进程）后重试，或改用「自定义文件」模式"
                    logger.warning(f"[{channel_name}] 下载失败 ({reason}): {url}")
                    return (url, False, reason)
                if _is_server_rejection(reason) and attempt < REJECT_RETRIES:
                    logger.info(f"[{channel_name}] 服务器拒绝（403/限流），{RETRY_DELAY}s 后重试 ({attempt+1}/{REJECT_RETRIES})")
                    time.sleep(RETRY_DELAY)
                    continue
                if _is_network_error(reason) and attempt < MAX_RETRIES:
                    logger.info(f"[{channel_name}] 网络错误，{RETRY_DELAY}s 后重试 ({attempt+1}/{MAX_RETRIES})")
                    time.sleep(RETRY_DELAY)
                    continue
                logger.warning(f"[{channel_name}] 下载失败 ({reason}): {url}")
                return (url, False, reason)
            except Exception as e:
                reason = f"{type(e).__name__}: {e!s}"[:300]
                if _is_cookies_format_error(reason):
                    reason = "cookies 文件格式不正确，可能被其他程序覆盖，请重新导出 cookies 后重试"
                    logger.warning(f"[{channel_name}] 下载异常 ({reason}): {url}")
                    return (url, False, reason)
                if _is_browser_lock_error(reason):
                    reason = f"浏览器 cookies 读取失败，请关闭所有浏览器窗口（含任务管理器中的后台进程）后重试，或改用「自定义文件」模式"
                    logger.warning(f"[{channel_name}] 下载异常 ({reason}): {url}")
                    return (url, False, reason)
                if _is_server_rejection(reason) and attempt < REJECT_RETRIES:
                    logger.info(f"[{channel_name}] 服务器拒绝（403/限流），{RETRY_DELAY}s 后重试 ({attempt+1}/{REJECT_RETRIES})")
                    time.sleep(RETRY_DELAY)
                    continue
                if _is_network_error(reason) and attempt < MAX_RETRIES:
                    logger.info(f"[{channel_name}] 网络异常，{RETRY_DELAY}s 后重试 ({attempt+1}/{MAX_RETRIES})")
                    time.sleep(RETRY_DELAY)
                    continue
                logger.warning(f"[{channel_name}] 下载异常 ({reason}): {url}")
                return (url, False, reason)

        # 不应到达这里
        reason = f"重试 {MAX_RETRIES} 次后仍失败"
        logger.warning(f"[{channel_name}] 下载失败 ({reason}): {url}")
        return (url, False, reason)

    # 并发下载（稳定 5 个，极速 10 个，超速 20 个同时下载）
    # ⚠️ 生产版本按速度模式的并发数已脱敏（演示版统一简化值）
    max_workers = 8 if ultra else (5 if turbo else 3)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_download_one, s): s for s in pending}
        for fut in as_completed(futures):
            url, ok, reason = fut.result()
            with _lock:
                if reason == _CANCELLED_MARKER:
                    # 用户取消：停掉未开始的任务，运行中的会在各自 hook 里 1 秒内自行中止
                    pool.shutdown(wait=False, cancel_futures=True)
                    logger.info(f"[{channel_name}] 用户取消，停止剩余下载")
                    if progress_hook:
                        progress_hook("download", done_before + success_count, total,
                                      f"已取消 · 完成 {success_count} · 失败 {len(failed_items)}")
                    return success_count, skip_count, [u for u, _ in failed_items]
                if ok:
                    success_count += 1
                    s = futures[fut]
                    done_ids.add(s["id"])
                    title = str(s.get("title", "")).strip()[:50]
                    logger.info(f"[{channel_name}] ✅ 下载成功 ({done_before + success_count}/{total}): {title or url}")
                    try:
                        with open(done_file, "w", encoding="utf-8") as f:
                            json.dump(list(done_ids), f)
                    except OSError:
                        pass  # 缓存目录可能已被清空（用户清空记录）
                else:
                    failed_items.append((url, reason))
                    if reason:
                        logger.warning(f"[{channel_name}] → 原因: {reason}")

                if progress_hook:
                    progress_hook(
                        "download",
                        done_before + success_count,
                        total,
                        f"完成 {success_count} · 跳过 {skip_count} · 失败 {len(failed_items)}",
                    )

    # 写失败记录 → cache 目录
    if failed_items:
        fail_log = _done_cache_path(target_dir).with_suffix(".failed.txt")
        try:
            with open(fail_log, "w", encoding="utf-8") as f:
                for url, reason in failed_items:
                    f.write(f"{reason}\n{url}\n\n")
        except OSError:
            pass  # 缓存目录可能已被清空

    # 清理 yt-dlp 残留临时文件
    _cleanup_temp_files(target_dir)

    return success_count, skip_count, [url for url, _ in failed_items]
