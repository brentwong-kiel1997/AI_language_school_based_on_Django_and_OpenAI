import argparse, json, sys
from pathlib import Path
from .client import MiniMaxClient, MiniMaxError
from .config import Config

def main(argv=None):
    p=argparse.ArgumentParser(prog="mmx"); sub=p.add_subparsers(dest="command",required=True)
    c=sub.add_parser("config").add_subparsers(dest="action",required=True); c.add_parser("show"); s=c.add_parser("set"); s.add_argument("--key",required=True); s.add_argument("--value",required=True)
    a=sub.add_parser("auth").add_subparsers(dest="action",required=True); l=a.add_parser("login"); l.add_argument("--api-key",required=True); a.add_parser("status"); a.add_parser("logout")
    t=sub.add_parser("text").add_subparsers(dest="action",required=True); ch=t.add_parser("chat"); ch.add_argument("--message"); ch.add_argument("--messages-file"); ch.add_argument("--model"); ch.add_argument("--json",dest="json_mode",action="store_true"); ch.add_argument("--stream",action="store_true"); ch.add_argument("--max-tokens",type=int)
    q=sub.add_parser("search").add_subparsers(dest="action",required=True); qq=q.add_parser("query"); qq.add_argument("query"); sub.add_parser("quota")
    args=p.parse_args(argv)
    try:
        cfg=Config.load()
        if args.command=="config":
            if args.action=="show": print(json.dumps({**cfg.__dict__,"api_key":"***" if cfg.api_key else None},ensure_ascii=False,indent=2))
            else:
                if not hasattr(cfg,args.key): raise ValueError("unknown config key")
                setattr(cfg,args.key,args.value); cfg.save()
            return 0
        if args.command=="auth":
            if args.action=="login": cfg.api_key=args.api_key; cfg.save(); print("API key saved")
            elif args.action=="logout": cfg.api_key=None; cfg.save(); print("API key removed")
            else: print("authenticated" if cfg.api_key else "not authenticated")
            return 0
        if not cfg.api_key: raise MiniMaxError("API key is required; set MINIMAX_API_KEY or run mmx auth login")
        with MiniMaxClient(cfg) as client:
            if args.command=="text":
                messages=json.loads(Path(args.messages_file).read_text()) if args.messages_file else [{"role":"user","content":args.message}] if args.message else (_ for _ in ()).throw(ValueError("provide --message or --messages-file"))
                r=client.text_chat(messages,model=args.model,json_mode=args.json_mode,stream=args.stream,max_tokens=args.max_tokens,on_delta=(lambda d: print(d,end="",flush=True)) if args.stream else None); print() if args.stream else print(r.text)
            elif args.command=="search": print(json.dumps(client.search_query(args.query),ensure_ascii=False))
            else: print(json.dumps(client.quota(),ensure_ascii=False))
        return 0
    except (MiniMaxError,ValueError,OSError,json.JSONDecodeError) as exc: print(f"Error: {exc}",file=sys.stderr); return 1
