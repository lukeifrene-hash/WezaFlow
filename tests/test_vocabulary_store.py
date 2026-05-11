import tempfile
import unittest
from pathlib import Path


class VocabularyStoreLearningSuggestionTests(unittest.TestCase):
    def test_learning_suggestions_use_correction_counts_and_thresholds(self):
        from services.vocabulary.store import VocabularyStore

        with tempfile.TemporaryDirectory() as temp_dir:
            store = VocabularyStore(Path(temp_dir) / "localflow.db")
            store.record_correction("lf", "LocalFlow")
            store.record_correction("lf", "LocalFlow")
            store.record_correction("bye", "Thank you for your time and consideration.")
            store.record_correction("bye", "Thank you for your time and consideration.")
            store.record_correction("bye", "Thank you for your time and consideration.")
            store.record_correction("ok", "Okay")

            suggestions = store.learning_suggestions()

        self.assertEqual(
            suggestions,
            [
                {
                    "kind": "snippet",
                    "expansion": "Thank you for your time and consideration.",
                    "count": 3,
                },
                {
                    "kind": "vocabulary",
                    "phrase": "Thank you for your time and consideration.",
                    "count": 3,
                },
                {
                    "kind": "vocabulary",
                    "phrase": "LocalFlow",
                    "count": 2,
                },
            ],
        )

    def test_learning_suggestions_can_override_thresholds(self):
        from services.vocabulary.store import VocabularyStore

        with tempfile.TemporaryDirectory() as temp_dir:
            store = VocabularyStore(Path(temp_dir) / "localflow.db")
            store.record_correction("lf", "LocalFlow")

            suggestions = store.learning_suggestions(
                vocabulary_threshold=1,
                snippet_threshold=1,
                snippet_min_chars=5,
            )

        self.assertEqual([suggestion["kind"] for suggestion in suggestions], ["snippet", "vocabulary"])


if __name__ == "__main__":
    unittest.main()
