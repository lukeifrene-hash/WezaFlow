import tempfile
import unittest
from pathlib import Path


class VocabularyScriptTests(unittest.TestCase):
    def test_add_term_add_correction_and_list_terms(self):
        from scripts.vocabulary import main

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "localflow.db"
            lines = []

            self.assertEqual(main(["--db", str(db_path), "add-term", "LocalFlow"], output=lines.append), 0)
            self.assertEqual(
                main(
                    ["--db", str(db_path), "add-correction", "local flow", "LocalFlow"],
                    output=lines.append,
                ),
                0,
            )
            self.assertEqual(main(["--db", str(db_path), "list"], output=lines.append), 0)

        self.assertIn("Added vocabulary term: LocalFlow", lines)
        self.assertIn("Added correction: local flow -> LocalFlow", lines)
        self.assertTrue(any("LocalFlow" in line for line in lines))
        self.assertTrue(any("local flow -> LocalFlow" in line for line in lines))
