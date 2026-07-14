import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from .asr import SeedASRError, transcribe_wav
from .client import get_client, reset_client
from .config import Config, load_dotenv


def main(argv: Optional[List[str]] = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="ark", description="Volcengine Ark Token Plan CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    chat = sub.add_parser("chat", help="Chat completions (JSON mode by default)")
    chat.add_argument("--message", required=True)
    chat.add_argument("--model")
    chat.add_argument("--max-tokens", type=int)
    chat.add_argument("--temperature", type=float, default=0)

    asr_p = sub.add_parser("asr").add_subparsers(dest="action", required=True)
    tr = asr_p.add_parser("transcribe")
    tr.add_argument("--wav", required=True)
    tr.add_argument("--language")

    cfg_p = sub.add_parser("config").add_subparsers(dest="action", required=True)
    cfg_p.add_parser("show")

    args = parser.parse_args(argv)
    try:
        if args.command == "config":
            print(json.dumps(Config.load().redacted(), ensure_ascii=False, indent=2))
            return 0

        cfg = Config.load()
        if not cfg.api_key:
            raise ValueError("ARK_API_KEY is required")

        if args.command == "chat":
            client = get_client(cfg)
            text = client.chat(
                [{"role": "user", "content": args.message}],
                model=args.model or cfg.model,
                temperature=args.temperature,
                max_tokens=args.max_tokens if args.max_tokens is not None else cfg.max_tokens,
            )
            print(text)
            return 0

        if args.command == "asr" and args.action == "transcribe":
            result = transcribe_wav(Path(args.wav), language=args.language, api_key=cfg.api_key)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        return 1
    except (ValueError, SeedASRError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        reset_client()


if __name__ == "__main__":
    raise SystemExit(main())
