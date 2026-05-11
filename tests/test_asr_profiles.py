import unittest


class AsrProfileTests(unittest.TestCase):
    def test_low_impact_is_default_runtime_profile(self):
        from services.asr.profiles import DEFAULT_ASR_PROFILE, resolve_asr_profile

        self.assertEqual(DEFAULT_ASR_PROFILE, "low-impact")
        self.assertEqual(resolve_asr_profile(None).name, "low-impact")

    def test_runtime_profiles_capture_model_thread_and_compute_choices(self):
        from services.asr.profiles import resolve_asr_profile

        low_impact = resolve_asr_profile("low-impact")
        snappy = resolve_asr_profile("snappy")
        balanced = resolve_asr_profile("balanced")
        quality = resolve_asr_profile("quality")
        distil_small = resolve_asr_profile("distil-small-en")

        self.assertEqual(low_impact.model_name, "small.en")
        self.assertEqual(low_impact.cpu_threads, 2)
        self.assertEqual(low_impact.speculative_cpu_threads, 2)
        self.assertFalse(low_impact.speculative_enabled)
        self.assertEqual(low_impact.supported_languages, ("en",))
        self.assertEqual(snappy.model_name, "small.en")
        self.assertEqual(snappy.cpu_threads, 4)
        self.assertEqual(snappy.speculative_cpu_threads, 2)
        self.assertFalse(snappy.speculative_enabled)
        self.assertEqual(snappy.supported_languages, ("en",))
        self.assertEqual(balanced.model_name, "small.en")
        self.assertEqual(balanced.cpu_threads, 4)
        self.assertEqual(balanced.speculative_cpu_threads, 2)
        self.assertTrue(balanced.speculative_enabled)
        self.assertEqual(balanced.supported_languages, ("en",))
        self.assertEqual(quality.model_name, "distil-large-v3")
        self.assertEqual(quality.cpu_threads, 6)
        self.assertEqual(quality.speculative_cpu_threads, 2)
        self.assertTrue(quality.speculative_enabled)
        self.assertIsNone(quality.supported_languages)
        self.assertEqual(distil_small.model_name, "Systran/faster-distil-whisper-small.en")
        self.assertEqual(distil_small.cpu_threads, 2)
        self.assertEqual(distil_small.speculative_cpu_threads, 2)
        self.assertFalse(distil_small.speculative_enabled)
        self.assertEqual(distil_small.supported_languages, ("en",))
        self.assertEqual(
            {
                low_impact.compute_type,
                snappy.compute_type,
                balanced.compute_type,
                quality.compute_type,
                distil_small.compute_type,
            },
            {"int8"},
        )

    def test_asr_profile_names_include_snappy(self):
        from services.asr.profiles import asr_profile_names

        self.assertIn("snappy", asr_profile_names())

    def test_unknown_runtime_profile_is_rejected(self):
        from services.asr.profiles import resolve_asr_profile

        with self.assertRaises(ValueError):
            resolve_asr_profile("turbo-party")


if __name__ == "__main__":
    unittest.main()
