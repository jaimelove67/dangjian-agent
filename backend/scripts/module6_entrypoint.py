"""读取容器挂载的密钥后启动目标进程。禁止把密钥写入日志或参数。"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    for name in (
        "DATABASE_URL",
        "REDIS_URL",
        "SECRET_KEY",
        "FILE_ENCRYPTION_KEYS",
        "DASHSCOPE_API_KEY",
    ):
        path = os.environ.get(name + "_FILE")
        if path:
            raw = Path(path).read_bytes()
            if len(raw) > 65536:
                raise ValueError("配置文件超过容量")
            value = raw.decode("utf-8-sig").strip()
            if not value and name != "DASHSCOPE_API_KEY":
                raise ValueError("必需配置文件为空")
            os.environ[name] = value
    if len(sys.argv) < 2:
        raise ValueError("缺少启动命令")
    os.execvp(sys.argv[1], sys.argv[1:])
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("startup_configuration_failed:" + type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
