from unittest.mock import Mock, patch

import json
import re
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import translation

from .models import JOB_READY, Learning_Material, Transcribed_Video
from . import utils, views


def valid_module_json(name, target_language="german"):
    words_fixture = {
        "russian": {
            "import_words": [
                {
                    "term": f"слово{i}",
                    "pronunciation": {"stress_marked": f"сло́во{i}"},
                    "part_of_speech": "сущ.",
                    "grammatical_info": {"gender": "neuter"},
                    "senses": [
                        {
                            "definition": f"определение {i}",
                            "translation": f"词义{i}",
                            "example": f"Пример {i}.",
                            "collocations": [],
                        }
                    ],
                }
                for i in range(12)
            ]
        },
        "english": {
            "import_words": [
                {
                    "term": f"word{i}",
                    "ipa": f"/wɜːd{i}/",
                    "part_of_speech": "noun",
                    "cefr": "B1",
                    "senses": [
                        {
                            "definition": f"definition {i}",
                            "translation": f"词义{i}",
                            "example": f"Example {i}.",
                            "collocations": [],
                        }
                    ],
                }
                for i in range(12)
            ]
        },
        "german": {
            "import_words": [
                {
                    "term": f"Wort{i}",
                    "pronunciation": f"[vɔʁt{i}]",
                    "part_of_speech": "Substantiv",
                    "article": "das",
                    "gender": "neuter",
                    "senses": [
                        {
                            "definition": f"Definition {i}.",
                            "translation": f"词义{i}",
                            "example": f"Beispiel {i}.",
                            "collocations": [],
                        }
                    ],
                }
                for i in range(12)
            ]
        },
    }
    lang = target_language.strip().lower()
    if lang in {"de", "german", "德语"}:
        lang_key = "german"
    elif lang in {"en", "english", "英语"}:
        lang_key = "english"
    elif lang in {"ru", "russian", "俄语", "русский"}:
        lang_key = "russian"
    else:
        lang_key = "german"

    modules = {
        "core": {
            "lesson_title": "Lesson", "level": "B1",
            "can_do": ["I can understand"],
            "warm_up": ["Question one?", "Question two?"],
        },
        "words": words_fixture[lang_key],
        "grammar": {
            "import_grammars": [
                {
                    "pattern": "pattern 1",
                    "meaning": "function 1",
                    "overview": "Short overview 1.",
                    "collocations": [{"phrase": "do X", "translation": "做 X"}],
                    "forms": ["form A"],
                    "model": {"sentence": "This is a model.", "translation": "这是例句。"},
                    "note": "Note 1.",
                    "examples": [{"phrase": "Example 1.", "translation": "译文1"}],
                    "practice": {
                        "instruction": "Do this:",
                        "items": [
                            {"prompt": "Prompt A", "answer": "Answer A"},
                            {"prompt": "Prompt B", "answer": "Answer B"},
                        ],
                    },
                },
                {
                    "pattern": "pattern 2",
                    "meaning": "function 2",
                    "overview": "Short overview 2.",
                    "collocations": [{"phrase": "do Y", "translation": "做 Y"}],
                    "forms": ["form B"],
                    "model": {"sentence": "Another model.", "translation": "另一句。"},
                    "note": "",
                    "examples": [{"phrase": "Example 2.", "translation": "译文2"}],
                    "practice": {
                        "instruction": "Translate:",
                        "items": [{"prompt": "Prompt C", "answer": "Answer C"}],
                    },
                },
            ]
        },
        "listening": {
            "listening_tasks": [{
                "type": "true_false",
                "instruction": "判断正误：",
                "items": [{"statement": "Statement one.", "answer": "В"}],
            }],
            "questions": ["q1"], "answers": ["a1"],
        },
        "expression": {
            "speaking_task": {
                "prompt": "Discuss the topic.",
                "duration": "1-2 min",
                "useful_language": ["word1", "word2"],
                "checklist": ["Point one", "Point two"],
                "sample_answer": "I think the report shows cooperation.",
            },
            "writing_task": {
                "prompt": "Write a short essay.",
                "length": "8-12 sentences",
                "useful_language": ["word3"],
                "checklist": ["Use a conclusion"],
                "support_phrases": ["I think"],
                "sample_answer": "In my opinion this is important. Thus we should notice it.",
            },
            "review": [{"term": "word1", "translation": "词1"}],
        },
        "translation": {"translation": {"0:00": "text"}},
    }
    return json.dumps(modules[name])


def valid_lesson_json():
    lesson = {}
    for name in ("core", "words", "grammar", "listening", "expression", "translation"):
        lesson.update(json.loads(valid_module_json(name)))
    return json.dumps(lesson)


def checker_ok():
    return '{"ok": true}'


def writer_then_checker(*module_names):
    """Interleave Writer module JSON with Checker acceptance for each module."""
    sequence = []
    for name in module_names:
        sequence.append(valid_module_json(name))
        sequence.append(checker_ok())
    return sequence


class MiniMaxGeneratorTests(TestCase):
    def setUp(self):
        # Sequential side_effect mocks require one module at a time.
        self._workers = patch.dict(
            "os.environ",
            {"MINIMAX_MODULE_WORKERS": "1", "MINIMAX_WORDS_BATCHES": "1"},
            clear=False,
        )
        self._workers.start()

    def tearDown(self):
        self._workers.stop()
        utils.reset_client()

    @patch("main_app.utils.time.sleep")
    @patch("main_app.utils._get_client")
    def test_network_error_is_retried_until_success(self, get_client, sleep):
        names = ("core", "words", "grammar", "listening", "expression", "translation")
        responses = [httpx.RequestError("timeout"), httpx.RequestError("connection reset")]
        responses += writer_then_checker(*names)
        get_client.return_value.chat.side_effect = responses
        generator = utils.Generator("German", "English", "transcript")
        with patch.dict("os.environ", {"MINIMAX_MAX_RETRIES": "2"}, clear=False):
            generator.chatbox()
        # 2 network failures + 6 writer + 6 checker
        self.assertEqual(get_client.return_value.chat.call_count, 14)
        self.assertEqual(sleep.call_args_list, [((1,),), ((2,),)])
        self.assertEqual(json.loads(generator.reply), json.loads(valid_lesson_json()))

    @patch("main_app.utils._get_client")
    def test_modules_are_requested_and_merged(self, get_client):
        names = ("core", "words", "grammar", "listening", "expression", "translation")
        get_client.return_value.chat.side_effect = writer_then_checker(*names)
        generator = utils.Generator("German", "English", "transcript")
        generator.chatbox()
        self.assertEqual(get_client.return_value.chat.call_count, 12)
        calls = get_client.return_value.chat.call_args_list
        prompts = [call.kwargs["messages"][0]["content"] for call in calls]
        self.assertTrue(all(prompt.strip() for prompt in prompts))
        writer_prompts = prompts[0::2]
        checker_prompts = prompts[1::2]
        self.assertTrue(all("Writer agent" in p for p in writer_prompts))
        self.assertTrue(all("Checker agent" in p for p in checker_prompts))
        expected_max_tokens = utils.DEFAULT_MAX_TOKENS
        self.assertTrue(all(call.kwargs["max_tokens"] == expected_max_tokens for call in calls))
        self.assertEqual(json.loads(generator.reply), json.loads(valid_lesson_json()))

    @patch("main_app.utils._get_client")
    def test_modules_run_in_parallel(self, get_client):
        """With workers>1, modules are dispatched concurrently and still merge."""
        self._workers.stop()
        try:
            # Match more-specific module markers first (shared words like "translation").
            writer_markers = (
                ("words", "import_words"),
                ("grammar", "import_grammars"),
                ("listening", "listening_tasks"),
                ("expression", "speaking_task"),
                ("translation", "Top-level key MUST be"),
                ("core", "lesson_title"),
            )

            def dispatch(**kwargs):
                content = kwargs["messages"][0]["content"]
                if "Checker agent" in content:
                    for name, _ in writer_markers:
                        if f"Module: {name}\n" in content:
                            return checker_ok()
                    return checker_ok()
                if "Writer agent" in content:
                    for name, needle in writer_markers:
                        if needle in content:
                            return valid_module_json(name)
                raise AssertionError(f"unexpected prompt: {content[:240]}")

            get_client.return_value.chat.side_effect = dispatch
            generator = utils.Generator("German", "English", "transcript")
            with patch.dict(
                "os.environ",
                {"MINIMAX_MODULE_WORKERS": "6", "MINIMAX_WORDS_BATCHES": "1"},
                clear=False,
            ):
                generator.chatbox()
            self.assertEqual(get_client.return_value.chat.call_count, 12)
            self.assertEqual(json.loads(generator.reply), json.loads(valid_lesson_json()))
        finally:
            self._workers.start()

    @patch("main_app.utils._get_client")
    def test_words_batches_merge_without_duplicates(self, get_client):
        """Two vocab batches run in parallel and merge to 8–20 unique lemmas."""
        self._workers.stop()
        try:
            batch_payloads = []
            for batch_i, terms in enumerate((
                [f"alpha{i}" for i in range(8)],
                [f"beta{i}" for i in range(8)],
            )):
                batch_payloads.append({
                    "import_words": [
                        {
                            "term": term,
                            "pronunciation": f"[{term}]",
                            "part_of_speech": "Substantiv",
                            "article": "das",
                            "gender": "neuter",
                            "senses": [{
                                "definition": f"Def {term}",
                                "translation": f"译{term}",
                                "example": f"Ex {term}.",
                                "collocations": [],
                            }],
                        }
                        for term in terms
                    ]
                })

            def dispatch(**kwargs):
                content = kwargs["messages"][0]["content"]
                if "Checker agent" in content:
                    return checker_ok()
                if "Writer agent" in content and "VOCABULARY BATCH 1 of 2" in content:
                    return json.dumps(batch_payloads[0])
                if "Writer agent" in content and "VOCABULARY BATCH 2 of 2" in content:
                    return json.dumps(batch_payloads[1])
                # Non-words modules still needed when chatbox runs only words? 
                # This test calls _run_words_module directly.
                raise AssertionError(content[:200])

            get_client.return_value.chat.side_effect = dispatch
            generator = utils.Generator("German", "Chinese", "transcript about housing")
            with patch.dict("os.environ", {"MINIMAX_WORDS_BATCHES": "2"}, clear=False):
                merged = generator._run_words_module(
                    get_client.return_value, utils.TEXT_MODEL, "transcript about housing"
                )
            terms = [w["term"] for w in merged["import_words"]]
            self.assertEqual(len(terms), 16)
            self.assertEqual(len(set(terms)), 16)
            self.assertTrue(terms[0].startswith("alpha"))
            self.assertTrue(any(t.startswith("beta") for t in terms))
        finally:
            self._workers.start()

    def test_merge_word_batches_dedupes_casefold(self):
        merged = utils.Generator._merge_word_batches([
            {"import_words": [
                {"term": "Haus", "senses": [{"definition": "a", "translation": "房", "example": "x"}]},
                {"term": "Wohnen", "senses": [{"definition": "b", "translation": "住", "example": "y"}]},
            ]},
            {"import_words": [
                {"term": "haus", "senses": [{"definition": "dup", "translation": "房", "example": "z"}]},
                {"term": "Miete", "senses": [{"definition": "c", "translation": "租", "example": "w"}]},
            ]},
        ])
        terms = [w["term"] for w in merged["import_words"]]
        self.assertEqual(terms, ["Haus", "Wohnen", "Miete"])

    @patch("main_app.utils._get_client")
    def test_invalid_module_json_is_repaired(self, get_client):
        names = ("core", "words", "grammar", "listening", "expression", "translation")
        get_client.return_value.chat.side_effect = (
            ["not json", valid_module_json("core"), checker_ok()]
            + writer_then_checker(*names[1:])
        )
        generator = utils.Generator("German", "English", "transcript")
        generator.chatbox()
        # bad write + rewrite + check + 5*(write+check) = 13
        self.assertEqual(get_client.return_value.chat.call_count, 13)
        self.assertIn("response is not valid JSON", generator.message_history[2]["content"])

    @patch("main_app.utils._get_client")
    def test_checker_rejection_triggers_writer_revision(self, get_client):
        names = ("core", "words", "grammar", "listening", "expression", "translation")
        get_client.return_value.chat.side_effect = (
            [
                valid_module_json("core"),
                '{"ok": false, "errors": ["warm_up too generic"]}',
                valid_module_json("core"),
                checker_ok(),
            ]
            + writer_then_checker(*names[1:])
        )
        generator = utils.Generator("German", "English", "transcript")
        generator.chatbox()
        prompts = [c.kwargs["messages"][0]["content"] for c in get_client.return_value.chat.call_args_list]
        self.assertTrue(any("warm_up too generic" in p for p in prompts))
        self.assertTrue(any("Checker agent" in p for p in prompts))
        self.assertEqual(json.loads(generator.reply), json.loads(valid_lesson_json()))

    @patch("main_app.utils._get_client")
    def test_invalid_module_repair_raises_clear_error(self, get_client):
        get_client.return_value.chat.return_value = "{}"
        generator = utils.Generator("German", "English", "transcript")
        with self.assertRaises(utils.LearningMaterialValidationError) as raised:
            generator.chatbox()
        self.assertIn("Writer/Checker loop", str(raised.exception))
        self.assertEqual(get_client.return_value.chat.call_count, 2)

    @patch("main_app.utils._get_client")
    def test_long_transcript_summarises_before_module_calls(self, get_client):
        names = ("core", "words", "grammar", "listening", "expression", "translation")
        get_client.return_value.chat.side_effect = [
            '{"keywords": ["hello"]}',
            '{"keywords": ["world"]}',
            *writer_then_checker(*names),
        ]
        generator = utils.Generator("German", "English", "x" * 9000)
        with patch.dict(
            "os.environ",
            {"MINIMAX_AGENT_PROMPT_CHARS": "4000", "MINIMAX_AGENT_CHUNK_CHARS": "6000"},
            clear=False,
        ):
            generator.chatbox()
        calls = get_client.return_value.chat.call_args_list
        self.assertEqual(len(calls), 14)  # 2 summaries + 6 writer + 6 checker
        self.assertIn("Structured transcript summaries", calls[2].kwargs["messages"][0]["content"])
        self.assertNotIn("x" * 6000, calls[2].kwargs["messages"][0]["content"])

    @patch("main_app.utils.time.sleep")
    @patch("main_app.utils._get_client")
    def test_network_error_is_raised_after_retries_exhausted(self, get_client, sleep):
        error = httpx.RequestError("timeout")
        get_client.return_value.chat.side_effect = error
        generator = utils.Generator("German", "English", "transcript")
        with patch.dict("os.environ", {"MINIMAX_MAX_RETRIES": "2"}, clear=False):
            with self.assertRaises(httpx.RequestError) as raised:
                generator.chatbox()
        self.assertIs(raised.exception, error)
        self.assertEqual(get_client.return_value.chat.call_count, 3)
        self.assertEqual(sleep.call_args_list, [((1,),), ((2,),)])


class InternationalizationTests(TestCase):
    def setUp(self):
        from accounts.models import User
        self.user = User.objects.create_user(
            email="test@bals.dev", username="test@bals.dev", password="testpass123",
        )
        self.client.login(email="test@bals.dev", password="testpass123")

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
            "优先使用人工字幕，其次使用自动字幕；没有字幕的视频暂不支持。",
        )
        self.assertNotContains(zh, "带有 YouTube 字幕")
        self.assertNotContains(zh, "可以是人工字幕或自动字幕")
        self.assertContains(en, "Captions are preferred")
        self.assertContains(
            en,
            "We use manual captions first, then automatic captions. Videos without any captions are not supported.",
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
                "import_words": [{
                    "term": "hello",
                    "part_of_speech": "interjection",
                    "senses": [{
                        "definition": "A greeting.",
                        "translation": "你好",
                        "example": "Hello!",
                    }],
                    "note": "greeting",
                }],
                "import_grammars": [{
                    "pattern": "subject + verb",
                    "meaning": "基本句型",
                    "overview": "主语加谓语构成基本句子。",
                    "collocations": [{"phrase": "I learn", "translation": "我学习"}],
                    "forms": ["Subject + Verb"],
                    "model": {"sentence": "I learn Russian.", "translation": "我学习俄语。"},
                    "note": "Keep word order stable.",
                    "examples": [{"phrase": "I learn.", "translation": "我学习。"}],
                    "practice": {
                        "instruction": "Make a sentence:",
                        "items": [{"prompt": "用主谓结构造句。", "answer": "I learn Russian."}],
                    },
                }],
                "listening_tasks": [{
                    "type": "true_false",
                    "instruction": "判断正误：",
                    "items": [{"statement": "China cooperates with Russia.", "answer": "В"}],
                }],
            }),
            status=JOB_READY,
        )

        response = self.client.get(f"/en/learning_material/{self.video.video_id}/Chinese")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "lexicon-entry")
        self.assertContains(response, "grammar-entry")
        self.assertContains(response, "dict-lemma")
        self.assertContains(response, "【你好】")
        self.assertContains(response, "hello")
        self.assertContains(response, "subject + verb")
        self.assertContains(response, "基本句型")
        self.assertContains(response, "grammar-pair-list")
        self.assertContains(response, "I learn.")
        self.assertContains(response, "China cooperates with Russia.")
        self.assertContains(response, "判断正误")
        self.assertContains(response, "lesson-toc")
        self.assertContains(response, "lesson-card")
        self.assertContains(response, "tab-pane")
        self.assertContains(response, "word-card")
        self.assertNotContains(response, "PART_OF_SPEECH")
        self.assertNotContains(response, "part_of_speech")

        template = response.templates[0].source
        self.assertIn('{% trans "Key vocabulary" %}', template)
        self.assertIn('{% trans "Grammar" %}', template)
        self.assertIn("dict-head", template)
        self.assertIn("【{{ sense.translation }}】", template)
        self.assertIn("answer-fold", template)
        self.assertIn("Typical collocations", template)
        self.assertIn("listening_items", template)
        self.assertIn("comprehension_items", template)
        self.assertNotIn("{{ key|capfirst }}", template)

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

    def test_learning_material_export_json(self):
        Learning_Material.objects.create(
            linked_video=self.video,
            native_language="Chinese",
            material=json.dumps({
                "can_do": ["Understand the report."],
                "import_words": [{
                    "term": "hello",
                    "part_of_speech": "interjection",
                    "senses": [{"definition": "A greeting.", "translation": "你好"}],
                }],
                "listening_tasks": [{
                    "type": "true_false",
                    "instruction": "判断正误：",
                    "items": [{"statement": "China cooperates with Russia.", "answer": "В"}],
                }],
                "questions": ["What is the topic?"],
                "answers": ["Cooperation."],
            }),
            status=JOB_READY,
        )

        response = self.client.get(
            f"/en/learning_material/{self.video.video_id}/Chinese/export.json"
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["meta"]["title"], "Test video")
        self.assertTrue(payload["meta"]["answer"])
        types = {s["type"] for s in payload["sections"]}
        self.assertIn("list", types)
        self.assertIn("vocab", types)
        self.assertIn("listening", types)
        self.assertIn("qa", types)
        listening = next(s for s in payload["sections"] if s["type"] == "listening")
        self.assertEqual(listening["tasks"][0]["items"][0]["prompt"], "China cooperates with Russia.")
        self.assertEqual(listening["tasks"][0]["items"][0]["answer"], "В")

        page = self.client.get(f"/en/learning_material/{self.video.video_id}/Chinese")
        self.assertContains(page, "export.json")
        self.assertContains(page, 'data-export-url')


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
    def test_manual_captions_win_without_download(self, ydl_class, get):
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

    @patch("main_app.utils.youtube_dl.YoutubeDL")
    def test_missing_captions_raises_clear_error(self, ydl_class):
        ydl_class.return_value = self._ydl(self._info())
        with self.assertRaisesRegex(RuntimeError, "no captions available"):
            utils.Transcribe("url").audio2text()

    @patch("main_app.utils.httpx.get")
    @patch("main_app.utils.youtube_dl.YoutubeDL")
    def test_caption_http_error_raises(self, ydl_class, get):
        ydl_class.return_value = self._ydl(self._info(
            subtitles={"en": [{"ext": "json3", "url": "bad"}]}))
        get.return_value.raise_for_status.side_effect = httpx.HTTPStatusError(
            "bad", request=httpx.Request("GET", "https://x"), response=httpx.Response(500))
        with self.assertRaisesRegex(RuntimeError, "caption track"):
            utils.Transcribe("url").audio2text()

    @patch("main_app.utils.httpx.get")
    @patch("main_app.utils.youtube_dl.YoutubeDL")
    def test_empty_caption_payload_raises_error(self, ydl_class, get):
        ydl_class.return_value = self._ydl(self._info(
            subtitles={"en": [{"ext": "json3", "url": "empty"}]}))
        get.return_value.raise_for_status.return_value = None
        get.return_value.json.return_value = {"events": []}
        with self.assertRaisesRegex(RuntimeError, "no captions available"):
            utils.Transcribe("url").audio2text()

    @patch("main_app.utils.youtube_dl.YoutubeDL")
    def test_video_over_limit_is_rejected(self, ydl_class):
        ydl_class.return_value = self._ydl(self._info(duration=601))
        with self.assertRaisesRegex(ValueError, "10 minutes"):
            utils.Transcribe("url").audio2text()

    def test_broadcast_embedded_timecodes_are_split_out_of_caption_text(self):
        payload = {
            "events": [
                {
                    "tStartMs": 0,
                    "dDurationMs": 4000,
                    "segs": [{
                        "utf8": (
                            "\ufeff00:00:00:20 00:00:04:01 In vielen europäischen\n"
                            "Städten wird Wohnen zum Luxus."
                        ),
                    }],
                },
                {
                    "tStartMs": 4000,
                    "dDurationMs": 3000,
                    "segs": [{
                        "utf8": (
                            "00:00:04:12 00:00:05:19 Mieten steigen rasant,\n"
                            "00:00:05:19 00:00:08:17 Familien finden keinen"
                        ),
                    }],
                },
            ]
        }
        segments = utils._parse_caption_payload(payload)
        texts = [s["text"] for s in segments]
        self.assertEqual(
            texts,
            [
                "In vielen europäischen Städten wird Wohnen zum Luxus.",
                "Mieten steigen rasant,",
                "Familien finden keinen",
            ],
        )
        self.assertFalse(any(re.search(r"\d{2}:\d{2}:\d{2}", t) for t in texts))
        stamps = utils._text_with_timestamps(segments)
        self.assertEqual(
            stamps["0:00:00"],
            "In vielen europäischen Städten wird Wohnen zum Luxus.",
        )
        self.assertIn("Mieten steigen rasant,", stamps["0:00:04"])


# ---------------------------------------------------------------------------
# New tests: views, models, formatters
# ---------------------------------------------------------------------------

class ModelTests(TestCase):
    def test_transcribed_video_slug_generation(self):
        video = Transcribed_Video.objects.create(
            video_id="AbC123_xyz", video_language="en",
            video_title="Test", video_length=60,
        )
        self.assertEqual(video.slug, "abc123_xyz")

    def test_learning_material_slug_generation(self):
        video = Transcribed_Video.objects.create(
            video_id="abc123", video_language="en",
            video_title="Test", video_length=60,
        )
        lm = Learning_Material.objects.create(
            linked_video=video, native_language="Chinese",
        )
        self.assertEqual(lm.slug, "abc123-chinese")

    def test_learning_material_unique_constraint(self):
        video = Transcribed_Video.objects.create(
            video_id="abc123", video_language="en",
            video_title="Test", video_length=60,
        )
        Learning_Material.objects.create(linked_video=video, native_language="Chinese")
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            Learning_Material.objects.create(linked_video=video, native_language="Chinese")


@override_settings(ALLOWED_HOSTS=["testserver"])
class HomeViewTests(TestCase):
    def setUp(self):
        Transcribed_Video.objects.create(
            video_id="v1111111111", video_language="English",
            video_title="French Revolution Explained", video_length=300,
            status=JOB_READY,
        )
        Transcribed_Video.objects.create(
            video_id="v2222222222", video_language="German",
            video_title="Wohnen in Wien", video_length=240,
            status=JOB_READY,
        )

    def test_home_lists_courses(self):
        response = self.client.get("/en/")
        self.assertContains(response, "French Revolution Explained")
        self.assertContains(response, "Wohnen in Wien")

    def test_home_language_filter(self):
        response = self.client.get("/en/?language_filter=German")
        self.assertContains(response, "Wohnen in Wien")
        self.assertNotContains(response, "French Revolution")

    def test_home_search(self):
        response = self.client.get("/en/?q=French")
        self.assertContains(response, "French Revolution Explained")
        self.assertNotContains(response, "Wohnen in Wien")

    def test_home_search_no_match(self):
        response = self.client.get("/en/?q=nonexistent")
        self.assertContains(response, "No courses yet")

    def test_home_search_case_insensitive(self):
        response = self.client.get("/en/?q=french")
        self.assertContains(response, "French Revolution Explained")


@override_settings(ALLOWED_HOSTS=["testserver"])
class ViewIntegrationTests(TestCase):
    def setUp(self):
        self.video = Transcribed_Video.objects.create(
            video_id="testVideo1", video_language="en",
            video_title="Test Video", video_length=60,
            video_text='{"0:00": "Hello world."}',
            status=JOB_READY,
        )

    def test_learning_material_redirects_when_not_ready(self):
        Learning_Material.objects.create(
            linked_video=self.video, native_language="Chinese",
            status="pending",
        )
        response = self.client.get(f"/en/learning_material/{self.video.video_id}/Chinese")
        self.assertEqual(response.status_code, 302)

    def test_learning_material_export_404(self):
        response = self.client.get("/en/learning_material/nonexistent/Chinese/export.json")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"], "not_found")

    def test_learning_material_export_409_not_ready(self):
        Learning_Material.objects.create(
            linked_video=self.video, native_language="Chinese",
            status="pending",
        )
        response = self.client.get(f"/en/learning_material/{self.video.video_id}/Chinese/export.json")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"], "not_ready")

    def test_transcript_redirects_when_not_ready(self):
        pending = Transcribed_Video.objects.create(
            video_id="pendingVid", video_language="en",
            video_title="Pending", video_length=30,
            status="pending",
        )
        response = self.client.get(f"/en/transcript/{pending.slug}")
        self.assertEqual(response.status_code, 302)
        self.assertIn("wait", response.url)


class FormatterTests(TestCase):
    def test_format_lexicon_entries_english(self):
        items = views._format_lexicon_entries([{
            "term": "hello", "ipa": "/həˈləʊ/",
            "part_of_speech": "interjection", "cefr": "A1",
            "senses": [{"definition": "A greeting.", "translation": "你好", "example": "Hello!"}],
        }], "English")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["headword"], "hello")
        self.assertIn("A1", items[0]["grammar"])
        self.assertNotIn("сущ.", items[0]["grammar"])

    def test_format_lexicon_entries_russian(self):
        items = views._format_lexicon_entries([{
            "term": "дом",
            "pronunciation": {"stress_marked": "до́м"},
            "part_of_speech": "сущ.", "grammatical_info": {"gender": "masculine"},
            "senses": [{"definition": "Здание.", "translation": "房子", "example": "Это дом."}],
        }], "Russian")
        self.assertEqual(items[0]["headword"], "до́м")
        self.assertIn("сущ.", items[0]["grammar"])
        self.assertIn("м.", items[0]["grammar"])

    def test_format_lexicon_entries_german(self):
        items = views._format_lexicon_entries([{
            "term": "Haus", "pronunciation": "[haʊ̯s]",
            "part_of_speech": "Substantiv", "article": "das", "gender": "neuter",
            "senses": [{"definition": "Gebäude.", "translation": "房子", "example": "Das Haus."}],
        }], "German")
        self.assertIn("Subst.", items[0]["grammar"])
        self.assertIn("das", items[0]["grammar"])

    def test_pos_for_language_english(self):
        self.assertEqual(views._pos_for_language("noun", "English"), "n.")
        self.assertEqual(views._pos_for_language("verb", "English"), "v.")

    def test_pos_for_language_russian(self):
        self.assertEqual(views._pos_for_language("noun", "Russian"), "сущ.")

    def test_pos_for_language_german(self):
        self.assertEqual(views._pos_for_language("Substantiv", "German"), "Subst.")

    def test_pos_for_language_unknown(self):
        self.assertEqual(views._pos_for_language("noun", "French"), "noun")

    def test_split_phrase_gloss(self):
        phrase, gloss = views._split_phrase_gloss("Haus — 房子")
        self.assertEqual(phrase, "Haus")
        self.assertEqual(gloss, "房子")

    def test_split_phrase_gloss_no_sep(self):
        phrase, gloss = views._split_phrase_gloss("hello")
        self.assertEqual(phrase, "hello")
        self.assertEqual(gloss, "")

    def test_merge_word_batches(self):
        merged = utils.Generator._merge_word_batches([
            {"import_words": [{"term": "Alpha"}, {"term": "Beta"}]},
            {"import_words": [{"term": "alpha"}, {"term": "Gamma"}]},
        ])
        terms = [w["term"] for w in merged["import_words"]]
        self.assertEqual(terms, ["Alpha", "Beta", "Gamma"])

    def test_lexicon_aside_labels_english(self):
        labels = views._lexicon_aside_labels("English")
        self.assertEqual(labels["syn"], "Syn.")
        self.assertEqual(labels["ant"], "Ant.")

    def test_lexicon_aside_labels_russian(self):
        labels = views._lexicon_aside_labels("Russian")
        self.assertEqual(labels["syn"], "син.")

    def test_lexicon_aside_labels_german(self):
        labels = views._lexicon_aside_labels("German")
        self.assertEqual(labels["phrase"], "Redw.")

    def test_lexicon_aside_labels_unknown(self):
        labels = views._lexicon_aside_labels("French")
        self.assertEqual(labels["syn"], "Syn.")
