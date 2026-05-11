import unittest
import threading
import time

from services.pipeline.models import AppContext, PipelineResult


def result(text="hello"):
    return PipelineResult(
        raw_transcript=text,
        polished_text=f"{text}.",
        app_context=AppContext(app_name="notepad.exe", window_title="", category="other"),
        duration_ms=123,
        timings_ms={"asr_ms": 100, "total_ms": 123},
    )


class FakeRecorder:
    def __init__(self, samples):
        self.samples = samples

    def snapshot_samples(self):
        return list(self.samples)


class FakePipeline:
    def __init__(self, pipeline_result=None):
        self.pipeline_result = pipeline_result or result()
        self.calls = []

    def process_audio(self, audio, language=None, inject=True):
        self.calls.append((audio, language, inject))
        return self.pipeline_result


class FakeLogger:
    def __init__(self):
        self.events = []

    def log(self, event, **fields):
        self.events.append((event, fields))


class BlockingPipeline:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()

    def process_audio(self, audio, language=None, inject=True):
        self.started.set()
        self.release.wait(timeout=5)
        return result("slow")


class SpeculativeTranscriptionTests(unittest.TestCase):
    def test_starts_snapshot_when_recording_has_trailing_silence(self):
        from services.runtime.speculative import SpeculativeConfig, SpeculativeTranscriptionSession

        pipeline = FakePipeline(result("early"))
        logger = FakeLogger()
        session = SpeculativeTranscriptionSession(
            pipeline=pipeline,
            recorder=FakeRecorder([0.2] * 200 + [0.0] * 200),
            logger=logger,
            config=SpeculativeConfig(
                sample_rate=1000,
                min_recording_ms=250,
                trailing_silence_ms=100,
                max_reuse_tail_ms=200,
            ),
        )

        self.assertTrue(session.maybe_start_snapshot(language="en"))
        session.wait(timeout=1)

        self.assertEqual(pipeline.calls, [([0.2] * 200 + [0.0] * 200, "en", False)])
        self.assertTrue(any(event == "speculative_asr_success" for event, _ in logger.events))

    def test_does_not_start_until_trailing_silence_is_present(self):
        from services.runtime.speculative import SpeculativeConfig, SpeculativeTranscriptionSession

        pipeline = FakePipeline()
        session = SpeculativeTranscriptionSession(
            pipeline=pipeline,
            recorder=FakeRecorder([0.2] * 400),
            logger=FakeLogger(),
            config=SpeculativeConfig(
                sample_rate=1000,
                min_recording_ms=250,
                trailing_silence_ms=100,
                max_reuse_tail_ms=200,
            ),
        )

        self.assertFalse(session.maybe_start_snapshot(language="en"))
        self.assertEqual(pipeline.calls, [])

    def test_reuses_finished_result_when_final_tail_is_silent(self):
        from services.runtime.speculative import SpeculativeConfig, SpeculativeTranscriptionSession

        pipeline = FakePipeline(result("ready"))
        session = SpeculativeTranscriptionSession(
            pipeline=pipeline,
            recorder=FakeRecorder([0.2] * 200 + [0.0] * 200),
            logger=FakeLogger(),
            config=SpeculativeConfig(
                sample_rate=1000,
                min_recording_ms=250,
                trailing_silence_ms=100,
                max_reuse_tail_ms=200,
            ),
        )

        session.maybe_start_snapshot(language="en")
        reused, fields = session.stop([0.2] * 200 + [0.0] * 250)

        self.assertEqual(reused.raw_transcript, "ready")
        self.assertTrue(fields["speculative_reused"])
        self.assertEqual(fields["speculative_snapshot_sample_count"], 400)

    def test_discards_finished_result_when_new_speech_arrives_after_snapshot(self):
        from services.runtime.speculative import SpeculativeConfig, SpeculativeTranscriptionSession

        pipeline = FakePipeline(result("early"))
        session = SpeculativeTranscriptionSession(
            pipeline=pipeline,
            recorder=FakeRecorder([0.2] * 200 + [0.0] * 200),
            logger=FakeLogger(),
            config=SpeculativeConfig(
                sample_rate=1000,
                min_recording_ms=250,
                trailing_silence_ms=100,
                max_reuse_tail_ms=200,
            ),
        )

        session.maybe_start_snapshot(language="en")
        reused, fields = session.stop([0.2] * 200 + [0.0] * 200 + [0.2])

        self.assertIsNone(reused)
        self.assertFalse(fields["speculative_reused"])

    def test_default_reuse_rejects_long_unprocessed_tail(self):
        from services.runtime.speculative import SpeculativeConfig, SpeculativeTranscriptionSession

        pipeline = FakePipeline(result("early"))
        session = SpeculativeTranscriptionSession(
            pipeline=pipeline,
            recorder=FakeRecorder([0.2] * 500 + [0.0] * 1500),
            logger=FakeLogger(),
            config=SpeculativeConfig(sample_rate=1000),
        )

        session.maybe_start_snapshot(language="en")
        session.wait(timeout=1)
        reused, fields = session.stop([0.2] * 500 + [0.0] * 2100)

        self.assertIsNone(reused)
        self.assertFalse(fields["speculative_reused"])
        self.assertEqual(fields["speculative_status"], "discarded_new_tail")

    def test_stop_does_not_wait_for_unfinished_speculative_result(self):
        from services.runtime.speculative import SpeculativeConfig, SpeculativeTranscriptionSession

        pipeline = BlockingPipeline()
        session = SpeculativeTranscriptionSession(
            pipeline=pipeline,
            recorder=FakeRecorder([0.2] * 200 + [0.0] * 200),
            logger=FakeLogger(),
            config=SpeculativeConfig(
                sample_rate=1000,
                min_recording_ms=250,
                trailing_silence_ms=100,
                max_reuse_tail_ms=200,
            ),
        )

        session.maybe_start_snapshot(language="en")
        self.assertTrue(pipeline.started.wait(timeout=1))
        started = time.perf_counter()
        reused, fields = session.stop([0.2] * 200 + [0.0] * 250)
        elapsed = time.perf_counter() - started
        pipeline.release.set()

        self.assertIsNone(reused)
        self.assertLess(elapsed, 0.5)
        self.assertEqual(fields["speculative_status"], "pending")


if __name__ == "__main__":
    unittest.main()
