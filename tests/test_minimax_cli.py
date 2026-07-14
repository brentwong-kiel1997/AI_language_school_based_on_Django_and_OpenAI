import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from minimax_cli import (
    Config,
    MiniMaxClient,
    AuthenticationError,
    QuotaExceededError,
    TaskTimeoutError,
    ValidationError,
)
from minimax_cli.io_utils import hex_to_bytes


class MiniMaxTests(unittest.TestCase):
    def test_default_config(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("MINIMAX_")}
        env["MINIMAX_CONFIG_DIR"] = tempfile.mkdtemp()
        with patch.dict(os.environ, env, clear=True):
            cfg = Config.load()
        self.assertEqual(cfg.text_model, "MiniMax-M3")
        self.assertEqual(cfg.region, "cn")
        self.assertEqual(cfg.base_url, "https://api.minimaxi.com")
        self.assertEqual(cfg.speech_model, "speech-2.8-hd")
        self.assertEqual(cfg.image_model, "image-01")
        self.assertEqual(cfg.video_model, "MiniMax-Hailuo-2.3")
        self.assertEqual(cfg.music_model, "music-2.6")
        self.assertEqual(cfg.context_window_tokens, 1_000_000)
        self.assertEqual(cfg.max_tokens, 131072)

    def test_region_switches_base_url(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(
            os.environ, {"MINIMAX_CONFIG_DIR": d, "MINIMAX_REGION": "global"}, clear=False
        ):
            cfg = Config.load()
            self.assertEqual(cfg.base_url, "https://api.minimax.io")
            cfg.set_value("region", "cn")
            self.assertEqual(cfg.base_url, "https://api.minimaxi.com")

    def test_env_precedes_file(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(
            os.environ,
            {"MINIMAX_CONFIG_DIR": d, "MINIMAX_API_KEY": "env-key", "MINIMAX_BASE_URL": "https://env.example"},
            clear=False,
        ):
            Config(api_key="file-key", base_url="https://file.example").save()
            cfg = Config.load()
            self.assertEqual(cfg.api_key, "env-key")
            self.assertEqual(cfg.base_url, "https://env.example")

    def test_chat_body_headers_and_json_mode(self):
        seen = {}

        def handler(request):
            seen.update(path=request.url.path, body=json.loads(request.content), auth=request.headers["authorization"])
            return httpx.Response(200, json={"model": "m", "choices": [{"message": {"content": "ok"}}]})

        with MiniMaxClient(Config(api_key="secret"), transport=httpx.MockTransport(handler)) as c:
            r = c.text_chat([{"role": "user", "content": "hi"}], json_mode=True)
        self.assertEqual(seen["path"], "/v1/text/chatcompletion_v2")
        self.assertEqual(seen["auth"], "Bearer secret")
        self.assertNotIn("response_format", seen["body"])
        self.assertEqual(seen["body"]["max_tokens"], 131072)
        self.assertEqual(r.text, "ok")

    def test_explicit_max_tokens_is_forwarded(self):
        seen = {}

        def handler(request):
            seen.update(json.loads(request.content))
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

        with MiniMaxClient(Config(api_key="secret", max_tokens=99), transport=httpx.MockTransport(handler)) as c:
            c.text_chat([{"role": "user", "content": "hi"}], max_tokens=1234)
        self.assertEqual(seen["max_tokens"], 1234)

    def test_stream_and_errors(self):
        def stream_handler(request):
            return httpx.Response(
                200,
                content=b'data: {"choices":[{"delta":{"content":"a"}}]}\n\ndata: {"choices":[{"delta":{"content":"b"}}]}\n\ndata: [DONE]\n',
            )

        got = []
        with MiniMaxClient(Config(api_key="x"), transport=httpx.MockTransport(stream_handler)) as c:
            self.assertEqual(c.text_chat([{"role": "user", "content": "x"}], stream=True, on_delta=got.append).text, "ab")
        self.assertEqual(got, ["a", "b"])
        for status, expected in [(401, AuthenticationError), (429, QuotaExceededError)]:
            with MiniMaxClient(Config(api_key="x"), transport=httpx.MockTransport(lambda r, s=status: httpx.Response(s))) as c:
                self.assertRaises(expected, c.quota)

    def test_speech_synthesize_and_voices(self):
        audio = b"ID3fake"
        hex_audio = audio.hex()
        seen = {}

        def handler(request):
            seen["path"] = request.url.path
            if request.url.path == "/v1/get_voice":
                return httpx.Response(
                    200,
                    json={
                        "system_voice": [
                            {"voice_id": "en_a", "voice_name": "English A", "description": ["en"]},
                            {"voice_id": "zh_a", "voice_name": "Chinese A", "description": ["zh"]},
                        ],
                        "base_resp": {"status_code": 0, "status_msg": "success"},
                    },
                )
            seen["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={"data": {"audio": hex_audio, "status": 2}, "base_resp": {"status_code": 0, "status_msg": "success"}},
            )

        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "speech.mp3"
            with MiniMaxClient(Config(api_key="k"), transport=httpx.MockTransport(handler)) as c:
                result = c.speech_synthesize("hello", out=out, voice_id="en_a", speed=1.1)
                self.assertEqual(seen["path"], "/v1/t2a_v2")
                self.assertEqual(seen["body"]["model"], "speech-2.8-hd")
                self.assertEqual(seen["body"]["voice_setting"]["voice_id"], "en_a")
                voices = c.speech_voices("en")
                self.assertEqual(seen["path"], "/v1/get_voice")
            self.assertEqual(out.read_bytes(), audio)
            self.assertEqual(result.size, len(audio))
            self.assertEqual(len(voices), 1)
            self.assertEqual(voices[0]["voice_id"], "en_a")

    def test_speech_stream_chunks(self):
        part1 = b"aa".hex()
        part2 = b"bb".hex()

        def handler(request):
            body = (
                f'data: {{"data":{{"audio":"{part1}","status":1}},"base_resp":{{"status_code":0}}}}\n\n'
                f'data: {{"data":{{"audio":"{part2}","status":2}},"base_resp":{{"status_code":0}}}}\n\n'
            )
            return httpx.Response(200, content=body.encode())

        chunks = []
        with MiniMaxClient(Config(api_key="k"), transport=httpx.MockTransport(handler)) as c:
            result = c.speech_synthesize("hi", stream=True, on_chunk=chunks.append)
        self.assertEqual(b"".join(chunks), b"aabb")
        self.assertEqual(result.audio, b"aabb")

    def test_image_generate_downloads(self):
        calls = []

        def handler(request):
            calls.append(str(request.url))
            if request.url.path == "/v1/image_generation":
                return httpx.Response(
                    200,
                    json={
                        "data": {"image_urls": ["https://cdn.example/a.jpg"], "task_id": "t", "success_count": 1, "failed_count": 0},
                        "base_resp": {"status_code": 0, "status_msg": "success"},
                    },
                )
            return httpx.Response(200, content=b"jpeg-bytes")

        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out.jpg"
            with MiniMaxClient(Config(api_key="k"), transport=httpx.MockTransport(handler)) as c:
                result = c.image_generate("a cat", out=out)
            self.assertTrue(any("/v1/image_generation" in u for u in calls))
            self.assertEqual(out.read_bytes(), b"jpeg-bytes")
            self.assertEqual(result.path, str(out.resolve()))

    def test_vision_describe_local_file(self):
        seen = {}

        def handler(request):
            seen["path"] = request.url.path
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"content": "a dog", "base_resp": {"status_code": 0, "status_msg": "ok"}})

        with tempfile.TemporaryDirectory() as d:
            image = Path(d) / "dog.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\n")
            with MiniMaxClient(Config(api_key="k"), transport=httpx.MockTransport(handler)) as c:
                result = c.vision_describe(image=str(image), prompt="What is this?")
        self.assertEqual(seen["path"], "/v1/coding_plan/vlm")
        self.assertTrue(seen["body"]["image_url"].startswith("data:image/png;base64,"))
        self.assertEqual(result.text, "a dog")

    def test_video_poll_download_and_timeout(self):
        state = {"n": 0}

        def handler(request):
            if request.url.path == "/v1/video_generation":
                return httpx.Response(200, json={"task_id": "tid", "base_resp": {"status_code": 0}})
            if request.url.path == "/v1/query/video_generation":
                state["n"] += 1
                status = "Success" if state["n"] >= 2 else "Processing"
                return httpx.Response(
                    200,
                    json={"task_id": "tid", "status": status, "file_id": "fid", "base_resp": {"status_code": 0}},
                )
            if request.url.path == "/v1/files/retrieve":
                return httpx.Response(
                    200,
                    json={"file": {"file_id": "fid", "download_url": "https://cdn.example/v.mp4"}, "base_resp": {"status_code": 0}},
                )
            return httpx.Response(200, content=b"mp4-bytes")

        sleeps = []
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "v.mp4"
            with MiniMaxClient(
                Config(api_key="k", poll_interval_seconds=0.01, video_timeout_seconds=5),
                transport=httpx.MockTransport(handler),
                sleep=sleeps.append,
            ) as c:
                result = c.video_generate("waves", download=out)
            self.assertEqual(out.read_bytes(), b"mp4-bytes")
            self.assertEqual(result.task_id, "tid")
            self.assertTrue(sleeps)

        def always_processing(request):
            if request.url.path == "/v1/video_generation":
                return httpx.Response(200, json={"task_id": "tid", "base_resp": {"status_code": 0}})
            return httpx.Response(200, json={"task_id": "tid", "status": "Processing", "base_resp": {"status_code": 0}})

        with MiniMaxClient(
            Config(api_key="k", poll_interval_seconds=0.01, video_timeout_seconds=0.02),
            transport=httpx.MockTransport(always_processing),
            sleep=lambda *_: None,
        ) as c:
            self.assertRaises(TaskTimeoutError, c.video_generate, "x")

    def test_music_generate_and_cover(self):
        audio = b"MUSIC"
        hex_audio = audio.hex()

        def handler(request):
            body = json.loads(request.content)
            self.assertEqual(request.url.path, "/v1/music_generation")
            if body.get("model") == "music-cover":
                self.assertIn("audio_base64", body)
            return httpx.Response(
                200,
                json={"data": {"audio": hex_audio, "status": 2}, "base_resp": {"status_code": 0, "status_msg": "ok"}},
            )

        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "m.mp3"
            cover_src = Path(d) / "src.mp3"
            cover_src.write_bytes(b"ref")
            cover_out = Path(d) / "c.mp3"
            with MiniMaxClient(Config(api_key="k"), transport=httpx.MockTransport(handler)) as c:
                result = c.music_generate(prompt="pop", lyrics="[verse] hi", out=out)
                cover = c.music_cover("jazz", audio_file=cover_src, out=cover_out)
            self.assertEqual(out.read_bytes(), audio)
            self.assertEqual(cover_out.read_bytes(), audio)
            self.assertEqual(result.size, len(audio))
            self.assertEqual(cover.size, len(audio))

    def test_music_stream_binary(self):
        def handler(request):
            return httpx.Response(200, content=b"chunk-a" + b"chunk-b")

        chunks = []
        with MiniMaxClient(Config(api_key="k"), transport=httpx.MockTransport(handler)) as c:
            result = c.music_generate(prompt="x", lyrics="[verse] y", stream=True, on_chunk=chunks.append)
        self.assertEqual(b"".join(chunks), b"chunk-achunk-b")
        self.assertEqual(result.audio, b"chunk-achunk-b")

    def test_hex_helper(self):
        self.assertEqual(hex_to_bytes("4142"), b"AB")
        with self.assertRaises(ValueError):
            hex_to_bytes("zzz")

    def test_validation_paths(self):
        with MiniMaxClient(Config(api_key="k"), transport=httpx.MockTransport(lambda r: httpx.Response(200))) as c:
            self.assertRaises(ValidationError, c.speech_synthesize, "")
            self.assertRaises(ValidationError, c.image_generate, "")
            self.assertRaises(ValidationError, c.vision_describe)
            self.assertRaises(ValidationError, c.music_cover, "p")

    def test_cli_help_and_key_protection(self):
        from minimax_cli.cli import main, _build_parser

        help_text = _build_parser().format_help()
        for name in ("text", "image", "video", "speech", "music", "vision", "search", "quota", "auth", "config"):
            self.assertIn(name, help_text)
        with patch.dict(os.environ, {"MINIMAX_API_KEY": ""}):
            self.assertEqual(main(["quota"]), 1)
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {"MINIMAX_CONFIG_DIR": d, "MINIMAX_API_KEY": "secret-key"}, clear=False):
            # ensure help / status does not dump secret into stdout via config show after login
            self.assertEqual(main(["auth", "login", "--api-key", "secret-key"]), 0)
            from io import StringIO

            buf = StringIO()
            with patch("sys.stdout", buf):
                self.assertEqual(main(["config", "show"]), 0)
            self.assertNotIn("secret-key", buf.getvalue())
            self.assertIn("***", buf.getvalue())

    def test_cli_speech_args(self):
        from minimax_cli.cli import main

        audio = b"xx"
        hex_audio = audio.hex()

        def handler(request):
            return httpx.Response(
                200,
                json={"data": {"audio": hex_audio, "status": 2}, "base_resp": {"status_code": 0, "status_msg": "ok"}},
            )

        with tempfile.TemporaryDirectory() as d, patch.dict(
            os.environ, {"MINIMAX_CONFIG_DIR": d, "MINIMAX_API_KEY": "k", "MINIMAX_OUTPUT_DIR": d}, clear=False
        ), patch("minimax_cli.cli.MiniMaxClient") as client_cls:
            instance = client_cls.return_value.__enter__.return_value
            instance.speech_synthesize.return_value.path = str(Path(d) / "out.mp3")
            instance.speech_synthesize.return_value.size = 2
            code = main(["speech", "synthesize", "--text", "hi", "--out", str(Path(d) / "out.mp3")])
            self.assertEqual(code, 0)
            instance.speech_synthesize.assert_called()


if __name__ == "__main__":
    unittest.main()
