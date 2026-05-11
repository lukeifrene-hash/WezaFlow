import unittest

from services.pipeline.models import AppContext


class FakeVAD:
    def __init__(self, result):
        self.result = result
        self.last_stats = {"input_sample_count": 3, "output_sample_count": 2}

    def filter(self, audio):
        return self.result


class FakeTranscriber:
    def __init__(self, text):
        self.text = text
        self.calls = []

    def transcribe(self, audio, language=None, initial_prompt=None):
        from services.pipeline.models import AsrResult

        self.calls.append((audio, language, initial_prompt))
        return AsrResult(text=self.text, language=language, duration_ms=12)


class FakeFormatter:
    def __init__(self):
        self.calls = []

    def format(self, raw_text, app_context, vocabulary_hints=None):
        from services.pipeline.models import FormatResult

        self.calls.append((raw_text, app_context, vocabulary_hints))
        return FormatResult(text=f"polished: {raw_text}", model="fake", duration_ms=8)

    def command_edit(self, selected_text, command_text):
        from services.pipeline.models import FormatResult

        return FormatResult(text=f"{selected_text} [{command_text}]", model="fake", duration_ms=9)


class FakeInjector:
    def __init__(self):
        self.injected = []

    def inject(self, text):
        self.injected.append(text)
        return True


class FakeSnippets:
    def __init__(self, expansion=None):
        self.expansion = expansion

    def expand(self, text):
        return self.expansion


class FakeVocabularyStore:
    def formatter_hints(self):
        return ["LocalFlow", "wispr flow -> Wispr Flow"]

    def asr_hints(self):
        return "LocalFlow, Wispr Flow"


def fake_context():
    return AppContext(
        app_name="Code.exe",
        window_title="LocalFlow",
        category="code",
        browser_url=None,
        visible_text=[],
    )


class PipelineOrchestratorTests(unittest.TestCase):
    def test_process_audio_filters_transcribes_formats_and_injects(self):
        from services.pipeline.orchestrator import PipelineOrchestrator

        injector = FakeInjector()
        formatter = FakeFormatter()
        pipeline = PipelineOrchestrator(
            vad=FakeVAD(result=[0.2, 0.4]),
            transcriber=FakeTranscriber("hello world"),
            formatter=formatter,
            context_provider=fake_context,
            injector=injector,
        )

        result = pipeline.process_audio([0.0, 0.2, 0.4], language="en")

        self.assertEqual(result.raw_transcript, "hello world")
        self.assertEqual(result.polished_text, "polished: hello world")
        self.assertEqual(result.app_context.category, "code")
        self.assertEqual(injector.injected, ["polished: hello world"])
        self.assertEqual(formatter.calls[0][1].visible_text, [])

    def test_process_audio_uses_vocabulary_store_for_asr_prompt_and_formatter_hints(self):
        from services.pipeline.orchestrator import PipelineOrchestrator

        transcriber = FakeTranscriber("local flow")
        formatter = FakeFormatter()
        pipeline = PipelineOrchestrator(
            vad=FakeVAD(result=[0.2, 0.4]),
            transcriber=transcriber,
            formatter=formatter,
            context_provider=fake_context,
            injector=FakeInjector(),
            vocabulary_store=FakeVocabularyStore(),
        )

        result = pipeline.process_audio([0.2, 0.4], language="en", vocabulary_hints=["WEZZA"])

        self.assertEqual(result.raw_transcript, "local flow")
        self.assertEqual(transcriber.calls[0][2], "LocalFlow, Wispr Flow, WEZZA")
        self.assertEqual(formatter.calls[0][2], ["LocalFlow", "wispr flow -> Wispr Flow", "WEZZA"])

    def test_process_audio_reports_phase_timings(self):
        from services.pipeline.orchestrator import PipelineOrchestrator

        pipeline = PipelineOrchestrator(
            vad=FakeVAD(result=[0.2, 0.4]),
            transcriber=FakeTranscriber("hello world"),
            formatter=FakeFormatter(),
            context_provider=fake_context,
            injector=FakeInjector(),
        )

        result = pipeline.process_audio([0.0, 0.2, 0.4], language="en")

        self.assertEqual(
            set(result.timings_ms),
            {"context_ms", "vad_ms", "asr_ms", "format_ms", "inject_ms", "total_ms"},
        )
        self.assertEqual(result.timings_ms["total_ms"], result.duration_ms)
        self.assertEqual(
            result.diagnostics["vad"],
            {"input_sample_count": 3, "output_sample_count": 2},
        )

    def test_process_audio_uses_snippet_expansion_without_formatter(self):
        from services.pipeline.orchestrator import PipelineOrchestrator

        injector = FakeInjector()
        pipeline = PipelineOrchestrator(
            vad=FakeVAD(result=[0.2, 0.4]),
            transcriber=FakeTranscriber("insert my email"),
            formatter=FakeFormatter(),
            context_provider=fake_context,
            injector=injector,
            snippets=FakeSnippets(expansion="user@example.com"),
        )

        result = pipeline.process_audio([0.2, 0.4])

        self.assertEqual(result.raw_transcript, "insert my email")
        self.assertEqual(result.polished_text, "user@example.com")
        self.assertEqual(injector.injected, ["user@example.com"])

    def test_process_audio_returns_no_speech_without_injection(self):
        from services.pipeline.orchestrator import PipelineOrchestrator

        injector = FakeInjector()
        pipeline = PipelineOrchestrator(
            vad=FakeVAD(result=None),
            transcriber=FakeTranscriber("unused"),
            formatter=FakeFormatter(),
            context_provider=fake_context,
            injector=injector,
        )

        result = pipeline.process_audio([0.0, 0.0])

        self.assertIsNone(result)
        self.assertEqual(injector.injected, [])

    def test_command_mode_uses_formatter_command_edit(self):
        from services.pipeline.orchestrator import PipelineOrchestrator

        injector = FakeInjector()
        pipeline = PipelineOrchestrator(
            vad=FakeVAD(result=[0.2, 0.4]),
            transcriber=FakeTranscriber("make concise"),
            formatter=FakeFormatter(),
            context_provider=fake_context,
            injector=injector,
        )

        result = pipeline.process_command("Selected text", [0.2, 0.4])

        self.assertEqual(result.polished_text, "Selected text [make concise]")
        self.assertEqual(injector.injected, ["Selected text [make concise]"])


if __name__ == "__main__":
    unittest.main()
