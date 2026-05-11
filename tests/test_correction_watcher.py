import unittest


class Clock:
    def __init__(self, value=1000.0):
        self.value = value

    def now(self):
        return self.value


class ContextProvider:
    def __init__(self, context):
        self.context = context

    def __call__(self):
        return self.context


class CorrectionWatcherTests(unittest.TestCase):
    def test_edit_key_in_same_window_creates_pending_candidate(self):
        from services.pipeline.models import AppContext, PipelineResult
        from services.runtime.correction_watcher import CorrectionWatcher

        context = AppContext(app_name="notepad.exe", window_title="Untitled", category="other")
        clock = Clock()
        watcher = CorrectionWatcher(
            context_provider=ContextProvider(context),
            now=clock.now,
            id_factory=lambda: "candidate-1",
        )
        result = PipelineResult(
            raw_transcript="helo world",
            polished_text="Hello world",
            app_context=context,
            duration_ms=50,
        )

        watcher.start(result)
        candidate = watcher.observe_key("backspace")

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.id, "candidate-1")
        self.assertEqual(candidate.original, "Hello world")
        self.assertEqual(candidate.raw_transcript, "helo world")
        self.assertEqual(candidate.app_name, "notepad.exe")
        self.assertEqual(candidate.window_title, "Untitled")
        self.assertEqual(candidate.detected_at, 1000.0)
        self.assertEqual(watcher.list_pending(), [candidate])

    def test_printable_character_is_edit_like_but_modifier_key_is_ignored(self):
        from services.pipeline.models import AppContext, PipelineResult
        from services.runtime.correction_watcher import CorrectionWatcher

        context = AppContext(app_name="Notes", window_title="Draft", category="other")
        watcher = CorrectionWatcher(
            context_provider=ContextProvider(context),
            now=lambda: 10.0,
            id_factory=lambda: "candidate-1",
        )
        watcher.start(
            PipelineResult(
                raw_transcript="raw",
                polished_text="polished",
                app_context=context,
                duration_ms=1,
            )
        )

        self.assertIsNone(watcher.observe_key("ctrl"))
        candidate = watcher.observe_key("x")

        self.assertIsNotNone(candidate)
        self.assertEqual(len(watcher.list_pending()), 1)

    def test_window_mismatch_or_expired_watch_does_not_create_candidate(self):
        from services.pipeline.models import AppContext, PipelineResult
        from services.runtime.correction_watcher import CorrectionWatcher

        original = AppContext(app_name="notepad.exe", window_title="Untitled", category="other")
        current = ContextProvider(
            AppContext(app_name="chrome.exe", window_title="Search", category="browser")
        )
        clock = Clock()
        watcher = CorrectionWatcher(
            context_provider=current,
            now=clock.now,
            id_factory=lambda: "candidate-1",
            window_seconds=30,
        )
        result = PipelineResult(
            raw_transcript="hello",
            polished_text="Hello",
            app_context=original,
            duration_ms=1,
        )

        watcher.start(result)
        self.assertIsNone(watcher.observe_key("delete"))

        current.context = original
        clock.value += 31
        self.assertIsNone(watcher.observe_key("delete"))
        self.assertEqual(watcher.list_pending(), [])

    def test_start_ignores_incomplete_results_and_does_not_store_typed_key(self):
        from services.pipeline.models import AppContext, PipelineResult
        from services.runtime.correction_watcher import CorrectionWatcher

        context = AppContext(app_name="notepad.exe", window_title="Untitled", category="other")
        watcher = CorrectionWatcher(
            context_provider=ContextProvider(context),
            now=lambda: 20.0,
            id_factory=lambda: "candidate-1",
        )

        watcher.start(object())
        self.assertIsNone(watcher.observe_key("a"))

        watcher.start(
            PipelineResult(
                raw_transcript="hello",
                polished_text="Hello",
                app_context=context,
                duration_ms=1,
            )
        )
        candidate = watcher.observe_key("a")

        self.assertFalse(hasattr(candidate, "typed_text"))
        self.assertNotIn("a", candidate.__dict__.values())

    def test_confirm_and_dismiss_remove_pending_candidate(self):
        from services.pipeline.models import AppContext, PipelineResult
        from services.runtime.correction_watcher import CorrectionWatcher

        context = AppContext(app_name="notepad.exe", window_title="Untitled", category="other")
        ids = iter(["one", "two"])
        watcher = CorrectionWatcher(
            context_provider=ContextProvider(context),
            now=lambda: 30.0,
            id_factory=lambda: next(ids),
        )

        watcher.start(
            PipelineResult(
                raw_transcript="hello",
                polished_text="Hello",
                app_context=context,
                duration_ms=1,
            )
        )
        first = watcher.observe_key("enter")
        self.assertIs(watcher.confirm(first.id), first)
        self.assertEqual(watcher.list_pending(), [])

        watcher.start(
            PipelineResult(
                raw_transcript="bye",
                polished_text="Bye",
                app_context=context,
                duration_ms=1,
            )
        )
        second = watcher.observe_key("space")
        self.assertIs(watcher.dismiss(second.id), second)
        self.assertEqual(watcher.list_pending(), [])

    def test_each_started_watch_can_create_one_pending_candidate(self):
        from services.pipeline.models import AppContext, PipelineResult
        from services.runtime.correction_watcher import CorrectionWatcher

        context = AppContext(app_name="notepad.exe", window_title="Untitled", category="other")
        ids = iter(["one", "two"])
        watcher = CorrectionWatcher(
            context_provider=ContextProvider(context),
            now=lambda: 40.0,
            id_factory=lambda: next(ids),
        )

        watcher.start(
            PipelineResult(
                raw_transcript="helo",
                polished_text="Hello",
                app_context=context,
                duration_ms=1,
            )
        )
        first = watcher.observe_key("backspace")
        self.assertIsNone(watcher.observe_key("delete"))

        watcher.start(
            PipelineResult(
                raw_transcript="wurld",
                polished_text="World",
                app_context=context,
                duration_ms=1,
            )
        )
        second = watcher.observe_key("space")

        self.assertEqual([candidate.id for candidate in watcher.list_pending()], ["one", "two"])
        self.assertIs(first, watcher.list_pending()[0])
        self.assertIs(second, watcher.list_pending()[1])

    def test_confirm_pending_and_dismiss_pending_alias_api_methods(self):
        from services.pipeline.models import AppContext, PipelineResult
        from services.runtime.correction_watcher import CorrectionWatcher

        context = AppContext(app_name="notepad.exe", window_title="Untitled", category="other")
        ids = iter(["one", "two"])
        watcher = CorrectionWatcher(
            context_provider=ContextProvider(context),
            now=lambda: 30.0,
            id_factory=lambda: next(ids),
        )

        watcher.start(
            PipelineResult(
                raw_transcript="hello",
                polished_text="Hello",
                app_context=context,
                duration_ms=1,
            )
        )
        first = watcher.observe_key("enter")
        self.assertIs(watcher.confirm_pending(first.id), first)

        watcher.start(
            PipelineResult(
                raw_transcript="bye",
                polished_text="Bye",
                app_context=context,
                duration_ms=1,
            )
        )
        second = watcher.observe_key("space")
        self.assertIs(watcher.dismiss_pending(second.id), second)


if __name__ == "__main__":
    unittest.main()
