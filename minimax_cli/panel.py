"""The ``mmx`` dashboard panel.

When the user runs plain ``mmx`` with no sub-command, this module prints
a friendly summary that mirrors the screenshot in the docs:

* resources   – available capability resources
* flags       – common flags
* quota info  – current Token Plan balance
* help        – pointer to ``mmx --help``
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass

from .client import MiniMaxClient
from .config import Config
from .auth import AuthStore


RESOURCES: list[tuple[str, str, str]] = [
    ("语言", "text", "多轮对话 / 流式 / JSON 输出"),
    ("图像", "image", "文生图,支持宽高比与批量"),
    ("视频", "video", "异步生成,支持任务查询与下载"),
    ("语音", "speech", "文字转语音,多音色,流式"),
    ("音乐", "music", "文生音乐,歌词 / 纯音乐"),
    ("视觉", "vision", "图像理解,本地/URL/file_id"),
    ("搜索", "search", "内置网络检索"),
    ("音频", "audio", "Whisper 替代品,带时间戳转录"),
]


@dataclass
class PanelSection:
    title: str
    rows: list[tuple[str, str]]


def _hr(width: int) -> str:
    return "─" * width


def render_panel(client: MiniMaxClient | None = None, *, no_color: bool = False) -> str:
    cfg = Config.load()
    auth = AuthStore(cfg)
    state = auth.status()
    width = shutil.get_terminal_size((80, 24)).columns
    width = max(64, min(width, 96))

    out: list[str] = []
    out.append("╭" + _hr(width - 2) + "╮")
    title = f"  MiniMax CLI  v0.1.0  ·  {cfg.region.upper()}"
    out.append("│" + title.ljust(width - 2) + "│")
    out.append("│" + f"  Logged in: {state.short_key()}".ljust(width - 2) + "│")
    out.append("╰" + _hr(width - 2) + "╯")
    out.append("")

    # ---- resources ---------------------------------------------------------
    out.append("📦 resources")
    for label, slug, desc in RESOURCES:
        line = f"   • {label:<6}  mmx {slug:6s}  –  {desc}"
        out.append(line)
    out.append("")

    # ---- flags --------------------------------------------------------------
    out.append("🚩 flags")
    flags = [
        ("--model", "指定模型 id"),
        ("--stream/--no-stream", "流式开关"),
        ("--json", "text chat 输出 JSON 模式"),
        ("--out <file>", "speech / music / image 落盘路径"),
        ("--region cn|global", "切换服务区域"),
    ]
    for k, v in flags:
        out.append(f"   • {k:<22}  {v}")
    out.append("")

    # ---- quota --------------------------------------------------------------
    out.append("💳 quota")
    if client is not None and state.api_key:
        try:
            data = client.quota()
            total = data.get("total_granted") or data.get("total") or 0
            used = data.get("total_used") or data.get("used") or 0
            remain = max(0, (total or 0) - (used or 0))
            out.append(f"   total : {total}")
            out.append(f"   used  : {used}")
            out.append(f"   remain: {remain}")
        except Exception as exc:
            out.append(f"   (unavailable: {exc})")
    else:
        out.append("   run `mmx auth login --api-key <key>` to enable")
    out.append("")

    # ---- help ---------------------------------------------------------------
    out.append("🆘 help")
    out.append("   mmx <command> --help     单个命令的详细帮助")
    out.append("   mmx --help               全部命令一览")
    out.append("")

    return "\n".join(out)
