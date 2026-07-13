from unittest.mock import Mock, patch

import httpx

from django.test import TestCase
from django.urls import reverse
from django.utils import translation

from .models import JOB_READY, Transcribed_Video
from . import utils


def valid_lesson_json():
    import json
    return json.dumps({
        "lesson_title": "Lesson", "level": "B1", "can_do": ["I can understand"],
        "warm_up": ["Question one?", "Question two?"],
        "import_words": [{"term": f"word{i}", "meaning": f"meaning{i}"} for i in range(12)],
        "import_grammars": [{"pattern": "pattern 1"}, {"example": "example 2"}],
        "listening_tasks": [{"question": "gist?"}], "questions": ["q1"],
        "answers": ["a1"], "translation": {"0:00": "text"},
        "speaking_task": "Discuss", "writing_task": "Write 50 words", "review": ["r1"],
    })


class ArkGeneratorTests(TestCase):
    def tearDown(self):
        utils.reset_client()

    @patch("main_app.utils.ArkChatClient")
    def test_client_timeout_uses_environment_and_safe_fallbacks(
        self, client_class
    ):

        with patch.dict("os.environ", {"ARK_TIMEOUT_SECONDS": "450"}):
            utils.reset_client()
            utils._get_client()
        self.assertEqual(client_class.call_args.kwargs["timeout"], 450.0)

        for invalid_value in ("invalid", "0", "-1", "nan", "inf"):
            client_class.reset_mock()
            with patch.dict(
                "os.environ", {"ARK_TIMEOUT_SECONDS": invalid_value}
            ):
                utils.reset_client()
                utils._get_client()
            self.assertEqual(client_class.call_args.kwargs["timeout"], 300.0)

    @patch("main_app.utils.httpx.post")
    def test_response_format_400_retries_without_it(self, post):
        first = httpx.Response(400, text="unsupported response_format",
                               request=httpx.Request("POST", "https://ark.example/chat/completions"))
        second = httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]},
                                request=httpx.Request("POST", "https://ark.example/chat/completions"))
        post.side_effect = [first, second]
        client = utils.ArkChatClient("test-key", "https://ark.example", 30)
        self.assertEqual(client.chat([{"role": "user", "content": "hi"}], "model"), "{}")
        self.assertIn("response_format", post.call_args_list[0].kwargs["json"])
        self.assertNotIn("response_format", post.call_args_list[1].kwargs["json"])

    @patch("main_app.utils.time.sleep")
    @patch("main_app.utils._get_client")
    def test_network_error_is_retried_until_success(self, get_client, sleep):
        response = valid_lesson_json()
        get_client.return_value.chat.side_effect = [
            httpx.RequestError("timeout"),
            httpx.RequestError("connection reset"),
            response,
        ]

        generator = utils.Generator("German", "English", "transcript")
        with patch.dict("os.environ", {"ARK_MAX_RETRIES": "2"}):
            generator.chatbox()

        self.assertEqual(get_client.return_value.chat.call_count, 3)
        self.assertEqual(sleep.call_args_list, [((1,),), ((2,),)])
        self.assertEqual(generator.reply, valid_lesson_json())

    @patch("main_app.utils._get_client")
    def test_invalid_json_is_repaired(self, get_client):
        first, repaired = "not json", valid_lesson_json()
        get_client.return_value.chat.side_effect = [first, repaired]
        generator = utils.Generator("German", "English", "transcript")
        generator.chatbox()
        self.assertEqual(get_client.return_value.chat.call_count, 2)
        self.assertIn("response is not valid JSON", generator.message_history[2]["content"])

    @patch("main_app.utils._get_client")
    def test_invalid_repair_raises_clear_error(self, get_client):
        response = "{}"
        get_client.return_value.chat.return_value = response
        generator = utils.Generator("German", "English", "transcript")
        with self.assertRaises(utils.LearningMaterialValidationError) as raised:
            generator.chatbox()
        self.assertIn("missing required key", str(raised.exception))
        self.assertEqual(get_client.return_value.chat.call_count, 2)

    @patch("main_app.utils._get_client")
    def test_long_transcript_uses_summary_agent(self, get_client):
        summary, final = '{"keywords": ["hello"]}', valid_lesson_json()
        get_client.return_value.chat.side_effect = [summary, summary, final]
        generator = utils.Generator("German", "English", "x" * 9000)
        with patch.dict("os.environ", {"ARK_AGENT_PROMPT_CHARS": "4000", "ARK_AGENT_CHUNK_CHARS": "6000"}):
            generator.chatbox()
        calls = get_client.return_value.chat.call_args_list
        self.assertEqual(len(calls), 3)
        self.assertIn("Structured transcript summaries", calls[-1].kwargs["messages"][0]["content"])
        self.assertNotIn("x" * 6000, calls[-1].kwargs["messages"][0]["content"])

    @patch("main_app.utils.time.sleep")
    @patch("main_app.utils._get_client")
    def test_network_error_is_raised_after_retries_exhausted(
        self, get_client, sleep
    ):
        error = httpx.RequestError("timeout")
        get_client.return_value.chat.side_effect = error

        generator = utils.Generator("German", "English", "transcript")
        with patch.dict("os.environ", {"ARK_MAX_RETRIES": "2"}):
            with self.assertRaises(httpx.RequestError) as raised:
                generator.chatbox()

        self.assertIs(raised.exception, error)
        self.assertEqual(get_client.return_value.chat.call_count, 3)
        self.assertEqual(sleep.call_args_list, [((1,),), ((2,),)])


class InternationalizationTests(TestCase):
    def test_prefixed_home_pages_render_in_requested_language(self):
        zh = self.client.get("/zh/")
        en = self.client.get("/en/")
        self.assertEqual(zh.status_code, 200)
        self.assertContains(zh, "课程库")
        self.assertEqual(en.status_code, 200)
        self.assertContains(en, "Course library")
        self.assertNotContains(en, "课程库")

    def test_unprefixed_home_is_not_a_business_page(self):
        response = self.client.get("/")
        self.assertRedirects(response, "/zh/", fetch_redirect_response=False)

    def test_reverse_keeps_active_language_prefix(self):
        with translation.override("zh"):
            self.assertEqual(reverse("url_input"), "/zh/url_input")
        with translation.override("en"):
            self.assertEqual(reverse("url_input"), "/en/url_input")

    def test_ready_poll_redirect_is_language_prefixed(self):
        video = Transcribed_Video.objects.create(
            video_id="abcdefghijk", video_language="English",
            video_title="Test video", video_length=30, status=JOB_READY,
        )
        response = self.client.get(f"/en/wait/{video.video_id}/?status=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["redirect_url"], f"/en/transcript/{video.slug}")

    def test_form_labels_follow_interface_language(self):
        self.assertContains(self.client.get("/zh/url_input"), "YouTube 视频链接")
        self.assertContains(self.client.get("/en/url_input"), "YouTube video URL")
