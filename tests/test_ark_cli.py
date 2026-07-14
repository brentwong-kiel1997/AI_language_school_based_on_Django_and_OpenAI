import asyncio
import gzip
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

import httpx

from ark_cli import Config, asr, get_client, reset_client
from ark_cli.client import ArkChatClient
from ark_cli.config import DEFAULT_ARK_TIMEOUT_SECONDS


class ArkClientTests(unittest.TestCase):
    def tearDown(self):
        reset_client()

    @patch("ark_cli.client.ArkChatClient")
    def test_client_timeout_uses_environment_and_safe_fallbacks(self, client_class):
        with patch.dict("os.environ", {"ARK_API_KEY": "k", "ARK_TIMEOUT_SECONDS": "450"}):
            reset_client()
            get_client()
        self.assertEqual(client_class.call_args.kwargs["timeout"], 450.0)

        for invalid_value in ("invalid", "0", "-1", "nan", "inf"):
            client_class.reset_mock()
            with patch.dict("os.environ", {"ARK_API_KEY": "k", "ARK_TIMEOUT_SECONDS": invalid_value}):
                reset_client()
                get_client()
            self.assertEqual(client_class.call_args.kwargs["timeout"], DEFAULT_ARK_TIMEOUT_SECONDS)

    @patch("ark_cli.client.httpx.post")
    def test_response_format_400_retries_without_it(self, post):
        first = httpx.Response(
            400,
            text="unsupported response_format",
            request=httpx.Request("POST", "https://ark.example/chat/completions"),
        )
        second = httpx.Response(
            200,
            json={"choices": [{"message": {"content": "{}"}}]},
            request=httpx.Request("POST", "https://ark.example/chat/completions"),
        )
        post.side_effect = [first, second]
        client = ArkChatClient("test-key", "https://ark.example", 30)
        self.assertEqual(client.chat([{"role": "user", "content": "hi"}], "model"), "{}")
        self.assertIn("response_format", post.call_args_list[0].kwargs["json"])
        self.assertNotIn("response_format", post.call_args_list[1].kwargs["json"])

    @patch("ark_cli.client.httpx.post")
    def test_ark_chat_passes_configured_max_tokens(self, post):
        post.return_value = httpx.Response(
            200,
            json={"choices": [{"message": {"content": "{}"}}]},
            request=httpx.Request("POST", "https://ark.example/chat/completions"),
        )
        client = ArkChatClient("test-key", "https://ark.example", 30)
        client.chat([], "model", max_tokens=4096)
        self.assertEqual(post.call_args.kwargs["json"]["max_tokens"], 4096)

    def test_config_redacts_api_key(self):
        with patch.dict("os.environ", {"ARK_API_KEY": "secret-key"}):
            data = Config.load().redacted()
        self.assertEqual(data["api_key"], "***")
        self.assertNotIn("secret-key", json.dumps(data))


class SeedASRProtocolTests(unittest.TestCase):
    def test_frame_round_trip_and_error_frame(self):
        packet = asr.build_frame(
            asr.SERVER_FULL_RESPONSE,
            {"result": {"text": "ok"}},
            flags=asr.POS_SEQUENCE,
            sequence=7,
        )
        frame = asr.parse_frame(packet)
        self.assertEqual((frame.sequence, frame.payload["result"]["text"]), (7, "ok"))
        payload = gzip.compress(json.dumps({"message": "denied"}).encode())
        error = bytes((0x11, 0xF0, 0x11, 0)) + struct.pack(">I", 401) + struct.pack(">I", len(payload)) + payload
        frame = asr.parse_frame(error)
        with self.assertRaisesRegex(asr.SeedASRError, "401.*denied"):
            asr._check_frame(frame)

    def test_truncated_frame_is_rejected(self):
        with self.assertRaisesRegex(asr.SeedASRError, "truncated"):
            asr.parse_frame(b"123")


class SeedASRStreamingTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.wav_path = Path(self.temp_dir.name) / "audio.wav"
        import wave

        with wave.open(str(self.wav_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"\0" * 6400)

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def _message(payload, *, final=False):
        flags = asr.NEG_WITH_SEQUENCE if final else asr.POS_SEQUENCE
        sequence = -2 if final else 2
        return Mock(
            type=asr.aiohttp.WSMsgType.BINARY,
            data=asr.build_frame(
                asr.SERVER_FULL_RESPONSE, payload, flags=flags, sequence=sequence
            ),
        )

    def _session_factory(self, ws, captured):
        class WebSocketContext:
            async def __aenter__(self):
                return ws

            async def __aexit__(self, *args):
                return False

        class Session:
            def __init__(self, *, timeout):
                captured["timeout"] = timeout

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            def ws_connect(self, *args, **kwargs):
                return WebSocketContext()

        return Session

    async def test_audio_is_paced_while_results_are_received(self):
        receive_started = asyncio.Event()
        allow_audio_send = asyncio.Event()
        final_audio_sent = asyncio.Event()
        ws = Mock()
        sent_packets = []

        async def send_bytes(packet):
            sent_packets.append(packet)
            if len(sent_packets) == 2:
                await asyncio.wait_for(allow_audio_send.wait(), 1)
            if len(sent_packets) > 1:
                frame = asr.parse_frame(packet)
                if frame.flags == asr.NEG_WITH_SEQUENCE:
                    final_audio_sent.set()

        responses = [
            self._message({"result": {}}),
            self._message({"result": {"text": "partial"}}),
            self._message({"result": {"text": "done"}}, final=True),
        ]

        async def receive(*args, **kwargs):
            if len(responses) == 1:
                await asyncio.wait_for(final_audio_sent.wait(), 1)
            message = responses.pop(0)
            if len(responses) == 1:
                receive_started.set()
                allow_audio_send.set()
            return message

        ws.send_bytes = AsyncMock(side_effect=send_bytes)
        ws.receive = AsyncMock(side_effect=receive)
        captured = {}
        real_sleep = asyncio.sleep

        async def paced_sleep(delay):
            await real_sleep(0)

        with patch.object(asr.aiohttp, "ClientSession", self._session_factory(ws, captured)), patch.object(
            asr.asyncio, "sleep", AsyncMock(side_effect=paced_sleep)
        ) as sleep:
            result = await asr.transcribe_wav_async(
                self.wav_path,
                api_key="key",
                segment_ms=100,
                timeout=5,
                language="ru-RU",
            )

        self.assertTrue(receive_started.is_set())
        self.assertEqual(result["text"], "done")
        self.assertGreaterEqual(sleep.await_count, 1)
        sleep.assert_any_await(0.1)
        self.assertIsNone(captured["timeout"].total)
        initialization_frame = asr.parse_frame(sent_packets[0])
        self.assertEqual(initialization_frame.payload["audio"]["language"], "ru-RU")
        self.assertIs(initialization_frame.payload["request"]["enable_lid"], True)
        self.assertIs(initialization_frame.payload["request"]["enable_nonstream"], True)
        final_frame = asr.parse_frame(sent_packets[-1])
        self.assertEqual(final_frame.flags, asr.NEG_WITH_SEQUENCE)
        self.assertLess(final_frame.sequence, 0)

    async def test_async_endpoint_omits_language_from_payload(self):
        ws = Mock()
        sent_packets = []
        ws.send_bytes = AsyncMock(side_effect=lambda packet: sent_packets.append(packet))
        ws.receive = AsyncMock(
            side_effect=[
                self._message({"result": {}}),
                self._message({"result": {"text": "done"}}, final=True),
            ]
        )
        captured = {}

        with patch.object(asr.aiohttp, "ClientSession", self._session_factory(ws, captured)), patch.object(
            asr.asyncio, "sleep", AsyncMock()
        ):
            await asr.transcribe_wav_async(
                self.wav_path,
                api_key="key",
                ws_url="wss://openspeech.bytedance.com/api/v3/plan/sauc/bigmodel_async",
                segment_ms=100,
                timeout=5,
                language="ru-RU",
            )

        initialization_frame = asr.parse_frame(sent_packets[0])
        self.assertNotIn("language", initialization_frame.payload["audio"])

    async def test_long_audio_uses_duration_plus_allowance_without_session_total(self):
        class FakeWav:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def getframerate(self):
                return 16000

            def getnchannels(self):
                return 1

            def getsampwidth(self):
                return 2

            def getnframes(self):
                return 498 * 16000

        class Deadline:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

        ws = Mock()
        ws.send_bytes = AsyncMock()
        ws.receive = AsyncMock(
            side_effect=[
                self._message({"result": {}}),
                self._message({"result": {"text": "done"}}, final=True),
            ]
        )
        captured = {}
        timeout_context = Mock(return_value=Deadline())

        with patch.object(asr.wave, "open", return_value=FakeWav()), patch.object(
            asr.aiohttp, "ClientSession", self._session_factory(ws, captured)
        ), patch.object(asr.asyncio, "timeout", timeout_context):
            result = await asr.transcribe_wav_async(
                self.wav_path, api_key="key", segment_ms=100, timeout=120
            )

        self.assertEqual(result["text"], "done")
        self.assertIsNone(captured["timeout"].total)
        timeout_context.assert_called_once_with(618)

    async def test_receiver_error_cancels_sender(self):
        sender_cancelled = asyncio.Event()
        ws = Mock()
        ws.send_bytes = AsyncMock()
        responses = [
            self._message({"result": {}}),
            Mock(type=asr.aiohttp.WSMsgType.ERROR),
        ]
        ws.receive = AsyncMock(side_effect=lambda *args, **kwargs: responses.pop(0))
        captured = {}

        async def blocking_sleep(delay):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                sender_cancelled.set()
                raise

        with patch.object(asr.aiohttp, "ClientSession", self._session_factory(ws, captured)), patch.object(
            asr.asyncio, "sleep", side_effect=blocking_sleep
        ):
            with self.assertRaisesRegex(asr.SeedASRError, "stream ended unexpectedly"):
                await asr.transcribe_wav_async(self.wav_path, api_key="key", segment_ms=100, timeout=5)

        self.assertTrue(sender_cancelled.is_set())


if __name__ == "__main__":
    unittest.main()
