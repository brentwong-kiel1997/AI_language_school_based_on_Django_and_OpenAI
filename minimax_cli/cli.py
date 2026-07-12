"""``mmx`` command-line entry point.

This module wires up every sub-command listed in the upstream mmx-cli
documentation. It is intentionally self-contained: ``python -m minimax_cli``
or the ``mmx`` console script both dispatch into :func:`main` below.

The design mirrors the upstream CLI:

* ``mmx``                              → dashboard panel
* ``mmx auth login|status|refresh|logout``
* ``mmx config show|set``
* ``mmx text chat ...``
* ``mmx image generate ...``
* ``mmx video generate ...`` / ``mmx video status <task>`` / ``mmx video download <task>``
* ``mmx speech synthesize ...``
* ``mmx music generate ...``
* ``mmx vision describe ...``
* ``mmx search query ...``
* ``mmx audio transcribe ...``         – extra command, replaces Whisper
* ``mmx quota``
* ``mmx update [latest]``
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from . import __version__
from .auth import AuthStore
from .client import (
    ChatMessage,
    MiniMaxClient,
)
from .config import Config
from .exceptions import (
    AuthenticationError,
    MiniMaxError,
    QuotaExceededError,
    ValidationError,
)
from .panel import render_panel
from .quota import render_quota
from .regions import Region
from .update import check_latest, current_version


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _err(msg: str) -> None:
    print(f"mmx: {msg}", file=sys.stderr)


def _build_client(args: argparse.Namespace) -> MiniMaxClient:
    cfg = Config.load()
    if hasattr(args, "region") and args.region:
        cfg.region = args.region
    if hasattr(args, "api_key") and args.api_key:
        cfg.api_key = args.api_key
    try:
        return MiniMaxClient(config=cfg)
    except AuthenticationError as exc:
        _err(str(exc))
        sys.exit(2)


def _add_common_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--region",
        choices=[r.value for r in Region],
        help="覆盖 region (cn / global)",
    )
    p.add_argument(
        "--api-key",
        help="覆盖 API key (一般用 `mmx auth login` 设置)",
    )


# ---------------------------------------------------------------------------
# Command implementations
# ---------------------------------------------------------------------------


def cmd_models_list(args: argparse.Namespace) -> int:
    client = _build_client(args)
    try:
        data = client._http.get("/v1/models", timeout=15).json()
    except Exception as exc:
        _err(f"无法查询模型列表: {exc}")
        return 1
    models = data.get("data") or []
    if not models:
        print("(平台未返回任何模型)")
        return 0
    # Highlight the latest one (by created timestamp).
    sorted_models = sorted(models, key=lambda m: m.get("created", 0), reverse=True)
    latest_id = sorted_models[0]["id"]
    print(f"共 {len(models)} 个模型,最新: \033[1m{latest_id}\033[0m")
    print()
    print(f"  {'MODEL ID':<35}  {'CREATED':<20}  OWNER")
    print("  " + "-" * 70)
    for m in sorted_models:
        from datetime import datetime
        ts = ""
        if m.get("created"):
            ts = datetime.fromtimestamp(m["created"]).strftime("%Y-%m-%d %H:%M")
        marker = "  ★" if m["id"] == latest_id else "   "
        print(f"{marker} {m['id']:<35}  {ts:<20}  {m.get('owned_by','')}")
    return 0


def cmd_models_info(args: argparse.Namespace) -> int:
    client = _build_client(args)
    try:
        data = client._http.get("/v1/models", timeout=15).json()
    except Exception as exc:
        _err(f"无法查询: {exc}")
        return 1
    for m in data.get("data") or []:
        if m["id"] == args.model_id:
            from datetime import datetime
            ts = ""
            if m.get("created"):
                ts = datetime.fromtimestamp(m["created"]).strftime("%Y-%m-%d %H:%M:%S")
            print(json.dumps({
                "id": m["id"],
                "object": m.get("object"),
                "owned_by": m.get("owned_by"),
                "created": ts,
            }, indent=2, ensure_ascii=False))
            return 0
    _err(f"找不到模型: {args.model_id}")
    return 1


def cmd_auth(args: argparse.Namespace) -> int:
    store = AuthStore()
    if args.action == "login":
        if not args.api_key:
            _err("--api-key is required for `mmx auth login`")
            return 2
        state = store.login(args.api_key, region=args.region)
        print(f"✔ 登录成功  region={state.region}  key={state.short_key()}")
        return 0
    if args.action == "status":
        state = store.status()
        print(f"region : {state.region}")
        print(f"key    : {state.short_key()}")
        print(f"登录时间: {state.logged_in_at or '(not logged in)'}")
        print(f"刷新时间: {state.last_refresh or '-'}")
        return 0
    if args.action == "refresh":
        state = store.refresh()
        print(f"✔ 已刷新  region={state.region}  key={state.short_key()}")
        return 0
    if args.action == "logout":
        store.logout()
        print("✔ 已登出")
        return 0
    _err(f"unknown auth action: {args.action}")
    return 2


def cmd_config(args: argparse.Namespace) -> int:
    cfg = Config.load()
    if args.action == "show":
        data = cfg.to_dict()
        data["api_key"] = AuthStore(cfg).status().short_key()
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0
    if args.action == "set":
        if not args.key or args.value is None:
            _err("需要 --key 和 --value")
            return 2
        try:
            cfg.set(args.key, args.value)
            cfg.save()
        except ValidationError as exc:
            _err(str(exc))
            return 2
        print(f"✔ {args.key} = {args.value}")
        return 0
    _err(f"unknown config action: {args.action}")
    return 2


def cmd_text_chat(args: argparse.Namespace) -> int:
    messages: list[ChatMessage] = []
    if args.system:
        messages.append(ChatMessage.system(args.system))
    if args.message:
        messages.append(ChatMessage.user(args.message))
    if args.messages_file:
        data = json.loads(Path(args.messages_file).read_text(encoding="utf-8"))
        for m in data:
            messages.append(ChatMessage(m["role"], m["content"]))
    if not messages:
        _err("至少要传一个 --message 或 --system,或 --messages-file")
        return 2

    client = _build_client(args)
    if args.stream:
        def on_delta(token: str) -> None:
            sys.stdout.write(token)
            sys.stdout.flush()
        resp = client.text_chat(
            messages,
            model=args.model,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            json_mode=args.json,
            stream=True,
            on_delta=on_delta,
        )
        sys.stdout.write("\n")
    else:
        resp = client.text_chat(
            messages,
            model=args.model,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            json_mode=args.json,
        )
        if args.json:
            print(resp.to_json())
        else:
            print(resp.text)
    return 0


def cmd_image_generate(args: argparse.Namespace) -> int:
    client = _build_client(args)
    out_dir = Path(args.out_dir) if args.out_dir else client.config.ensure_output_dir()
    results = client.image_generate(
        args.prompt,
        model=args.model,
        n=args.n,
        aspect_ratio=args.aspect_ratio,
        out_dir=out_dir,
    )
    for r in results:
        print(r.url or r.file_id)
    return 0


def cmd_video_generate(args: argparse.Namespace) -> int:
    client = _build_client(args)
    out_dir = Path(args.out_dir) if args.out_dir else None
    task = client.video_generate(
        args.prompt,
        model=args.model,
        out_dir=out_dir,
        wait=not args.no_wait,
    )
    print(json.dumps({"task_id": task.task_id, "status": task.status, "url": task.url}, ensure_ascii=False))
    return 0


def cmd_video_status(args: argparse.Namespace) -> int:
    client = _build_client(args)
    task = client.video_query(args.task_id)
    print(json.dumps({"task_id": task.task_id, "status": task.status, "url": task.url}, ensure_ascii=False))
    return 0


def cmd_video_download(args: argparse.Namespace) -> int:
    client = _build_client(args)
    task = client.video_query(args.task_id)
    if task.status != "succeeded" or not task.url:
        print(f"task {task.task_id} is {task.status}; nothing to download", file=sys.stderr)
        return 1
    out_dir = Path(args.out_dir) if args.out_dir else client.config.ensure_output_dir()
    saved = client._download_to_dir([task.url], out_dir)
    for p in saved:
        print(str(p))
    return 0


def cmd_speech_synthesize(args: argparse.Namespace) -> int:
    client = _build_client(args)
    out = Path(args.out) if args.out else None
    audio = client.speech_synthesize(
        args.text,
        voice=args.voice,
        model=args.model,
        out=out,
        stream=args.stream,
        audio_format=args.format,
        sample_rate=args.sample_rate,
        speed=args.speed,
    )
    if out is None:
        sys.stdout.buffer.write(audio)
    else:
        print(str(out))
    return 0


def cmd_music_generate(args: argparse.Namespace) -> int:
    client = _build_client(args)
    out = client.music_generate(
        args.prompt,
        lyrics=args.lyrics,
        model=args.model,
        out=args.out,
    )
    print(str(out))
    return 0


def cmd_vision_describe(args: argparse.Namespace) -> int:
    client = _build_client(args)
    source = args.file_id or args.image or args.url
    if source is None:
        _err("需要 --image <local path> / --url <https://> / --file-id <id>")
        return 2
    resp = client.vision_describe(source, prompt=args.prompt, model=args.model)
    print(resp.text)
    return 0


def cmd_search_query(args: argparse.Namespace) -> int:
    client = _build_client(args)
    results = client.search_query(args.query, top_k=args.top_k)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


def cmd_audio_transcribe(args: argparse.Namespace) -> int:
    """Drop-in replacement for OpenAI's Whisper transcriptions endpoint."""
    client = _build_client(args)
    result = client.audio_transcribe(
        args.file,
        model=args.model,
        language=args.language,
        response_format=args.format,
    )
    if args.format == "text":
        print(result.text)
    else:
        payload = {
            "language": result.language,
            "duration": result.duration,
            "text": result.text,
            "segments": [s.__dict__ for s in result.segments],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_quota(args: argparse.Namespace) -> int:
    client = _build_client(args)
    print(render_quota(client))
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    if args.latest:
        print("升级方式: pip install -U minimax-cli")
        return 0
    print(f"当前版本: {current_version()}")
    print(check_latest())
    return 0


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mmx",
        description="minimax_cli – MiniMax 多模态 CLI 的纯 Python 实现",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=False)

    # ---- models ----
    mdl = sub.add_parser("models", help="查看 / 查询可用模型")
    mdl_sub = mdl.add_subparsers(dest="action", required=True)
    m_list = mdl_sub.add_parser("list", help="列出平台所有可用模型")
    m_list.set_defaults(func=cmd_models_list)
    m_info = mdl_sub.add_parser("info", help="查看单个模型详情")
    m_info.add_argument("model_id")
    m_info.set_defaults(func=cmd_models_info)
    _add_common_flags(mdl)

    # ---- auth ----
    auth = sub.add_parser("auth", help="登录 / 状态 / 刷新 / 登出")
    auth_sub = auth.add_subparsers(dest="action", required=True)
    a_login = auth_sub.add_parser("login", help="登录并保存 API key")
    a_login.add_argument("--api-key", required=True)
    a_login.add_argument("--region", choices=[r.value for r in Region])
    a_login.set_defaults(func=cmd_auth)
    a_status = auth_sub.add_parser("status", help="查看当前登录状态")
    a_status.set_defaults(func=cmd_auth)
    a_refresh = auth_sub.add_parser("refresh", help="刷新 region 检测")
    a_refresh.set_defaults(func=cmd_auth)
    a_logout = auth_sub.add_parser("logout", help="登出并清除本地凭据")
    a_logout.set_defaults(func=cmd_auth)
    _add_common_flags(auth)

    # ---- config ----
    cfg_p = sub.add_parser("config", help="查看 / 修改本地配置")
    cfg_sub = cfg_p.add_subparsers(dest="action", required=True)
    c_show = cfg_sub.add_parser("show", help="打印当前配置")
    c_show.set_defaults(func=cmd_config)
    c_set = cfg_sub.add_parser("set", help="设置单个 key=value")
    c_set.add_argument("--key", required=True)
    c_set.add_argument("--value", required=True)
    c_set.set_defaults(func=cmd_config)
    _add_common_flags(cfg_p)

    # ---- text ----
    text = sub.add_parser("text", help="语言对话")
    text_sub = text.add_subparsers(dest="action", required=True)
    t_chat = text_sub.add_parser("chat", help="单轮 / 多轮 chat completion")
    t_chat.add_argument("--message", "-m", help="用户消息")
    t_chat.add_argument("--system", "-s", help="系统提示词")
    t_chat.add_argument("--messages-file", help="包含 [{role,content},...] 的 JSON 文件")
    t_chat.add_argument("--model", default="MiniMax-M3")
    t_chat.add_argument("--temperature", type=float, default=0.0)
    t_chat.add_argument("--max-tokens", type=int)
    t_chat.add_argument("--json", action="store_true", help="强制 JSON 输出")
    t_chat.add_argument(
        "--stream", dest="stream", action="store_true", default=True,
        help="流式输出 (默认)"
    )
    t_chat.add_argument(
        "--no-stream", dest="stream", action="store_false",
        help="关闭流式",
    )
    t_chat.set_defaults(func=cmd_text_chat)
    _add_common_flags(text)

    # ---- image ----
    img = sub.add_parser("image", help="图像生成")
    img_sub = img.add_subparsers(dest="action", required=True)
    i_gen = img_sub.add_parser("generate", help="文生图")
    i_gen.add_argument("prompt", help="图像 prompt")
    i_gen.add_argument("--model", default="MiniMax-Image-01")
    i_gen.add_argument("--n", type=int, default=1)
    i_gen.add_argument("--aspect-ratio", default="1:1")
    i_gen.add_argument("--out-dir", help="下载生成图片到此目录")
    i_gen.set_defaults(func=cmd_image_generate)
    _add_common_flags(img)

    # ---- video ----
    vid = sub.add_parser("video", help="视频生成 (异步)")
    vid_sub = vid.add_subparsers(dest="action", required=True)
    v_gen = vid_sub.add_parser("generate", help="创建视频任务")
    v_gen.add_argument("prompt", help="视频 prompt")
    v_gen.add_argument("--model", default="MiniMax-Hailuo-2.3")
    v_gen.add_argument("--out-dir")
    v_gen.add_argument("--no-wait", action="store_true", help="不阻塞等待完成")
    v_gen.set_defaults(func=cmd_video_generate)
    v_st = vid_sub.add_parser("status", help="查询任务状态")
    v_st.add_argument("task_id")
    v_st.set_defaults(func=cmd_video_status)
    v_dl = vid_sub.add_parser("download", help="下载已完成视频")
    v_dl.add_argument("task_id")
    v_dl.add_argument("--out-dir")
    v_dl.set_defaults(func=cmd_video_download)
    _add_common_flags(vid)

    # ---- speech ----
    sp = sub.add_parser("speech", help="文字转语音 (TTS)")
    sp_sub = sp.add_subparsers(dest="action", required=True)
    s_say = sp_sub.add_parser("synthesize", help="合成语音")
    s_say.add_argument("--text", required=True)
    s_say.add_argument("--voice", default="female-shaonv")
    s_say.add_argument("--model", default="MiniMax-Speech-2.8")
    s_say.add_argument("--out", "-o", help="输出文件 (默认 stdout)")
    s_say.add_argument("--format", default="mp3")
    s_say.add_argument("--sample-rate", type=int, default=32000)
    s_say.add_argument("--speed", type=float, default=1.0)
    s_say.add_argument("--stream", action="store_true")
    s_say.set_defaults(func=cmd_speech_synthesize)
    _add_common_flags(sp)

    # ---- music ----
    mu = sub.add_parser("music", help="文生音乐")
    mu_sub = mu.add_subparsers(dest="action", required=True)
    m_gen = mu_sub.add_parser("generate", help="生成音乐")
    m_gen.add_argument("prompt", help="风格 / 主题描述")
    m_gen.add_argument("--lyrics", help="歌词 (留空 = 纯音乐)")
    m_gen.add_argument("--model", default="MiniMax-Music-2.6")
    m_gen.add_argument("--out", "-o", help="输出文件")
    m_gen.set_defaults(func=cmd_music_generate)
    _add_common_flags(mu)

    # ---- vision ----
    vi = sub.add_parser("vision", help="视觉理解")
    vi_sub = vi.add_subparsers(dest="action", required=True)
    v_des = vi_sub.add_parser("describe", help="描述一张图片")
    v_des.add_argument("--image", help="本地图片路径")
    v_des.add_argument("--url", help="图片 URL")
    v_des.add_argument("--file-id", help="平台 file_id")
    v_des.add_argument("--prompt", default="Describe this image in detail.")
    v_des.add_argument("--model", default="MiniMax-Vision-01")
    v_des.set_defaults(func=cmd_vision_describe)
    _add_common_flags(vi)

    # ---- search ----
    sr = sub.add_parser("search", help="网络搜索")
    sr_sub = sr.add_subparsers(dest="action", required=True)
    s_q = sr_sub.add_parser("query", help="发起一次搜索")
    s_q.add_argument("query")
    s_q.add_argument("--top-k", type=int, default=5)
    s_q.set_defaults(func=cmd_search_query)
    _add_common_flags(sr)

    # ---- audio (extra: replaces Whisper) ----
    au = sub.add_parser("audio", help="音频转录 (Whisper 替代)")
    au_sub = au.add_subparsers(dest="action", required=True)
    a_tr = au_sub.add_parser("transcribe", help="把音频文件转成文字")
    a_tr.add_argument("file", help="本地音频文件路径")
    a_tr.add_argument("--model", default="MiniMax-ASR-01")
    a_tr.add_argument("--language", help="指定音频语言,留空自动检测")
    a_tr.add_argument("--format", default="verbose_json",
                      choices=["text", "verbose_json", "json"])
    a_tr.set_defaults(func=cmd_audio_transcribe)
    _add_common_flags(au)

    # ---- quota ----
    qu = sub.add_parser("quota", help="查看 Token Plan 余额")
    qu.set_defaults(func=cmd_quota)
    _add_common_flags(qu)

    # ---- update ----
    up = sub.add_parser("update", help="检查 / 升级")
    up.add_argument("latest", nargs="?", help="传 'latest' 直接打印升级方式")
    up.set_defaults(func=cmd_update)
    _add_common_flags(up)

    return p


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    # Bare `mmx` (no args) → show panel.
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        try:
            client = MiniMaxClient()
            print(render_panel(client))
        except AuthenticationError:
            print(render_panel(None))
        return 0
    args = parser.parse_args(list(argv))
    if not hasattr(args, "func"):
        parser.print_help()
        return 1
    try:
        return int(args.func(args) or 0)
    except AuthenticationError as exc:
        _err(str(exc))
        return 2
    except QuotaExceededError as exc:
        _err(str(exc))
        return 3
    except ValidationError as exc:
        _err(str(exc))
        return 2
    except MiniMaxError as exc:
        _err(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
