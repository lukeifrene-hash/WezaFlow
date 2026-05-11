import unittest
from pathlib import Path

from services.pipeline.models import AppContext, AsrResult, FormatResult


class FakeVAD:
    def filter(self, audio):
        return audio


class FakeTranscriber:
    def __init__(self, text):
        self.text = text

    def transcribe(self, audio, language=None, initial_prompt=None):
        return AsrResult(text=self.text, language=language, duration_ms=1)


class FakeFormatter:
    def format(self, raw_text, app_context, vocabulary_hints=None):
        return FormatResult(text=f"formatted {raw_text}", model="fake", duration_ms=1)

    def command_edit(self, selected_text, command_text):
        return FormatResult(text=selected_text, model="fake", duration_ms=1)


class FakeInjector:
    def __init__(self):
        self.injected = []

    def inject(self, text):
        self.injected.append(text)


def fake_context():
    return AppContext(
        app_name="Code.exe",
        window_title="LocalFlow",
        category="code",
        browser_url=None,
        visible_text=[],
    )


class PipelineFactoryTests(unittest.TestCase):
    def test_build_pipeline_loads_configured_snippets(self):
        from services.pipeline.factory import build_pipeline

        injector = FakeInjector()
        pipeline = build_pipeline(
            root=Path(__file__).resolve().parents[1],
            vad=FakeVAD(),
            transcriber=FakeTranscriber("insert my email"),
            formatter=FakeFormatter(),
            context_provider=fake_context,
            injector=injector,
        )

        result = pipeline.process_audio([0.1, 0.2])

        self.assertEqual(result.polished_text, "user@example.com")
        self.assertEqual(injector.injected, ["user@example.com"])

    def test_build_pipeline_wires_vocabulary_store_from_repo_db(self):
        from services.pipeline.factory import build_pipeline
        from services.vocabulary.store import VocabularyStore

        pipeline = build_pipeline(
            root=Path(__file__).resolve().parents[1],
            vad=FakeVAD(),
            transcriber=FakeTranscriber("hello"),
            formatter=FakeFormatter(),
            context_provider=fake_context,
            injector=FakeInjector(),
        )

        self.assertIsInstance(pipeline.vocabulary_store, VocabularyStore)
        self.assertEqual(pipeline.vocabulary_store.db_path.name, "localflow.db")

    def test_load_snippet_records_accepts_simple_yaml_without_pyyaml(self):
        from services.pipeline.factory import load_snippet_records

        records = load_snippet_records(
            Path(__file__).resolve().parents[1] / "config" / "snippets.yaml"
        )

        self.assertEqual(
            [{"trigger_phrase": "insert my email", "expansion": "user@example.com"}],
            records,
        )

    def test_build_pipeline_uses_microphone_sane_vad_threshold(self):
        from services.pipeline.factory import build_pipeline

        pipeline = build_pipeline(
            root=Path(__file__).resolve().parents[1],
            transcriber=FakeTranscriber("hello"),
            formatter=FakeFormatter(),
            context_provider=fake_context,
            injector=FakeInjector(),
        )

        self.assertLessEqual(pipeline.vad.threshold, 0.05)

    def test_build_pipeline_quiet_mode_lowers_vad_threshold_and_preserves_padding(self):
        from services.pipeline.factory import build_pipeline

        normal = build_pipeline(
            root=Path(__file__).resolve().parents[1],
            transcriber=FakeTranscriber("hello"),
            formatter=FakeFormatter(),
            context_provider=fake_context,
            injector=FakeInjector(),
        )
        quiet = build_pipeline(
            root=Path(__file__).resolve().parents[1],
            transcriber=FakeTranscriber("hello"),
            formatter=FakeFormatter(),
            context_provider=fake_context,
            injector=FakeInjector(),
            quiet_mode=True,
        )

        self.assertLess(quiet.vad.threshold, normal.vad.threshold)
        self.assertLess(quiet.vad.trim_threshold, normal.vad.trim_threshold)
        self.assertGreaterEqual(quiet.vad.trim_padding_ms, normal.vad.trim_padding_ms)

    def test_build_pipeline_defaults_to_low_impact_whisper_settings(self):
        import services.pipeline.factory as factory_module

        original_transcriber = factory_module.Transcriber

        class CapturingTranscriber(FakeTranscriber):
            instances = []

            def __init__(self, *args, **kwargs):
                super().__init__("hello")
                self.args = args
                self.kwargs = kwargs
                CapturingTranscriber.instances.append(self)

        factory_module.Transcriber = CapturingTranscriber
        try:
            pipeline = factory_module.build_pipeline(
                root=Path(__file__).resolve().parents[1],
                vad=FakeVAD(),
                formatter=FakeFormatter(),
                context_provider=fake_context,
                injector=FakeInjector(),
            )
        finally:
            factory_module.Transcriber = original_transcriber

        self.assertIs(pipeline.transcriber, CapturingTranscriber.instances[0])
        self.assertEqual(CapturingTranscriber.instances[0].kwargs["model_name"], "small.en")
        self.assertEqual(CapturingTranscriber.instances[0].kwargs["cpu_threads"], 2)

    def test_build_pipeline_accepts_whisper_cpu_thread_override(self):
        import services.pipeline.factory as factory_module

        original_transcriber = factory_module.Transcriber

        class CapturingTranscriber(FakeTranscriber):
            instances = []

            def __init__(self, *args, **kwargs):
                super().__init__("hello")
                self.kwargs = kwargs
                CapturingTranscriber.instances.append(self)

        factory_module.Transcriber = CapturingTranscriber
        try:
            factory_module.build_pipeline(
                root=Path(__file__).resolve().parents[1],
                vad=FakeVAD(),
                formatter=FakeFormatter(),
                context_provider=fake_context,
                injector=FakeInjector(),
                whisper_cpu_threads=2,
            )
        finally:
            factory_module.Transcriber = original_transcriber

        self.assertEqual(CapturingTranscriber.instances[0].kwargs["cpu_threads"], 2)

    def test_build_pipeline_accepts_whisper_model_and_compute_overrides(self):
        import services.pipeline.factory as factory_module

        original_transcriber = factory_module.Transcriber

        class CapturingTranscriber(FakeTranscriber):
            instances = []

            def __init__(self, *args, **kwargs):
                super().__init__("hello")
                self.kwargs = kwargs
                CapturingTranscriber.instances.append(self)

        factory_module.Transcriber = CapturingTranscriber
        try:
            factory_module.build_pipeline(
                root=Path(__file__).resolve().parents[1],
                vad=FakeVAD(),
                formatter=FakeFormatter(),
                context_provider=fake_context,
                injector=FakeInjector(),
                whisper_model_name="small.en",
                whisper_compute_type="int8",
                whisper_cpu_threads=4,
            )
        finally:
            factory_module.Transcriber = original_transcriber

        self.assertEqual(CapturingTranscriber.instances[0].kwargs["model_name"], "small.en")
        self.assertEqual(CapturingTranscriber.instances[0].kwargs["compute_type"], "int8")
        self.assertEqual(CapturingTranscriber.instances[0].kwargs["cpu_threads"], 4)


if __name__ == "__main__":
    unittest.main()
