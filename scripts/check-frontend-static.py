"""对本次写回的前端文件做静态自检。

会话内 node 无法创建子进程（EBUSY），跑不了 vue-tsc / vite，这里用纯 Python 做三项检查：
  1. SFC 的 <template>/<script>/<style> 块是否配对、标签是否闭合平衡；
  2. 相对与别名导入（#/ 前缀）是否指向真实存在的文件；
  3. element-plus 组件样式导入路径是否存在。

不修改任何文件，只报告。
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "frontend/apps/web-ele"
SRC = APP / "src"
EP = next(
    (ROOT / "frontend/node_modules/.pnpm").glob("element-plus@*/node_modules/element-plus"),
    None,
)

TARGETS = [
    SRC / "api/party/types.ts",
    SRC / "api/party/mock.ts",
    SRC / "api/party/qa.ts",
    SRC / "api/party/knowledge.ts",
    SRC / "api/party/types.ts",
    SRC / "router/routes/modules/party.ts",
    SRC / "views/party/qa/index.vue",
    SRC / "views/party/knowledge/list.vue",
    SRC / "views/party/knowledge/intake.vue",
    SRC / "preferences.ts",
]

VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}

problems: list[str] = []


def resolve_alias(spec: str) -> Path | None:
    """把 #/xxx 与相对路径解析为磁盘路径（不带扩展名）。"""
    if spec.startswith("#/"):
        return SRC / spec[2:]
    return None


def check_vue_blocks(path: Path, text: str) -> None:
    for block in ("template", "script", "style"):
        opens = len(re.findall(rf"<{block}[\s>]", text))
        closes = len(re.findall(rf"</{block}>", text))
        if opens != closes:
            problems.append(f"{path.name}: <{block}> 块数量不匹配（开 {opens} / 闭 {closes}）")

    tmpl = re.search(r"<template>(.*)</template>\s*\n\s*<style", text, re.S)
    if not tmpl:
        problems.append(f"{path.name}: 未找到 <template> 根块")
        return

    body = tmpl.group(1)
    stack: list[str] = []
    for m in re.finditer(r"<(/?)([a-zA-Z][\w.-]*)((?:\"[^\"]*\"|'[^']*'|[^>\"'])*?)(/?)>", body):
        closing, name, _attrs, self_close = m.groups()
        if name.lower() in VOID_TAGS or self_close:
            continue
        if closing:
            if not stack:
                problems.append(f"{path.name}: 多余的闭合标签 </{name}>")
                return
            top = stack.pop()
            if top != name:
                problems.append(
                    f"{path.name}: 标签未正确闭合，期望 </{top}> 实际 </{name}>"
                )
                return
        else:
            stack.append(name)
    if stack:
        problems.append(f"{path.name}: 存在未闭合标签 {stack}")


def check_imports(path: Path, text: str) -> None:
    for m in re.finditer(r"""(?:from|import)\s+['"]([^'"]+)['"]""", text):
        spec = m.group(1)
        if spec.startswith("."):
            base = (path.parent / spec).resolve()
            if not any(
                (base.with_suffix(ext)).exists()
                for ext in ("", ".ts", ".vue", ".js", "/index.ts", "/index.vue")
            ):
                problems.append(f"{path.name}: 相对导入未解析 → {spec}")
            continue

        if spec.startswith("element-plus/es/components/"):
            if EP is None:
                problems.append(f"{path.name}: 未找到 element-plus 包，无法校验 {spec}")
                continue
            if not (EP / spec[len("element-plus/"):]).with_suffix(".mjs").exists():
                problems.append(f"{path.name}: element-plus 样式路径不存在 → {spec}")
            continue

        if spec.startswith("#/"):
            base = resolve_alias(spec)
            assert base is not None
            if not any(
                (base.with_suffix(ext)).exists()
                for ext in ("", ".ts", ".vue", ".js", "/index.ts", "/index.vue")
            ):
                problems.append(f"{path.name}: 别名导入未解析 → {spec}")
            continue

        if spec.startswith("@vben/"):
            continue  # monorepo 内部包

        if spec in ("vue", "vue-router", "element-plus"):
            continue

        problems.append(f"{path.name}: 未识别的导入来源 → {spec}")

    for m in re.finditer(r"import\(\s*['\"]([^'\"]+)['\"]\s*\)", text):
        spec = m.group(1)
        if spec.startswith("#/"):
            base = resolve_alias(spec)
            assert base is not None
            if not base.exists():
                problems.append(f"{path.name}: 动态导入未解析 → {spec}")


def main() -> int:
    checked = 0
    for path in TARGETS:
        if not path.exists():
            problems.append(f"缺失文件：{path}")
            continue
        text = path.read_text(encoding="utf-8")
        checked += 1
        if path.suffix == ".vue":
            check_vue_blocks(path, text)
        check_imports(path, text)

    print(f"已检查 {checked} 个文件")
    if problems:
        print(f"\n发现 {len(problems)} 个问题：")
        for p in problems:
            print("  -", p)
        return 1

    print("全部通过：块结构平衡、导入路径均可解析。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
