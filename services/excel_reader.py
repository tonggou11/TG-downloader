"""
Excel 读取服务：解析无表头的 .xlsx 表格。

表格格式：
  A 列 (col=0) → 频道链接
  B 列 (col=1) → 频道名
  C 列 (col=2) → 序号

输出：[(序号, 频道链接, 频道名), ...]
"""

import re
from pathlib import Path

import openpyxl


# 文件名非法字符（Windows）
_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')


def safe_filename(name: str) -> str:
    """将频道名转换为安全的文件夹名，替换非法字符为下划线。"""
    # 去掉首尾空格，替换非法字符
    name = name.strip()
    # 去掉 @ 前缀（频道名通常以 @ 开头）
    name = re.sub(r"^@+", "", name)
    name = _INVALID_FILENAME_CHARS.sub("_", name)
    # 去掉连续空格
    name = re.sub(r"\s+", " ", name)
    return name


def normalize_url(url: str) -> str:
    """标准化频道链接。

    支持格式:
      - https://www.youtube.com/@Handle/shorts
      - https://www.youtube.com/@Handle/videos
      - https://www.youtube.com/@Handle
      - https://www.youtube.com/channel/UCxxx/shorts
      - http://...（自动补 https://）
      - @Handle/shorts（自动补完整 URL）

    返回标准化的 Shorts 专区 URL。
    """
    url = url.strip()

    # 自动补协议
    if not url.startswith("http://") and not url.startswith("https://"):
        if url.startswith("@") or url.startswith("youtube"):
            url = "https://www.youtube.com/" + url.lstrip("@")
        elif url.startswith("www."):
            url = "https://" + url
        else:
            url = "https://www.youtube.com/" + url

    # 确保以 /shorts 结尾
    if not url.endswith("/shorts"):
        # 去掉尾部斜杠 + /videos 等
        url = re.sub(r"(/videos|/featured)?$", "", url)
        # 确保只有一个 /
        url = url.rstrip("/")
        url += "/shorts"

    return url


def read_channels(excel_path: str | Path) -> list[tuple[int, str, str]]:
    """
    读取 Excel 文件，返回频道列表。

    参数:
        excel_path: .xlsx 文件路径

    返回:
        [(序号, 标准化URL, 安全频道名), ...]

    异常:
        FileNotFoundError: 文件不存在
        ValueError: 文件格式无效或内容为空
    """
    path = Path(excel_path)

    if not path.exists():
        raise FileNotFoundError(f"找不到文件: {excel_path}")

    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb.active

    channels: list[tuple[int, str, str]] = []
    seen = set()  # 去重

    for row in ws.iter_rows(min_row=1, max_col=3, values_only=True):
        url = str(row[0]).strip() if row[0] is not None else ""
        name = str(row[1]).strip() if row[1] is not None else ""
        seq = row[2] if len(row) > 2 and row[2] is not None else None

        # 跳过空行
        if not url or not name:
            continue
        if url in {"None", "nan", "N/A"} or name in {"None", "nan"}:
            continue

        try:
            url = normalize_url(url)
        except Exception:
            continue

        name = safe_filename(name)

        # 去重
        key = url
        if key in seen:
            continue
        seen.add(key)

        seq_int = int(seq) if seq is not None and str(seq).strip().isdigit() else len(channels) + 1
        channels.append((seq_int, url, name))

    wb.close()

    if not channels:
        raise ValueError("Excel 文件中未找到有效的频道数据")

    return channels
