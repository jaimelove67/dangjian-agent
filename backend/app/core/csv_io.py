"""CSV 输出工具（各模块导出共用）。

两件事必须统一，否则每个导出处各写一遍、各修一遍：

- **UTF-8 BOM**：Excel 直接双击打开中文 CSV 不乱码；
- **危险首字符转文本**：以 ``= + - @`` 或制表 / 换行开头的单元格会被 Excel 当公式或换行
  处理，可能造成公式注入——统一加前导撇号转成文本。

只负责"行数据 → CSV 字节"，不含文件名、筛选口径与审计留痕（那些由调用方决定）。
"""

from __future__ import annotations

import csv
import io
from typing import Any, Iterable, Sequence


def csv_bytes(headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> bytes:
    """构造 UTF-8 BOM 的 CSV：Excel 可直接打开，危险首字符按文本处理。"""
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(list(headers))
    for row in rows:
        cells = []
        for value in row:
            text = str(value)
            if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(
                ("\t", "\r", "\n")
            ):
                text = "'" + text
            cells.append(text)
        writer.writerow(cells)
    return output.getvalue().encode("utf-8-sig")
