"""确认关卡：提交前向用户展示「将提交什么、发给谁、包含哪些信息」。"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any


class ConfirmDenied(RuntimeError):
    pass


@dataclass
class ConfirmContext:
    portal: str
    job_title: str
    company: str
    url: str
    resume: str | None = None
    fields: list[str] = field(default_factory=list)  # 将被填写的字段清单（含敏感字段）
    notes: list[str] = field(default_factory=list)   # 例如：无法自动填写、需要人工补充项
    raw_input: Any = None  # 测试注入


def render(ctx: ConfirmContext) -> str:
    lines = [
        "",
        "=" * 64,
        "【提交前确认】",
        f"  平台:      {ctx.portal}",
        f"  岗位:      {ctx.job_title}",
        f"  公司:      {ctx.company}",
        f"  链接:      {ctx.url}",
    ]
    if ctx.resume:
        lines.append(f"  简历附件:  {ctx.resume}")
    if ctx.fields:
        lines.append("  将填写:    " + " | ".join(ctx.fields))
    for n in ctx.notes:
        lines.append(f"  ⚠ {n}")
    lines.extend(
        [
            "=" * 64,
            "输入 y 确认并提交；输入其他任何内容取消本次投递。",
            "（需要取消后留在页面检查时，请在命令中加 --review）",
        ]
    )
    return "\n".join(lines)


def confirm(ctx: ConfirmContext) -> bool:
    """返回 True 表示用户确认提交；False/中断表示取消。"""
    if ctx.raw_input is not None:
        ans = ctx.raw_input
    else:
        print(render(ctx))
        ans = input("> ").strip()
    return ans.lower() in {"y", "yes", "确认", "是", "ok"}
