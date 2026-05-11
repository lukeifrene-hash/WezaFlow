import io
import math
import unittest
import wave


class AudioRecorderTests(unittest.TestCase):
    def test_float_samples_convert_to_16khz_mono_wav_bytes(self):
        from services.asr.audio_capture import AudioRecorder

        wav_bytes = AudioRecorder.float_samples_to_wav_bytes([0.0, 0.5, -1.0, 1.0])

        with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
            self.assertEqual(wav.getframerate(), 16000)
            self.assertEqual(wav.getnchannels(), 1)
            self.assertEqual(wav.getsampwidth(), 2)
            self.assertEqual(wav.getnframes(), 4)
            frames = wav.readframes(4)

        samples = [
            int.from_bytes(frames[index : index + 2], "little", signed=True)
            for index in range(0, len(frames), 2)
        ]
        self.assertEqual(samples, [0, 16384, -32767, 32767])

    def test_recorder_collects_injected_frames_between_start_and_stop(self):
        from services.asr.audio_capture import AudioRecorder

        recorder = AudioRecorder()

        recorder.inject_frame([0.25])
        recorder.start()
        recorder.inject_frame([0.5, -0.5])
        recorder.inject_frame([1.5])
        wav_bytes = recorder.stop()

        self.assertFalse(recorder.is_recording)
        with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
            self.assertEqual(wav.getnframes(), 3)

    def test_recorder_returns_snapshot_without_stopping_recording(self):
        from services.asr.audio_capture import AudioRecorder

        recorder = AudioRecorder()

        recorder.start()
        recorder.inject_frame([0.25, -0.5])
        snapshot = recorder.snapshot_samples()
        recorder.inject_frame([0.75])
        wav_bytes = recorder.stop()

        self.assertEqual(snapshot, [0.25, -0.5])
        self.assertFalse(recorder.is_recording)
        with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
            self.assertEqual(wav.getnframes(), 3)

    def test_recorder_can_capture_from_injected_stream_factory(self):
        from services.asr.audio_capture import AudioRecorder

        class Stream:
            def __init__(self, callback):
                self.callback = callback
                self.stopped = False
                self.closed = False

            def start(self):
                self.callback([[0.25], [-0.25]], 2, None, None)

            def stop(self):
                self.stopped = True

            def close(self):
                self.closed = True

        streams = []

        def stream_factory(callback, sample_rate, blocksize):
            stream = Stream(callback)
            streams.append((stream, sample_rate, blocksize))
            return stream

        recorder = AudioRecorder(stream_factory=stream_factory, blocksize=512)

        recorder.start()
        wav_bytes = recorder.stop()

        self.assertTrue(streams[0][0].stopped)
        self.assertTrue(streams[0][0].closed)
        self.assertEqual(streams[0][1], 16000)
        self.assertEqual(streams[0][2], 512)
        with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
            self.assertEqual(wav.getnframes(), 2)


class VADFilterTests(unittest.TestCase):
    def test_energy_fallback_returns_none_for_short_quiet_audio(self):
        from services.asr.vad import VADFilter

        vad = VADFilter(threshold=0.05, min_duration_ms=100, sample_rate=16000)

        self.assertIsNone(vad.filter([0.01] * 1600))

    def test_energy_fallback_keeps_audio_above_threshold_for_min_duration(self):
        from services.asr.vad import VADFilter

        vad = VADFilter(threshold=0.05, min_duration_ms=100, sample_rate=16000)
        audio = [0.0] * 400 + [0.1] * 1600 + [0.0] * 400

        self.assertEqual(vad.filter(audio), audio)

    def test_energy_fallback_keeps_quiet_recording_with_real_peak(self):
        from services.asr.vad import VADFilter

        vad = VADFilter(threshold=0.02, min_duration_ms=250, sample_rate=16000)
        audio = [0.0] * 32000
        audio[1000] = 0.038
        audio[1500] = -0.041

        self.assertEqual(vad.filter(audio), audio)

    def test_energy_fallback_trims_leading_and_trailing_silence_with_padding(self):
        from services.asr.vad import VADFilter

        vad = VADFilter(
            threshold=0.05,
            min_duration_ms=100,
            sample_rate=1000,
            trim_padding_ms=100,
        )
        audio = [0.0] * 500 + [0.1] * 200 + [0.0] * 500

        self.assertEqual(vad.filter(audio), [0.0] * 100 + [0.1] * 200 + [0.0] * 100)

    def test_trim_uses_lower_boundary_threshold_to_keep_soft_edge_words(self):
        from services.asr.vad import VADFilter

        vad = VADFilter(
            threshold=0.02,
            min_duration_ms=100,
            sample_rate=1000,
            trim_padding_ms=100,
            trim_threshold=0.005,
        )
        audio = [0.0] * 500 + [0.008] * 300 + [0.03] * 100 + [0.008] * 300 + [0.0] * 500

        self.assertEqual(vad.filter(audio), [0.0] * 100 + [0.008] * 300 + [0.03] * 100 + [0.008] * 300 + [0.0] * 100)
        self.assertEqual(vad.last_stats["input_sample_count"], 1700)
        self.assertEqual(vad.last_stats["output_sample_count"], 900)
        self.assertEqual(vad.last_stats["trim_start_samples"], 400)
        self.assertEqual(vad.last_stats["trim_end_samples"], 400)


class TranscriberTests(unittest.TestCase):
    def test_transcriber_uses_injected_backend_and_returns_asr_result(self):
        from services.asr.transcriber import Transcriber
        from services.pipeline.models import AsrResult

        class Backend:
            def transcribe(self, audio, language=None, initial_prompt=None):
                self.calls = [(audio, language, initial_prompt)]
                return {"text": "hello world", "language": language or "en", "duration_ms": 42}

        backend = Backend()
        result = Transcriber(backend=backend).transcribe(
            b"wav", language="en", initial_prompt="Names: LocalFlow"
        )

        self.assertIsInstance(result, AsrResult)
        self.assertEqual(result.text, "hello world")
        self.assertEqual(result.language, "en")
        self.assertEqual(result.duration_ms, 42)
        self.assertEqual(backend.calls, [(b"wav", "en", "Names: LocalFlow")])

    def test_transcriber_reuses_lazy_default_backend(self):
        import services.asr.transcriber as transcriber_module

        original_backend = transcriber_module.FasterWhisperBackend

        class Backend:
            created = 0

            def __init__(self, *args, **kwargs):
                Backend.created += 1

            def transcribe(self, audio, language=None, initial_prompt=None):
                return {"text": "hello", "language": language, "duration_ms": 1}

        transcriber_module.FasterWhisperBackend = Backend
        try:
            transcriber = transcriber_module.Transcriber()
            transcriber.transcribe([0.1], language="en")
            transcriber.transcribe([0.2], language="en")
        finally:
            transcriber_module.FasterWhisperBackend = original_backend

        self.assertEqual(Backend.created, 1)

    def test_faster_whisper_backend_converts_python_samples_to_float32_array(self):
        from services.asr.transcriber import FasterWhisperBackend

        class FakeArray:
            def __init__(self, values, dtype):
                self.values = values
                self.dtype = dtype

        class FakeNumpy:
            float32 = "float32"

            @staticmethod
            def asarray(values, dtype=None):
                return FakeArray(values, dtype)

        class Model:
            def __init__(self):
                self.seen_audio = None

            def transcribe(self, audio, language=None, initial_prompt=None):
                self.seen_audio = audio
                return {"text": "hello", "language": language, "duration_ms": 1}

        model = Model()
        backend = FasterWhisperBackend(numpy_module=FakeNumpy())
        backend._model = model

        backend.transcribe([0.0, 0.1, -0.1], language="en")

        self.assertIsInstance(model.seen_audio, FakeArray)
        self.assertEqual(model.seen_audio.values, [0.0, 0.1, -0.1])
        self.assertEqual(model.seen_audio.dtype, "float32")

    def test_transcriber_normalizes_faster_whisper_segment_results(self):
        from services.asr.transcriber import Transcriber

        class Segment:
            text = "hello"

        class Info:
            language = "en"
            duration = 1.25

        class Backend:
            def transcribe(self, audio, language=None, initial_prompt=None):
                return [Segment()], Info()

        result = Transcriber(backend=Backend()).transcribe([math.sin(1.0)])

        self.assertEqual(result.text, "hello")
        self.assertEqual(result.language, "en")
        self.assertEqual(result.duration_ms, 1250)

    def test_transcriber_warm_up_reuses_lazy_backend(self):
        import services.asr.transcriber as transcriber_module

        original_backend = transcriber_module.FasterWhisperBackend

        class Backend:
            created = 0

            def __init__(self, *args, **kwargs):
                Backend.created += 1
                self.warmups = []

            def warm_up(self, language=None):
                self.warmups.append(language)

            def transcribe(self, audio, language=None, initial_prompt=None):
                return {"text": "hello", "language": language, "duration_ms": 1}

        transcriber_module.FasterWhisperBackend = Backend
        try:
            transcriber = transcriber_module.Transcriber()
            transcriber.warm_up(language="en")
            transcriber.transcribe([0.2], language="en")
        finally:
            transcriber_module.FasterWhisperBackend = original_backend

        self.assertEqual(Backend.created, 1)
        self.assertEqual(transcriber.backend.warmups, ["en"])


if __name__ == "__main__":
    unittest.main()
