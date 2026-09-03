"""门户适配器注册表：URL → 适配器。"""
from __future__ import annotations

from .base import PortalAdapter
from .bytedance import BytedanceAdapter
from .shixiseng import ShixisengAdapter
from .tencent import TencentAdapter
from .nowcoder import NowcoderAdapter
from .boss import BossAdapter
from .xiaohongshu import XiaohongshuAdapter
from .bilibili import BilibiliAdapter
from .zhaopin import ZhaopinAdapter
from .hotjob import HotjobAdapter
from .generic import GenericFormAdapter

ADAPTERS: list[type[PortalAdapter]] = [
    BytedanceAdapter,
    ShixisengAdapter,
    TencentAdapter,
    NowcoderAdapter,
    BossAdapter,
    XiaohongshuAdapter,
    BilibiliAdapter,
    ZhaopinAdapter,
    HotjobAdapter,
    GenericFormAdapter,
]

_BY_NAME = {a.name: a for a in ADAPTERS}


def adapter_for_url(url: str) -> PortalAdapter | None:
    for a in ADAPTERS:
        inst = a()
        if any(p in url for p in inst.url_patterns):
            return inst
    return None


def adapter_for_name(name: str) -> PortalAdapter | None:
    cls = _BY_NAME.get(name)
    return cls() if cls else None


def portal_names() -> list[str]:
    return list(_BY_NAME.keys())
