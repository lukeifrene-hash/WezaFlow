import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from services.pipeline.models import AppContext, FormatResult


def app_context(category="work_chat"):
    return AppContext(
        app_name="Slack.exe",
        window_title="LocalFlow standup",
        category=category,
        browser_url=None,
        visible_text=[],
    )


class TextFormatterTests(unittest.TestCase):
    def test_format_uses_deterministic_fallback_for_fillers_corrections_and_punctuation(self):
        from services.llm.formatter import TextFormatter

        formatter = TextFormatter(backend=None)

        result = formatter.format(
            "um we need the budget to be 50k actually make that 75k",
            app_context(),
            vocabulary_hints=["LocalFlow"],
        )

        self.assertIsInstance(result, FormatResult)
        self.assertEqual(result.model, "local-fallback")
        self.assertEqual(result.text, "We need the budget to be 75k.")
        self.assertGreaterEqual(result.duration_ms, 0)

    def test_format_uses_injected_backend_when_available(self):
        from services.llm.formatter import TextFormatter

        class Backend:
            model = "fake-ollama"

            def format(self, raw_text, app_context, vocabulary_hints=None):
                self.seen = (raw_text, app_context, vocabulary_hints)
                return "backend text"

        backend = Backend()
        formatter = TextFormatter(backend=backend)

        result = formatter.format("hello", app_context(), vocabulary_hints=["WEZZA"])

        self.assertEqual(result.text, "backend text")
        self.assertEqual(result.model, "fake-ollama")
        self.assertEqual(backend.seen[0], "hello")
        self.assertEqual(backend.seen[2], ["WEZZA"])

    def test_format_handles_inline_actually_make_that_corrections(self):
        from services.llm.formatter import TextFormatter

        formatter = TextFormatter(backend=None)

        result = formatter.format("let's budget 50k, actually make that 75k", app_context())

        self.assertEqual(result.text, "Let's budget 75k.")

    def test_format_converts_spoken_punctuation_and_line_breaks(self):
        from services.llm.formatter import TextFormatter

        formatter = TextFormatter(backend=None)

        result = formatter.format(
            "hello comma team period newline are we ready question mark new paragraph thanks new line bye full stop",
            app_context("email"),
        )

        self.assertEqual(result.text, "Hello, team.\nAre we ready?\n\nThanks\nBye.")

    def test_format_resolves_spoken_self_corrections(self):
        from services.llm.formatter import TextFormatter

        formatter = TextFormatter(backend=None)

        cases = {
            "send it wait no cancel it": "Cancel it.",
            "ship the first draft scratch that ship the final draft": "Ship the final draft.",
            "tell sam actually tell dana": "Tell dana.",
            "tell sam sorry I meant tell dana": "Tell dana.",
            "the meeting is at three sorry, I meant four": "Four.",
            "set amount to forty no make that fifty K": "Set amount to 50k.",
        }

        for raw_text, expected_text in cases.items():
            with self.subTest(raw_text=raw_text):
                self.assertEqual(formatter.format(raw_text, app_context()).text, expected_text)

    def test_format_preserves_non_correction_actually(self):
        from services.llm.formatter import TextFormatter

        formatter = TextFormatter(backend=None)

        cases = {
            "i actually think this is fine": "I actually think this is fine.",
            "this actually works": "This actually works.",
            "i actually enjoyed it": "I actually enjoyed it.",
            "that is actually quite good": "That is actually quite good.",
        }

        for raw_text, expected_text in cases.items():
            with self.subTest(raw_text=raw_text):
                self.assertEqual(formatter.format(raw_text, app_context()).text, expected_text)

    def test_format_preserves_non_filler_like(self):
        from services.llm.formatter import TextFormatter

        formatter = TextFormatter(backend=None)

        cases = {
            "i like this": "I like this.",
            "i would like to go": "I would like to go.",
            "like we should go": "We should go.",
        }

        for raw_text, expected_text in cases.items():
            with self.subTest(raw_text=raw_text):
                self.assertEqual(formatter.format(raw_text, app_context()).text, expected_text)

    def test_format_normalizes_common_spoken_numbers(self):
        from services.llm.formatter import TextFormatter

        formatter = TextFormatter(backend=None)

        result = formatter.format("schedule it for three thirty with a fifty K budget", app_context())

        self.assertEqual(result.text, "Schedule it for 3:30 with a 50k budget.")

    def test_format_uses_minimal_cleanup_for_code_context(self):
        from services.llm.formatter import TextFormatter

        formatter = TextFormatter(backend=None)

        result = formatter.format("um return local flow period", app_context("code"), vocabulary_hints=["LocalFlow"])

        self.assertEqual(result.text, "um return LocalFlow.")

    def test_format_applies_vocabulary_hints_to_proper_nouns(self):
        from services.llm.formatter import TextFormatter

        formatter = TextFormatter(backend=None)

        result = formatter.format(
            "use local flow with wispr flow",
            app_context(),
            vocabulary_hints=["LocalFlow", "Wispr Flow"],
        )

        self.assertEqual(result.text, "Use LocalFlow with Wispr Flow.")

    def test_command_edit_supports_deterministic_fallback_commands(self):
        from services.llm.formatter import TextFormatter

        formatter = TextFormatter(backend=None)

        self.assertEqual(
            formatter.command_edit("This is a very long sentence that should shrink.", "make concise").text,
            "This is a long sentence that should shrink.",
        )
        self.assertEqual(
            formatter.command_edit("one two three", "turn into bullet list").text,
            "- one\n- two\n- three",
        )
        self.assertEqual(formatter.command_edit("Mixed Case", "uppercase").text, "MIXED CASE")
        self.assertEqual(formatter.command_edit("Mixed Case", "lowercase").text, "mixed case")
        self.assertEqual(
            formatter.command_edit("This is basically a very rough draft.", "rewrite lightly").text,
            "This is a rough draft.",
        )

    def test_ollama_prompt_includes_safe_app_context(self):
        from services.llm.formatter import OllamaBackend

        posts = []

        class Response:
            def raise_for_status(self):
                pass

            def json(self):
                return {"response": "polished"}

        class FakeHttpx:
            @staticmethod
            def post(url, json, timeout):
                posts.append({"url": url, "json": json, "timeout": timeout})
                return Response()

        original_httpx = sys.modules.get("httpx")
        sys.modules["httpx"] = FakeHttpx
        try:
            backend = OllamaBackend()
            backend.format(
                "hello",
                AppContext(
                    app_name="chrome.exe",
                    window_title="Gmail",
                    category="email",
                    browser_url="https://mail.google.com/mail/u/0/#inbox",
                    visible_text=["Thread about LocalFlow", "Reply box"],
                ),
                vocabulary_hints=["LocalFlow"],
            )
        finally:
            if original_httpx is None:
                sys.modules.pop("httpx", None)
            else:
                sys.modules["httpx"] = original_httpx

        prompt = posts[0]["json"]["prompt"]
        self.assertIn("Browser URL: https://mail.google.com/mail/u/0/#inbox.", prompt)
        self.assertIn("Visible text: Thread about LocalFlow | Reply box.", prompt)


class SnippetEngineTests(unittest.TestCase):
    def test_expands_exact_trigger_phrases_case_insensitively_from_mapping(self):
        from services.snippets.engine import SnippetEngine

        engine = SnippetEngine({"Insert My Email": "user@example.com"})

        self.assertEqual(engine.expand("insert my email"), "user@example.com")
        self.assertEqual(engine.expand(" INSERT MY EMAIL "), "user@example.com")
        self.assertIsNone(engine.expand("please insert my email"))

    def test_loads_snippets_from_list_of_records(self):
        from services.snippets.engine import SnippetEngine

        engine = SnippetEngine(
            [
                {"trigger_phrase": "sign off", "expansion": "Best,\nAda"},
                {"trigger": "phone", "text": "+1 555 0100"},
            ]
        )

        self.assertEqual(engine.expand("SIGN OFF"), "Best,\nAda")
        self.assertEqual(engine.expand("phone"), "+1 555 0100")


class VocabularyStoreTests(unittest.TestCase):
    def test_add_word_increments_frequency_and_lists_vocabulary(self):
        from services.vocabulary.store import VocabularyStore

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "localflow.db"
            store = VocabularyStore(db_path)

            store.add_word("LocalFlow")
            store.add_word("localflow")
            store.add_word("WEZZA")

            rows = store.list_vocabulary()

        self.assertEqual(
            rows,
            [
                {"word": "localflow", "frequency": 2},
                {"word": "wezza", "frequency": 1},
            ],
        )

    def test_record_correction_increments_count(self):
        from services.vocabulary.store import VocabularyStore

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "localflow.db"
            store = VocabularyStore(db_path)

            store.record_correction("weather", "whether")
            store.record_correction("weather", "whether")

            connection = sqlite3.connect(db_path)
            try:
                row = connection.execute(
                    "SELECT original, corrected, count FROM corrections"
                ).fetchone()
            finally:
                connection.close()

        self.assertEqual(row, ("weather", "whether", 2))

    def test_list_correction_pairs_orders_by_count(self):
        from services.vocabulary.store import VocabularyStore

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "localflow.db"
            store = VocabularyStore(db_path)

            store.record_correction("local flow", "LocalFlow")
            store.record_correction("weather", "whether")
            store.record_correction("local flow", "LocalFlow")

            rows = store.list_correction_pairs()

        self.assertEqual(
            rows,
            [
                {"original": "local flow", "corrected": "LocalFlow", "count": 2},
                {"original": "weather", "corrected": "whether", "count": 1},
            ],
        )

    def test_hint_strings_preserve_new_vocabulary_casing(self):
        from services.vocabulary.store import VocabularyStore

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "localflow.db"
            store = VocabularyStore(db_path)

            store.add_word("LocalFlow")
            store.add_word("localflow")
            store.add_word("Wispr Flow")
            store.record_correction("local flow", "LocalFlow")
            store.record_correction("wispr flow", "Wispr Flow")

            vocabulary_rows = store.list_vocabulary()
            formatter_hints = store.formatter_hints()
            asr_hints = store.asr_hints()

        self.assertEqual(
            vocabulary_rows,
            [
                {"word": "localflow", "frequency": 2},
                {"word": "wispr flow", "frequency": 1},
            ],
        )
        self.assertEqual(
            formatter_hints,
            ["LocalFlow", "Wispr Flow", "local flow -> LocalFlow", "wispr flow -> Wispr Flow"],
        )
        self.assertEqual(asr_hints, "LocalFlow, Wispr Flow")


if __name__ == "__main__":
    unittest.main()
