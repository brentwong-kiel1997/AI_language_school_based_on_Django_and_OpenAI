import json
import os
import tempfile
import unittest
from unittest.mock import patch
import httpx
from minimax_cli import Config, MiniMaxClient, AuthenticationError, QuotaExceededError

class MiniMaxTests(unittest.TestCase):
    def test_default_config(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {"MINIMAX_CONFIG_DIR":d}, clear=False):
            cfg = Config.load()
        self.assertEqual(cfg.text_model, "MiniMax-M3")
        self.assertEqual(cfg.context_window_tokens, 1_000_000)
        self.assertEqual(cfg.max_tokens, 131072)

    def test_env_precedes_file(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {"MINIMAX_CONFIG_DIR":d,"MINIMAX_API_KEY":"env-key","MINIMAX_BASE_URL":"https://env.example"}, clear=False):
            Config(api_key="file-key", base_url="https://file.example").save(); cfg=Config.load()
            self.assertEqual(cfg.api_key,"env-key"); self.assertEqual(cfg.base_url,"https://env.example")
    def test_chat_body_headers_and_json_mode(self):
        seen={}
        def handler(request):
            seen.update(path=request.url.path, body=json.loads(request.content), auth=request.headers["authorization"]); return httpx.Response(200,json={"model":"m","choices":[{"message":{"content":"ok"}}]})
        with MiniMaxClient(Config(api_key="secret"),transport=httpx.MockTransport(handler)) as c: r=c.text_chat([{ "role":"user","content":"hi"}],json_mode=True)
        self.assertEqual(seen["path"],"/v1/text/chatcompletion_v2"); self.assertEqual(seen["auth"],"Bearer secret"); self.assertNotIn("response_format",seen["body"]); self.assertEqual(seen["body"]["max_tokens"], 131072); self.assertEqual(r.text,"ok")

    def test_explicit_max_tokens_is_forwarded(self):
        seen = {}
        def handler(request):
            seen.update(json.loads(request.content)); return httpx.Response(200, json={"choices":[{"message":{"content":"ok"}}]})
        with MiniMaxClient(Config(api_key="secret", max_tokens=99), transport=httpx.MockTransport(handler)) as c:
            c.text_chat([{"role":"user", "content":"hi"}], max_tokens=1234)
        self.assertEqual(seen["max_tokens"], 1234)
    def test_stream_and_errors(self):
        def stream_handler(request): return httpx.Response(200,content=b'data: {"choices":[{"delta":{"content":"a"}}]}\n\ndata: {"choices":[{"delta":{"content":"b"}}]}\n\ndata: [DONE]\n')
        got=[]
        with MiniMaxClient(Config(api_key="x"),transport=httpx.MockTransport(stream_handler)) as c: self.assertEqual(c.text_chat([{ "role":"user","content":"x"}],stream=True,on_delta=got.append).text,"ab")
        self.assertEqual(got,["a","b"])
        for status, expected in [(401,AuthenticationError),(429,QuotaExceededError)]:
            with MiniMaxClient(Config(api_key="x"),transport=httpx.MockTransport(lambda r,s=status:httpx.Response(s))) as c: self.assertRaises(expected,c.quota)
    def test_no_key_cli_protection(self):
        with patch.dict(os.environ,{"MINIMAX_API_KEY":""}):
            from minimax_cli.cli import main
            self.assertEqual(main(["quota"]),1)

if __name__ == "__main__": unittest.main()
