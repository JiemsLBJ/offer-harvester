"""CV 模板身份哨兵测试：\\name{} 行必须全部是占位符。

用法：
  python tests/test_cv_identity_guard.py     # 直跑
  pytest tests/test_cv_identity_guard.py     # pytest 环境

上游教训（ai-job-search）：占位哨兵曾放在模板头注释里，个性化改写永远不会碰
头注释，于是带真名的简历照样通过检查。修复是把哨兵挪进 \\name{} 数据行。
本仓库采用同等防线：cv/ 与 cover_letters/ 下所有 .tex 的 \\name{} 命令，
每个非空花括号参数必须是完整的方括号占位符（如 [姓]、[名]、[姓名]），
任何裸值（真实姓名、拼音、任意文本）都会让测试失败。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TARGETS = sorted(REPO.glob("cv/*.tex")) + sorted(REPO.glob("cover_letters/*.tex"))

# \name{...}{...} 或 \name{...}；参数内容不含花括号
NAME_RE = re.compile(r"\\name\{([^{}]*)\}(?:\{([^{}]*)\})?")
PLACEHOLDER_RE = re.compile(r"^\[[^\[\]]+\]$")


def check_file(path: Path) -> list[str]:
    problems: list[str] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        for match in NAME_RE.finditer(line):
            for arg in match.groups():
                if arg is None:
                    continue
                stripped = arg.strip()
                if stripped == "":
                    continue  # 空参数（如 \name{[姓名]}{}）合法
                if not PLACEHOLDER_RE.match(stripped):
                    problems.append(
                        f"{path.relative_to(REPO)}:{lineno} \\name 参数不是占位符: {arg!r}"
                    )
    return problems


def main() -> int:
    if not TARGETS:
        print("FAIL 未找到任何 .tex 模板")
        return 1
    problems: list[str] = []
    for path in TARGETS:
        problems += check_file(path)
    if problems:
        for p in problems:
            print(f"FAIL {p}")
        print(f"\n=== 0 passed, {len(problems)} failed ===")
        return 1
    print(f"PASS {len(TARGETS)} 个模板的 \\name 行均为占位符")
    return 0


if __name__ == "__main__":
    sys.exit(main())
