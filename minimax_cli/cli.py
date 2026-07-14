import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from .client import MiniMaxClient, MiniMaxError
from .config import Config
from .io_utils import timestamp_name


def _print_json(data) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2 if isinstance(data, (dict, list)) else None))


def _parse_messages(args) -> List[dict]:
    messages = []
    if getattr(args, "messages_file", None):
        messages = json.loads(Path(args.messages_file).read_text(encoding="utf-8"))
    if getattr(args, "message", None):
        for item in args.message:
            if ":" in item and item.split(":", 1)[0] in {"system", "user", "assistant"}:
                role, content = item.split(":", 1)
                messages.append({"role": role, "content": content})
            else:
                messages.append({"role": "user", "content": item})
    if not messages:
        raise ValueError("provide --message or --messages-file")
    return messages


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mmx", description="MiniMax China Token Plan CLI")
    p.add_argument("--output", choices=["text", "json"], default="text", help="Output format")
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("config").add_subparsers(dest="action", required=True)
    c.add_parser("show")
    s = c.add_parser("set")
    s.add_argument("--key", required=True)
    s.add_argument("--value", required=True)

    a = sub.add_parser("auth").add_subparsers(dest="action", required=True)
    login = a.add_parser("login")
    login.add_argument("--api-key", required=True)
    a.add_parser("status")
    a.add_parser("logout")
    a.add_parser("refresh")

    t = sub.add_parser("text").add_subparsers(dest="action", required=True)
    ch = t.add_parser("chat")
    ch.add_argument("--message", action="append")
    ch.add_argument("--messages-file")
    ch.add_argument("--model")
    ch.add_argument("--json", dest="json_mode", action="store_true")
    ch.add_argument("--stream", action="store_true")
    ch.add_argument("--max-tokens", type=int)

    image = sub.add_parser("image").add_subparsers(dest="action", required=True)
    ig = image.add_parser("generate")
    ig.add_argument("--prompt", required=True)
    ig.add_argument("--model")
    ig.add_argument("--n", type=int, default=1)
    ig.add_argument("--aspect-ratio")
    ig.add_argument("--width", type=int)
    ig.add_argument("--height", type=int)
    ig.add_argument("--seed", type=int)
    ig.add_argument("--out")
    ig.add_argument("--out-dir")
    ig.add_argument("--response-format", choices=["url", "base64"], default="url")

    speech = sub.add_parser("speech").add_subparsers(dest="action", required=True)
    syn = speech.add_parser("synthesize")
    syn.add_argument("--text")
    syn.add_argument("--text-file")
    syn.add_argument("--model")
    syn.add_argument("--voice", default="English_expressive_narrator")
    syn.add_argument("--speed", type=float)
    syn.add_argument("--volume", type=float)
    syn.add_argument("--pitch", type=float)
    syn.add_argument("--format", default="mp3")
    syn.add_argument("--sample-rate", type=int, default=32000)
    syn.add_argument("--bitrate", type=int, default=128000)
    syn.add_argument("--channels", type=int, default=1)
    syn.add_argument("--language")
    syn.add_argument("--subtitles", action="store_true")
    syn.add_argument("--out")
    syn.add_argument("--stream", action="store_true")
    voices = speech.add_parser("voices")
    voices.add_argument("--lang")

    video = sub.add_parser("video").add_subparsers(dest="action", required=True)
    vg = video.add_parser("generate")
    vg.add_argument("--prompt", required=True)
    vg.add_argument("--model")
    vg.add_argument("--first-frame")
    vg.add_argument("--last-frame")
    vg.add_argument("--subject-image")
    vg.add_argument("--callback-url")
    vg.add_argument("--async", dest="async_mode", action="store_true")
    vg.add_argument("--download")
    vg.add_argument("--poll-interval", type=float)
    vg.add_argument("--timeout", type=float)
    vt = video.add_parser("task")
    vt_sub = vt.add_subparsers(dest="task_action", required=True)
    vt_get = vt_sub.add_parser("get")
    vt_get.add_argument("--task-id", required=True)
    vd = video.add_parser("download")
    vd.add_argument("--file-id", required=True)
    vd.add_argument("--out", required=True)

    music = sub.add_parser("music").add_subparsers(dest="action", required=True)
    mg = music.add_parser("generate")
    mg.add_argument("--prompt")
    mg.add_argument("--lyrics")
    mg.add_argument("--lyrics-optimizer", action="store_true")
    mg.add_argument("--instrumental", action="store_true")
    mg.add_argument("--model")
    mg.add_argument("--out")
    mg.add_argument("--format", default="mp3")
    mg.add_argument("--sample-rate", type=int, default=44100)
    mg.add_argument("--bitrate", type=int, default=256000)
    mg.add_argument("--channel", type=int)
    mg.add_argument("--seed", type=int)
    mg.add_argument("--stream", action="store_true")
    mg.add_argument("--vocals")
    mg.add_argument("--genre")
    mg.add_argument("--mood")
    mg.add_argument("--instruments")
    mc = music.add_parser("cover")
    mc.add_argument("--prompt", required=True)
    mc.add_argument("--audio")
    mc.add_argument("--audio-file")
    mc.add_argument("--lyrics")
    mc.add_argument("--model", default="music-cover")
    mc.add_argument("--out")
    mc.add_argument("--format", default="mp3")
    mc.add_argument("--sample-rate", type=int, default=44100)
    mc.add_argument("--bitrate", type=int, default=256000)
    mc.add_argument("--channel", type=int)
    mc.add_argument("--seed", type=int)
    mc.add_argument("--stream", action="store_true")

    vision = sub.add_parser("vision").add_subparsers(dest="action", required=True)
    vdsc = vision.add_parser("describe")
    vdsc.add_argument("--image")
    vdsc.add_argument("--file-id")
    vdsc.add_argument("--prompt")
    vdsc.add_argument("--model")

    search = sub.add_parser("search").add_subparsers(dest="action", required=True)
    sq = search.add_parser("query")
    sq.add_argument("query")

    sub.add_parser("quota")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    # Support shorthand: mmx image "prompt"
    raw = list(argv) if argv is not None else sys.argv[1:]
    if len(raw) >= 2 and raw[0] == "image" and raw[1] not in {"generate", "-h", "--help"} and not raw[1].startswith("-"):
        raw = ["image", "generate", "--prompt", raw[1], *raw[2:]]

    parser = _build_parser()
    args = parser.parse_args(raw)
    output_json = args.output == "json"

    try:
        cfg = Config.load()
        if args.command == "config":
            if args.action == "show":
                _print_json(cfg.redacted())
            else:
                cfg.set_value(args.key, args.value)
                cfg.save()
                print(f"set {args.key}")
            return 0

        if args.command == "auth":
            if args.action == "login":
                cfg.api_key = args.api_key
                cfg.save()
                print("API key saved")
            elif args.action == "logout":
                cfg.api_key = None
                cfg.save()
                print("API key removed")
            elif args.action == "refresh":
                print(
                    "OAuth Device Code refresh is not implemented yet. "
                    "Use API key auth: mmx auth login --api-key <key>",
                    file=sys.stderr,
                )
                return 1
            else:
                print(
                    json.dumps(
                        {
                            "authenticated": bool(cfg.api_key),
                            "region": cfg.region,
                            "base_url": cfg.base_url,
                            "auth_mode": "api_key" if cfg.api_key else None,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            return 0

        if not cfg.api_key:
            raise MiniMaxError("API key is required; set MINIMAX_API_KEY or run mmx auth login")

        with MiniMaxClient(cfg) as client:
            if args.command == "text":
                messages = _parse_messages(args)
                on_delta = (lambda d: print(d, end="", flush=True)) if args.stream and not output_json else None
                result = client.text_chat(
                    messages,
                    model=args.model,
                    json_mode=args.json_mode,
                    stream=args.stream,
                    max_tokens=args.max_tokens,
                    on_delta=on_delta,
                )
                if args.stream and not output_json:
                    print()
                elif output_json:
                    _print_json({"text": result.text, "model": result.model, "usage": result.usage})
                else:
                    print(result.text)

            elif args.command == "image":
                out_dir = args.out_dir or cfg.output_dir
                result = client.image_generate(
                    args.prompt,
                    model=args.model,
                    n=args.n,
                    aspect_ratio=args.aspect_ratio,
                    width=args.width,
                    height=args.height,
                    seed=args.seed,
                    response_format=args.response_format,
                    out=args.out,
                    out_dir=out_dir,
                )
                payload = {"paths": result.paths, "raw": result.raw}
                _print_json(payload) if output_json else print("\n".join(result.paths or []))

            elif args.command == "speech":
                if args.action == "voices":
                    voices = client.speech_voices(args.lang)
                    _print_json(voices)
                else:
                    text = args.text
                    if args.text_file:
                        text = Path(args.text_file).read_text(encoding="utf-8") if args.text_file != "-" else sys.stdin.read()
                    if not text:
                        raise ValueError("--text or --text-file is required")
                    out = args.out or str(Path(cfg.output_dir) / timestamp_name("speech", args.format))
                    if args.stream and not args.out:
                        def _write(chunk: bytes) -> None:
                            sys.stdout.buffer.write(chunk)
                            sys.stdout.buffer.flush()

                        result = client.speech_synthesize(
                            text,
                            model=args.model,
                            voice_id=args.voice,
                            speed=args.speed,
                            volume=args.volume,
                            pitch=args.pitch,
                            audio_format=args.format,
                            sample_rate=args.sample_rate,
                            bitrate=args.bitrate,
                            channel=args.channels,
                            language_boost=args.language,
                            subtitle_enable=args.subtitles,
                            stream=True,
                            on_chunk=_write,
                        )
                        return 0
                    result = client.speech_synthesize(
                        text,
                        model=args.model,
                        voice_id=args.voice,
                        speed=args.speed,
                        volume=args.volume,
                        pitch=args.pitch,
                        audio_format=args.format,
                        sample_rate=args.sample_rate,
                        bitrate=args.bitrate,
                        channel=args.channels,
                        language_boost=args.language,
                        subtitle_enable=args.subtitles,
                        stream=args.stream,
                        out=out,
                    )
                    if output_json:
                        _print_json({"path": result.path, "size": result.size})
                    else:
                        print(result.path)

            elif args.command == "video":
                if args.action == "generate":
                    subject = None
                    if args.subject_image:
                        subject = [{"type": "character", "image": [client._image_to_data_uri(args.subject_image)]}]
                    result = client.video_generate(
                        args.prompt,
                        model=args.model,
                        first_frame_image=args.first_frame,
                        last_frame_image=args.last_frame,
                        subject_reference=subject,
                        callback_url=args.callback_url,
                        async_mode=args.async_mode,
                        poll_interval=args.poll_interval,
                        timeout=args.timeout,
                        download=args.download,
                    )
                    payload = {
                        "task_id": result.task_id,
                        "path": result.path,
                        "download_url": result.download_url,
                        "raw": result.raw,
                    }
                    _print_json(payload) if output_json else print(result.path or result.task_id)
                elif args.action == "task":
                    task = client.video_get_task(args.task_id)
                    _print_json(task)
                else:
                    result = client.video_download(args.file_id, args.out)
                    if output_json:
                        _print_json({"path": result.path, "size": result.size, "download_url": result.download_url})
                    else:
                        print(result.path)

            elif args.command == "music":
                if args.action == "generate":
                    out = args.out or str(Path(cfg.output_dir) / timestamp_name("music", args.format))
                    if args.stream and not args.out:
                        def _write(chunk: bytes) -> None:
                            sys.stdout.buffer.write(chunk)
                            sys.stdout.buffer.flush()

                        client.music_generate(
                            prompt=args.prompt,
                            lyrics=args.lyrics,
                            model=args.model,
                            lyrics_optimizer=args.lyrics_optimizer,
                            instrumental=args.instrumental,
                            stream=True,
                            audio_format=args.format,
                            sample_rate=args.sample_rate,
                            bitrate=args.bitrate,
                            channel=args.channel,
                            seed=args.seed,
                            on_chunk=_write,
                            vocals=args.vocals,
                            genre=args.genre,
                            mood=args.mood,
                            instruments=args.instruments,
                        )
                        return 0
                    result = client.music_generate(
                        prompt=args.prompt,
                        lyrics=args.lyrics,
                        model=args.model,
                        lyrics_optimizer=args.lyrics_optimizer,
                        instrumental=args.instrumental,
                        stream=args.stream,
                        out=out,
                        audio_format=args.format,
                        sample_rate=args.sample_rate,
                        bitrate=args.bitrate,
                        channel=args.channel,
                        seed=args.seed,
                        vocals=args.vocals,
                        genre=args.genre,
                        mood=args.mood,
                        instruments=args.instruments,
                    )
                    if output_json:
                        _print_json({"path": result.path, "size": result.size})
                    else:
                        print(result.path)
                else:
                    out = args.out or str(Path(cfg.output_dir) / timestamp_name("cover", args.format))
                    result = client.music_cover(
                        args.prompt,
                        audio_url=args.audio,
                        audio_file=args.audio_file,
                        lyrics=args.lyrics,
                        model=args.model,
                        out=out,
                        audio_format=args.format,
                        sample_rate=args.sample_rate,
                        bitrate=args.bitrate,
                        channel=args.channel,
                        seed=args.seed,
                        stream=args.stream,
                    )
                    if output_json:
                        _print_json({"path": result.path, "size": result.size})
                    else:
                        print(result.path)

            elif args.command == "vision":
                result = client.vision_describe(
                    image=args.image,
                    file_id=args.file_id,
                    prompt=args.prompt,
                    model=args.model,
                )
                if output_json:
                    _print_json({"content": result.text, "raw": result.raw})
                else:
                    print(result.text or "")

            elif args.command == "search":
                _print_json(client.search_query(args.query))

            else:
                _print_json(client.quota())
        return 0
    except (MiniMaxError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
