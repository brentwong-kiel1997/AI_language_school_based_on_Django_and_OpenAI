from unittest.mock import Mock, patch

import json
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
from ark_cli import asr

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import translation

from .models import JOB_READY, Learning_Material, Transcribed_Video
from . import utils, views


def valid_module_json(name):
    modules = {
        "core": {
            "lesson_title": "Lesson", "level": "B1",
            "can_do": ["I can understand"],
            "warm_up": ["Question one?", "Question two?"],
        },
        "words": {
            "import_words": [
                {"term": f"word{i}", "part_of_speech": "noun", "senses": [
                    {"definition": f"definition{i}", "translation": f"meaning{i}",
                     "example": f"Example {i}.", "collocations": []}
                ]}
                for i in range(12)
            ]
        },
        "grammar": {
            "import_grammars": [
                {"pattern": "pattern 1", "example": "Example 1."},
                {"explanation": "explanation 2", "practice": "Practice 2."},
            ]
        },
        "listening": {
            "listening_tasks": [{"question": "gist?"}],
            "questions": ["q1"], "answers": ["a1"],
        },
        "expression": {
            "speaking_task": "Discuss", "writing_task": "Write 50 words",
            "review": ["r1"],
        },
        "translation": {"translation": {"0:00": "text"}},
    }
    return json.dumps(modules[name])


def valid_lesson_json():
    lesson = {}
    for name in ("core", "words", "grammar", "listening", "expression", "translation"):
        lesson.update(json.loads(valid_module_json(name)))
    return json.dumps(lesson)


class ArkGeneratorTests(TestCase):
    def tearDown(self):
        utils.reset_client()

    @patch("main_app.utils.time.sleep")
    @patch("main_app.utils._get_client")
    def test_network_error_is_retried_until_success(self, get_client, sleep):
        responses = [httpx.RequestError("timeout"), httpx.RequestError("connection reset")]
        responses += [valid_module_json(name) for name in ("core", "words", "grammar", "listening", "expression", "translation")]
        get_client.return_value.chat.side_effect = responses
        generator = utils.Generator("German", "English", "transcript")
        with patch.dict("os.environ", {"ARK_MAX_RETRIES": "2"}):
            generator.chatbox()
        self.assertEqual(get_client.return_value.chat.call_count, 8)
        self.assertEqual(sleep.call_args_list, [((1,),), ((2,),)])
        self.assertEqual(json.loads(generator.reply), json.loads(valid_lesson_json()))

    @patch("main_app.utils._get_client")
    def test_modules_are_requested_and_merged(self, get_client):
        names = ("core", "words", "grammar", "listening", "expression", "translation")
        get_client.return_value.chat.side_effect = [valid_module_json(name) for name in names]
        generator = utils.Generator("German", "English", "transcript")
        generator.chatbox()
        self.assertEqual(get_client.return_value.chat.call_count, 6)
        calls = get_client.return_value.chat.call_args_list
        prompts = [call.kwargs["messages"][0]["content"] for call in calls]
        self.assertTrue(all(prompt.strip() for prompt in prompts))
        expected_max_tokens = utils.DEFAULT_ARK_MAX_TOKENS
        self.assertTrue(all(call.kwargs["max_tokens"] == expected_max_tokens for call in calls))
        self.assertEqual(json.loads(generator.reply), json.loads(valid_lesson_json()))

    @patch("main_app.utils._get_client")
    def test_invalid_module_json_is_repaired(self, get_client):
        names = ("core", "words", "grammar", "listening", "expression", "translation")
        get_client.return_value.chat.side_effect = ["not json", valid_module_json("core")] + [valid_module_json(name) for name in names[1:]]
        generator = utils.Generator("German", "English", "transcript")
        generator.chatbox()
        self.assertEqual(get_client.return_value.chat.call_count, 7)
        self.assertIn("response is not valid JSON", generator.message_history[2]["content"])

    @patch("main_app.utils._get_client")
    def test_invalid_module_repair_raises_clear_error(self, get_client):
        get_client.return_value.chat.return_value = "{}"
        generator = utils.Generator("German", "English", "transcript")
        with self.assertRaises(utils.LearningMaterialValidationError) as raised:
            generator.chatbox()
        self.assertIn("Ark module core invalid after validation", str(raised.exception))
        self.assertEqual(get_client.return_value.chat.call_count, 2)

    @patch("main_app.utils._get_client")
    def test_long_transcript_summarises_before_module_calls(self, get_client):
        names = ("core", "words", "grammar", "listening", "expression", "translation")
        get_client.return_value.chat.side_effect = [
            '{"keywords": ["hello"]}', '{"keywords": ["world"]}',
            *[valid_module_json(name) for name in names],
        ]
        generator = utils.Generator("German", "English", "x" * 9000)
        with patch.dict("os.environ", {"ARK_AGENT_PROMPT_CHARS": "4000", "ARK_AGENT_CHUNK_CHARS": "6000"}):
            generator.chatbox()
        calls = get_client.return_value.chat.call_args_list
        self.assertEqual(len(calls), 8)
        self.assertIn("Structured transcript summaries", calls[2].kwargs["messages"][0]["content"])
        self.assertNotIn("x" * 6000, calls[2].kwargs["messages"][0]["content"])

    @patch("main_app.utils.time.sleep")
    @patch("main_app.utils._get_client")
    def test_network_error_is_raised_after_retries_exhausted(self, get_client, sleep):
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

    def test_create_course_caption_guidance_follows_interface_language(self):
        zh = self.client.get("/zh/url_input")
        en = self.client.get("/en/url_input")

        self.assertContains(zh, "优先使用 YouTube 字幕")
        self.assertContains(
            zh,
            "优先使用人工字幕，其次使用自动字幕；没有字幕时通过 Seed ASR 进行语音识别。",
        )
        self.assertNotContains(zh, "带有 YouTube 字幕")
        self.assertNotContains(zh, "可以是人工字幕或自动字幕")
        self.assertContains(en, "Captions are preferred")
        self.assertContains(
            en,
            "We use manual captions first, then automatic captions, and Seed ASR when no captions are available.",
        )
        self.assertNotContains(en, "Has YouTube captions")
        self.assertNotContains(en, "Manual or automatic captions are accepted")


@override_settings(ALLOWED_HOSTS=["testserver"])
class YouTubeEmbedTests(TestCase):
    def setUp(self):
        self.video = Transcribed_Video.objects.create(
            video_id="VX95qAiPad8",
            video_language="English",
            video_title="Test video",
            video_length=30,
            video_text="{}",
            status=JOB_READY,
        )

    def test_transcript_embed_identifies_origin_and_referrer(self):
        response = self.client.get(f"/en/transcript/{self.video.slug}")

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, 'referrerpolicy="strict-origin-when-cross-origin"'
        )
        self.assertContains(response, "allowfullscreen")
        self.assertEqual(
            response.headers["Referrer-Policy"],
            "strict-origin-when-cross-origin",
        )

        embed_url = response.context["embedded"]
        self.assertIn("origin=http%3A%2F%2Ftestserver", embed_url)
        query = parse_qs(urlparse(embed_url).query)
        self.assertEqual(query["origin"], ["http://testserver"])
        self.assertEqual(query["enablejsapi"], ["1"])

    def test_learning_material_uses_lexicon_and_grammar_entries(self):
        Learning_Material.objects.create(
            linked_video=self.video,
            native_language="Chinese",
            material=json.dumps({
                "import_words": [{"term": "hello", "meaning": "你好", "example": "Hello!", "note": "greeting"}],
                "import_grammars": [{"pattern": "subject + verb", "example": "I learn.", "explanation": "A basic sentence.", "practice": "Make a sentence."}],
            }),
            status=JOB_READY,
        )

        response = self.client.get(f"/en/learning_material/{self.video.video_id}/Chinese")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="lexicon-entry"')
        self.assertContains(response, 'class="grammar-entry"')
        self.assertContains(response, "hello")
        self.assertContains(response, "Meaning")
        self.assertContains(response, "Pattern")

        template = response.templates[0].source
        self.assertIn(
            '<div class="col-12"><section class="card material-section"><h3>{% trans "Key vocabulary" %}',
            template,
        )
        self.assertIn(
            '<div class="col-12"><section class="card material-section"><h3>{% trans "Grammar" %}',
            template,
        )
        self.assertNotIn(
            '<div class="col-md-6"><section class="card material-section"><h3>{% trans "Key vocabulary" %}',
            template,
        )
        self.assertNotIn(
            '<div class="col-md-6"><section class="card material-section"><h3>{% trans "Grammar" %}',
            template,
        )

    def test_learning_material_embed_has_referrer_policy(self):
        Learning_Material.objects.create(
            linked_video=self.video,
            native_language="Chinese",
            material="{}",
            status=JOB_READY,
        )

        response = self.client.get(
            f"/en/learning_material/{self.video.video_id}/Chinese"
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, 'referrerpolicy="strict-origin-when-cross-origin"'
        )
        query = parse_qs(urlparse(response.context["embedded"]).query)
        self.assertEqual(query["origin"], ["http://testserver"])
        self.assertEqual(query["enablejsapi"], ["1"])


class TranscribeFallbackTests(TestCase):
    def _info(self, **updates):
        info = {"duration": 30, "title": "Video", "id": "abc",
                "upload_date": "20260102", "subtitles": {},
                "automatic_captions": {}}
        info.update(updates)
        return info

    def _ydl(self, info):
        manager = Mock()
        manager.__enter__ = Mock(return_value=manager)
        manager.__exit__ = Mock(return_value=False)
        manager.extract_info.return_value = info
        return manager

    @patch("main_app.utils.httpx.get")
    @patch("main_app.utils.youtube_dl.YoutubeDL")
    @patch("main_app.utils.Transcribe._download_and_convert")
    @patch("main_app.utils.asr.transcribe_wav")
    def test_manual_captions_win_without_download_or_asr(self, transcribe, download, ydl_class, get):
        manual = [{"ext": "json3", "url": "manual"}]
        automatic = [{"ext": "json3", "url": "automatic"}]
        ydl_class.return_value = self._ydl(self._info(
            subtitles={"de": manual}, automatic_captions={"en": automatic}))
        get.return_value.json.return_value = {"events": [{"tStartMs": 0, "dDurationMs": 500,
                                                           "segs": [{"utf8": "Hallo"}]}]}
        get.return_value.raise_for_status.return_value = None
        item = utils.Transcribe("url"); item.audio2text()
        self.assertEqual(get.call_args.args[0], "manual")
        self.assertEqual(item.language, "de")
        download.assert_not_called(); transcribe.assert_not_called()

    @patch("main_app.utils.httpx.get")
    @patch("main_app.utils.youtube_dl.YoutubeDL")
    def test_automatic_captions_are_used(self, ydl_class, get):
        ydl_class.return_value = self._ydl(self._info(
            automatic_captions={"en-orig": [{"ext": "json3", "url": "auto"}]}))
        get.return_value.raise_for_status.return_value = None
        get.return_value.json.return_value = {"events": [{"tStartMs": 1000,
            "dDurationMs": 500, "segs": [{"utf8": "Hello"}]}]}
        item = utils.Transcribe("url"); item.audio2text()
        self.assertEqual(item.transcript["source"], "youtube_captions")
        self.assertEqual(item.language, "en")

    @patch("main_app.utils.asr.transcribe_wav")
    @patch("main_app.utils.Transcribe._download_and_convert")
    @patch("main_app.utils.youtube_dl.YoutubeDL")
    def test_missing_captions_downloads_audio_and_uses_asr(self, ydl_class, download, transcribe):
        ydl_class.return_value = self._ydl(self._info())
        download.return_value = Path("audio.wav")
        transcribe.return_value = {"text": "hello"}
        item = utils.Transcribe("url"); item.audio2text()
        download.assert_called_once()
        transcribe.assert_called_once_with(Path("audio.wav"), language=None)
        self.assertEqual(item.transcript["source"], "seed_asr_2.0")

    @patch("main_app.utils.asr.transcribe_wav")
    @patch("main_app.utils.Transcribe._download_and_convert")
    @patch("main_app.utils.youtube_dl.YoutubeDL")
    def test_metadata_language_is_mapped_for_asr(self, ydl_class, download, transcribe):
        ydl_class.return_value = self._ydl(self._info(language="ru"))
        download.return_value = Path("audio.wav")
        transcribe.return_value = {"text": "привет"}

        utils.Transcribe("url").audio2text()

        transcribe.assert_called_once_with(Path("audio.wav"), language="ru-RU")

    @patch("main_app.utils.asr.transcribe_wav")
    @patch("main_app.utils.Transcribe._download_and_convert")
    @patch("main_app.utils.httpx.get")
    @patch("main_app.utils.youtube_dl.YoutubeDL")
    def test_caption_http_error_does_not_trigger_asr(self, ydl_class, get, download, transcribe):
        ydl_class.return_value = self._ydl(self._info(
            subtitles={"en": [{"ext": "json3", "url": "bad"}]}))
        get.return_value.raise_for_status.side_effect = httpx.HTTPStatusError(
            "bad", request=httpx.Request("GET", "https://x"), response=httpx.Response(500))
        with self.assertRaisesRegex(RuntimeError, "caption track"):
            utils.Transcribe("url").audio2text()
        download.assert_not_called(); transcribe.assert_not_called()

    @patch("main_app.utils.asr.transcribe_wav", return_value={"text": "fallback"})
    @patch("main_app.utils.Transcribe._download_and_convert", return_value=Path("audio.wav"))
    @patch("main_app.utils.httpx.get")
    @patch("main_app.utils.youtube_dl.YoutubeDL")
    def test_empty_caption_payload_triggers_asr(self, ydl_class, get, download, transcribe):
        ydl_class.return_value = self._ydl(self._info(
            subtitles={"en": [{"ext": "json3", "url": "empty"}]}))
        get.return_value.raise_for_status.return_value = None
        get.return_value.json.return_value = {"events": []}
        utils.Transcribe("url").audio2text()
        download.assert_called_once(); transcribe.assert_called_once()

    @patch("main_app.utils.Transcribe._download_and_convert")
    @patch("main_app.utils.youtube_dl.YoutubeDL")
    def test_video_over_limit_is_rejected_before_download(self, ydl_class, download):
        ydl_class.return_value = self._ydl(self._info(duration=601))
        with self.assertRaisesRegex(ValueError, "10 minutes"):
            utils.Transcribe("url").audio2text()
        download.assert_not_called()

    def test_asr_result_converts_milliseconds_language_and_same_second(self):
        result = {"text": "你好 世界", "utterances": [
            {"text": "ignored", "start_time": 0, "end_time": 100, "definite": False},
            {"text": "你好", "start_time": 100, "end_time": 500, "definite": True,
             "additions": {"lid_lang": "speech_mand"}},
            {"text": "世界", "start_time": 800, "end_time": 1200, "definite": True}]}
        transcript, timestamps, language = utils._asr_transcript(result, 2)
        self.assertEqual(language, "zh")
        self.assertEqual(transcript["segments"][0]["start"], 0.1)
        self.assertEqual(timestamps, {"0:00:00": "你好 世界"})

    @patch("main_app.utils.asr.transcribe_wav")
    @patch("main_app.utils.Transcribe._download_and_convert")
    @patch("main_app.utils.youtube_dl.YoutubeDL")
    def test_created_files_are_cleaned_on_success_and_failure(self, ydl_class, download, transcribe):
        ydl_class.return_value = self._ydl(self._info())
        for error in (None, asr.SeedASRError("failed")):
            with tempfile.TemporaryDirectory() as root:
                made = Path(root) / "made"
                def create(url, output, created):
                    made.mkdir(); wav = made / "audio.wav"; wav.write_bytes(b"x")
                    created.extend([made, wav]); return wav
                download.side_effect = create
                transcribe.side_effect = error
                transcribe.return_value = {"text": "ok"}
                if error:
                    with self.assertRaises(asr.SeedASRError):
                        utils.Transcribe("url").audio2text(output_path=root)
                else:
                    utils.Transcribe("url").audio2text(output_path=root)
                self.assertFalse(made.exists())
