import unittest


class FakeRecorder:
    def __init__(self, audio=None):
        if audio is None:
            audio = [0.1]
        self.audio = audio
        self.started = 0
        self.stopped = 0

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1
        return self.audio


class FakePipeline:
    def __init__(self, result="result", error=None):
        self.result = result
        self.error = error
        self.calls = []
        self.command_calls = []
        self.injected = []

    def process_audio(self, audio, language=None):
        self.calls.append((audio, language))
        if self.error:
            raise self.error
        return self.result

    def process_command(self, selected_text, audio, language=None):
        self.command_calls.append((selected_text, audio, language))
        if self.error:
            raise self.error
        return self.result

    def inject_result(self, result):
        self.injected.append(result.polished_text)


class FakeStatus:
    def __init__(self):
        self.events = []

    def recording(self):
        self.events.append("recording")

    def processing(self):
        self.events.append("processing")

    def success(self, result):
        self.events.append(("success", result))

    def no_speech(self):
        self.events.append("no_speech")

    def error(self, error):
        self.events.append(("error", str(error)))

    def idle(self):
        self.events.append("idle")


class FakeLogger:
    def __init__(self):
        self.events = []

    def log(self, event, **fields):
        self.events.append((event, fields))


class FakeSpeculative:
    def __init__(self, result=None, fields=None):
        self.result = result
        self.fields = fields or {"speculative_reused": result is not None}
        self.started = []
        self.stopped_with = []
        self.cancelled = 0

    def start(self, *, language=None):
        self.started.append(language)

    def stop(self, audio):
        self.stopped_with.append(audio)
        return self.result, self.fields

    def cancel(self):
        self.cancelled += 1


class FakeCorrectionWatcher:
    def __init__(self):
        self.started = []

    def start(self, result):
        self.started.append(result)


class RuntimeSessionTests(unittest.TestCase):
    def test_start_recording_is_idempotent_while_recording(self):
        from services.runtime.session import RuntimeSession, RuntimeState

        recorder = FakeRecorder()
        session = RuntimeSession(
            recorder_factory=lambda: recorder,
            pipeline=FakePipeline(),
            status=FakeStatus(),
            logger=FakeLogger(),
        )

        self.assertTrue(session.start_recording())
        self.assertFalse(session.start_recording())

        self.assertEqual(session.state, RuntimeState.RECORDING)
        self.assertEqual(recorder.started, 1)

    def test_stop_and_process_calls_pipeline_once_and_returns_to_idle(self):
        from services.runtime.session import RuntimeSession, RuntimeState

        recorder = FakeRecorder(audio=[0.1, 0.2])
        pipeline = FakePipeline(result="ok")
        status = FakeStatus()
        logger = FakeLogger()
        session = RuntimeSession(
            recorder_factory=lambda: recorder,
            pipeline=pipeline,
            status=status,
            logger=logger,
        )

        session.start_recording()
        result = session.stop_and_process(language="en")

        self.assertEqual(result, "ok")
        self.assertEqual(session.state, RuntimeState.IDLE)
        self.assertEqual(recorder.stopped, 1)
        self.assertEqual(pipeline.calls, [([0.1, 0.2], "en")])
        self.assertIn(("success", "ok"), status.events)
        self.assertEqual(logger.events[-1][0], "dictation_success")

    def test_command_recording_reads_selection_and_processes_command(self):
        from services.runtime.session import RuntimeSession, RuntimeState

        recorder = FakeRecorder(audio=[0.4])
        pipeline = FakePipeline(result="edited")
        logger = FakeLogger()
        session = RuntimeSession(
            recorder_factory=lambda: recorder,
            pipeline=pipeline,
            status=FakeStatus(),
            logger=logger,
            selection_reader=lambda: "Selected text",
        )

        self.assertTrue(session.start_command_recording(language="en"))
        result = session.stop_and_process(language="en")

        self.assertEqual(result, "edited")
        self.assertEqual(session.state, RuntimeState.IDLE)
        self.assertEqual(pipeline.calls, [])
        self.assertEqual(pipeline.command_calls, [("Selected text", [0.4], "en")])
        self.assertEqual(logger.events[-1][0], "command_success")

    def test_command_recording_does_not_start_without_selected_text(self):
        from services.runtime.session import RuntimeSession, RuntimeState

        recorder = FakeRecorder(audio=[0.4])
        logger = FakeLogger()
        session = RuntimeSession(
            recorder_factory=lambda: recorder,
            pipeline=FakePipeline(result="edited"),
            status=FakeStatus(),
            logger=logger,
            selection_reader=lambda: "",
        )

        self.assertFalse(session.start_command_recording(language="en"))

        self.assertEqual(session.state, RuntimeState.IDLE)
        self.assertEqual(recorder.started, 0)
        self.assertEqual(logger.events[-1][0], "command_no_selection")

    def test_start_recording_starts_speculative_transcription_with_language(self):
        from services.runtime.session import RuntimeSession

        speculative = FakeSpeculative()
        session = RuntimeSession(
            recorder_factory=lambda: FakeRecorder(),
            pipeline=FakePipeline(),
            status=FakeStatus(),
            logger=FakeLogger(),
            speculative_factory=lambda recorder, pipeline, logger: speculative,
        )

        session.start_recording(language="en")

        self.assertEqual(speculative.started, ["en"])

    def test_stop_and_process_reuses_speculative_result_without_reprocessing(self):
        from services.pipeline.models import AppContext, PipelineResult
        from services.runtime.session import RuntimeSession

        speculative_result = PipelineResult(
            raw_transcript="hello",
            polished_text="Hello.",
            app_context=AppContext(app_name="notepad.exe", window_title="", category="other"),
            duration_ms=100,
        )
        speculative = FakeSpeculative(
            result=speculative_result,
            fields={"speculative_reused": True, "speculative_wait_ms": 4},
        )
        pipeline = FakePipeline(result="should not reprocess")
        logger = FakeLogger()
        session = RuntimeSession(
            recorder_factory=lambda: FakeRecorder(audio=[0.0, 0.2]),
            pipeline=pipeline,
            status=FakeStatus(),
            logger=logger,
            speculative_factory=lambda recorder, pipeline, logger: speculative,
        )

        session.start_recording(language="en")
        result = session.stop_and_process(language="en")

        self.assertIs(result, speculative_result)
        self.assertEqual(pipeline.calls, [])
        self.assertEqual(pipeline.injected, ["Hello."])
        self.assertTrue(logger.events[-1][1]["speculative_reused"])

    def test_successful_dictation_starts_correction_watcher(self):
        from services.pipeline.models import AppContext, PipelineResult
        from services.runtime.session import RuntimeSession

        result = PipelineResult(
            raw_transcript="hello",
            polished_text="Hello.",
            app_context=AppContext(app_name="notepad.exe", window_title="", category="other"),
            duration_ms=100,
        )
        watcher = FakeCorrectionWatcher()
        session = RuntimeSession(
            recorder_factory=lambda: FakeRecorder(),
            pipeline=FakePipeline(result=result),
            status=FakeStatus(),
            logger=FakeLogger(),
            correction_watcher=watcher,
        )

        session.start_recording(language="en")
        session.stop_and_process(language="en")

        self.assertEqual(watcher.started, [result])

    def test_command_success_does_not_start_correction_watcher(self):
        from services.pipeline.models import AppContext, PipelineResult
        from services.runtime.session import RuntimeSession

        result = PipelineResult(
            raw_transcript="make it shorter",
            polished_text="Edited text.",
            app_context=AppContext(app_name="notepad.exe", window_title="", category="other"),
            duration_ms=100,
        )
        watcher = FakeCorrectionWatcher()
        session = RuntimeSession(
            recorder_factory=lambda: FakeRecorder(),
            pipeline=FakePipeline(result=result),
            status=FakeStatus(),
            logger=FakeLogger(),
            selection_reader=lambda: "Selected text",
            correction_watcher=watcher,
        )

        session.start_command_recording(language="en")
        session.stop_and_process(language="en")

        self.assertEqual(watcher.started, [])

    def test_cancel_stops_speculative_transcription_session(self):
        from services.runtime.session import RuntimeSession

        speculative = FakeSpeculative()
        session = RuntimeSession(
            recorder_factory=lambda: FakeRecorder(),
            pipeline=FakePipeline(),
            status=FakeStatus(),
            logger=FakeLogger(),
            speculative_factory=lambda recorder, pipeline, logger: speculative,
        )

        session.start_recording(language="en")
        session.cancel()

        self.assertEqual(speculative.cancelled, 1)

    def test_stop_and_process_decodes_wav_bytes_before_pipeline(self):
        from services.asr.audio_capture import AudioRecorder
        from services.runtime.session import RuntimeSession

        wav_bytes = AudioRecorder.float_samples_to_wav_bytes([0.0, 0.5, -0.5])
        pipeline = FakePipeline(result="ok")
        session = RuntimeSession(
            recorder_factory=lambda: FakeRecorder(audio=wav_bytes),
            pipeline=pipeline,
            status=FakeStatus(),
            logger=FakeLogger(),
        )

        session.start_recording()
        session.stop_and_process()

        samples, language = pipeline.calls[0]
        self.assertEqual(language, None)
        self.assertEqual(len(samples), 3)
        self.assertAlmostEqual(samples[0], 0.0, places=3)
        self.assertAlmostEqual(samples[1], 0.5, places=3)
        self.assertAlmostEqual(samples[2], -0.5, places=3)

    def test_no_speech_result_reports_no_speech_and_returns_idle(self):
        from services.runtime.session import RuntimeSession, RuntimeState

        status = FakeStatus()
        session = RuntimeSession(
            recorder_factory=lambda: FakeRecorder(),
            pipeline=FakePipeline(result=None),
            status=status,
            logger=FakeLogger(),
        )

        session.start_recording()
        result = session.stop_and_process()

        self.assertIsNone(result)
        self.assertEqual(session.state, RuntimeState.IDLE)
        self.assertIn("no_speech", status.events)

    def test_no_speech_can_retry_explicit_fallback_pipeline(self):
        from services.runtime.session import RuntimeSession

        primary = FakePipeline(result=None)
        fallback = FakePipeline(result="fallback ok")
        logger = FakeLogger()
        session = RuntimeSession(
            recorder_factory=lambda: FakeRecorder(audio=[0.2]),
            pipeline=primary,
            fallback_pipeline=fallback,
            fallback_profile="quality",
            status=FakeStatus(),
            logger=logger,
        )

        session.start_recording()
        result = session.stop_and_process(language="en")

        self.assertEqual(result, "fallback ok")
        self.assertEqual(primary.calls, [([0.2], "en")])
        self.assertEqual(fallback.calls, [([0.2], "en")])
        self.assertEqual(logger.events[-1][0], "dictation_success")
        self.assertTrue(logger.events[-1][1]["fallback_attempted"])
        self.assertEqual(logger.events[-1][1]["fallback_profile"], "quality")

    def test_no_speech_logs_audio_sample_count_and_max_amplitude(self):
        from services.runtime.session import RuntimeSession

        logger = FakeLogger()
        session = RuntimeSession(
            recorder_factory=lambda: FakeRecorder(audio=[0.0, 0.03, -0.01]),
            pipeline=FakePipeline(result=None),
            status=FakeStatus(),
            logger=logger,
        )

        session.start_recording()
        session.stop_and_process()

        event, fields = logger.events[-1]
        self.assertEqual(event, "dictation_no_speech")
        self.assertEqual(fields["sample_count"], 3)
        self.assertAlmostEqual(fields["max_abs"], 0.03)

    def test_success_logs_recording_and_pipeline_timings(self):
        from services.pipeline.models import AppContext, PipelineResult
        from services.runtime.session import RuntimeSession

        result = PipelineResult(
            raw_transcript="hello",
            polished_text="Hello.",
            app_context=AppContext(
                app_name="notepad.exe",
                window_title="Untitled",
                category="other",
            ),
            duration_ms=123,
            timings_ms={"asr_ms": 80, "total_ms": 123},
            diagnostics={"vad": {"input_sample_count": 10, "output_sample_count": 8}},
        )
        logger = FakeLogger()
        session = RuntimeSession(
            recorder_factory=lambda: FakeRecorder(audio=[0.0, 0.2]),
            pipeline=FakePipeline(result=result),
            status=FakeStatus(),
            logger=logger,
        )

        session.start_recording()
        session.stop_and_process(language="en")

        event, fields = logger.events[-1]
        self.assertEqual(event, "dictation_success")
        self.assertEqual(fields["duration_ms"], 123)
        self.assertEqual(fields["timings_ms"], {"asr_ms": 80, "total_ms": 123})
        self.assertEqual(
            fields["diagnostics"],
            {"vad": {"input_sample_count": 10, "output_sample_count": 8}},
        )
        self.assertEqual(fields["app_category"], "other")
        self.assertEqual(fields["app_name"], "notepad.exe")
        self.assertIn("recording_ms", fields)
        self.assertEqual(fields["audio_sample_count"], 2)

    def test_success_logs_safe_browser_context_fields(self):
        from services.pipeline.models import AppContext, PipelineResult
        from services.runtime.session import RuntimeSession

        result = PipelineResult(
            raw_transcript="hello",
            polished_text="Hello.",
            app_context=AppContext(
                app_name="chrome.exe",
                window_title="Gmail",
                category="email",
                browser_url="https://mail.google.com/mail/u/0/#inbox",
                visible_text=["private thread body"],
            ),
            duration_ms=123,
        )
        logger = FakeLogger()
        session = RuntimeSession(
            recorder_factory=lambda: FakeRecorder(audio=[0.0, 0.2]),
            pipeline=FakePipeline(result=result),
            status=FakeStatus(),
            logger=logger,
        )

        session.start_recording()
        session.stop_and_process(language="en")

        fields = logger.events[-1][1]
        self.assertEqual(fields["app_category"], "email")
        self.assertEqual(fields["app_name"], "chrome.exe")
        self.assertEqual(fields["browser_host"], "mail.google.com")
        self.assertNotIn("visible_text", fields)

    def test_logs_include_runtime_context_fields(self):
        from services.pipeline.models import AppContext, PipelineResult
        from services.runtime.session import RuntimeSession

        result = PipelineResult(
            raw_transcript="hello",
            polished_text="Hello.",
            app_context=AppContext(
                app_name="notepad.exe",
                window_title="Untitled",
                category="other",
            ),
            duration_ms=123,
        )
        logger = FakeLogger()
        session = RuntimeSession(
            recorder_factory=lambda: FakeRecorder(audio=[0.0, 0.2]),
            pipeline=FakePipeline(result=result),
            status=FakeStatus(),
            logger=logger,
            log_fields={
                "asr_profile": "low-impact",
                "asr_model": "small.en",
                "asr_cpu_threads": 2,
                "asr_speculative_enabled": False,
            },
        )

        session.start_recording()
        session.stop_and_process(language="en")

        start_event, start_fields = logger.events[0]
        success_event, success_fields = logger.events[-1]
        self.assertEqual(start_event, "recording_started")
        self.assertEqual(success_event, "dictation_success")
        self.assertEqual(start_fields["asr_profile"], "low-impact")
        self.assertEqual(success_fields["asr_profile"], "low-impact")
        self.assertEqual(success_fields["asr_model"], "small.en")
        self.assertEqual(success_fields["asr_cpu_threads"], 2)
        self.assertFalse(success_fields["asr_speculative_enabled"])

    def test_logs_include_quiet_mode_field(self):
        from services.pipeline.models import AppContext, PipelineResult
        from services.runtime.session import RuntimeSession

        result = PipelineResult(
            raw_transcript="hello",
            polished_text="Hello.",
            app_context=AppContext(app_name="notepad.exe", window_title="", category="other"),
            duration_ms=123,
        )
        logger = FakeLogger()
        session = RuntimeSession(
            recorder_factory=lambda: FakeRecorder(audio=[0.0, 0.2]),
            pipeline=FakePipeline(result=result),
            status=FakeStatus(),
            logger=logger,
            log_fields={"quiet_mode": True},
        )

        session.start_recording()
        session.stop_and_process(language="en")

        self.assertTrue(logger.events[0][1]["quiet_mode"])
        self.assertTrue(logger.events[-1][1]["quiet_mode"])

    def test_processing_error_records_error_and_returns_to_idle(self):
        from services.runtime.session import RuntimeSession, RuntimeState

        status = FakeStatus()
        logger = FakeLogger()
        session = RuntimeSession(
            recorder_factory=lambda: FakeRecorder(),
            pipeline=FakePipeline(error=RuntimeError("boom")),
            status=status,
            logger=logger,
        )

        session.start_recording()
        result = session.stop_and_process()

        self.assertIsNone(result)
        self.assertEqual(session.state, RuntimeState.IDLE)
        self.assertIsInstance(session.last_error, RuntimeError)
        self.assertIn(("error", "boom"), status.events)
        self.assertEqual(logger.events[-1][0], "dictation_error")

    def test_cancel_stops_recording_without_processing(self):
        from services.runtime.session import RuntimeSession, RuntimeState

        recorder = FakeRecorder()
        pipeline = FakePipeline(result="should not happen")
        logger = FakeLogger()
        session = RuntimeSession(
            recorder_factory=lambda: recorder,
            pipeline=pipeline,
            status=FakeStatus(),
            logger=logger,
        )

        session.start_recording()
        session.cancel()

        self.assertEqual(session.state, RuntimeState.IDLE)
        self.assertEqual(recorder.stopped, 1)
        self.assertEqual(pipeline.calls, [])
        self.assertEqual(logger.events[-1][0], "dictation_cancelled")


if __name__ == "__main__":
    unittest.main()
