from __future__ import annotations

import sqlite3
from pathlib import Path


class VocabularyStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def add_word(self, word: str) -> None:
        normalized = self._normalize(word)
        if not normalized:
            return
        display_word = self._display_word(word)
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT display_word FROM vocabulary WHERE word = ?",
                (normalized,),
            ).fetchone()
            if row:
                best_display_word = self._best_display_word(row[0], display_word, normalized)
                connection.execute(
                    "UPDATE vocabulary SET frequency = frequency + 1, display_word = ? WHERE word = ?",
                    (best_display_word, normalized),
                )
            else:
                connection.execute(
                    "INSERT INTO vocabulary(word, frequency, display_word) VALUES (?, 1, ?)",
                    (normalized, display_word),
                )
            connection.commit()
        finally:
            connection.close()

    def record_correction(self, original: str, corrected: str) -> None:
        original = original.strip()
        corrected = corrected.strip()
        if not original or not corrected:
            return
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT id FROM corrections WHERE original = ? AND corrected = ?",
                (original, corrected),
            ).fetchone()
            if row:
                connection.execute("UPDATE corrections SET count = count + 1 WHERE id = ?", (row[0],))
            else:
                connection.execute(
                    "INSERT INTO corrections(original, corrected, count) VALUES (?, ?, 1)",
                    (original, corrected),
                )
            connection.commit()
        finally:
            connection.close()

    def list_vocabulary(self, limit: int | None = None) -> list[dict[str, int | str]]:
        sql = "SELECT word, frequency FROM vocabulary ORDER BY frequency DESC, word ASC"
        params: tuple[int, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        connection = self._connect()
        try:
            rows = connection.execute(sql, params).fetchall()
        finally:
            connection.close()
        return [{"word": row[0], "frequency": row[1]} for row in rows]

    def delete_word(self, word: str) -> bool:
        normalized = self._normalize(word)
        if not normalized:
            return False
        connection = self._connect()
        try:
            cursor = connection.execute("DELETE FROM vocabulary WHERE word = ?", (normalized,))
            connection.commit()
            return cursor.rowcount > 0
        finally:
            connection.close()

    def list_correction_pairs(self, limit: int | None = None) -> list[dict[str, int | str]]:
        sql = "SELECT original, corrected, count FROM corrections ORDER BY count DESC, original ASC, corrected ASC"
        params: tuple[int, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        connection = self._connect()
        try:
            rows = connection.execute(sql, params).fetchall()
        finally:
            connection.close()
        return [{"original": row[0], "corrected": row[1], "count": row[2]} for row in rows]

    def learning_suggestions(
        self,
        vocabulary_threshold: int = 2,
        snippet_threshold: int = 3,
        snippet_min_chars: int = 20,
    ) -> list[dict[str, int | str]]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT corrected, SUM(count) AS total_count
                FROM corrections
                GROUP BY corrected
                ORDER BY total_count DESC, corrected ASC
                """
            ).fetchall()
        finally:
            connection.close()

        suggestions: list[dict[str, int | str]] = []
        for corrected, count in rows:
            text = str(corrected).strip()
            if count >= snippet_threshold and len(text) >= snippet_min_chars:
                suggestions.append(
                    {
                        "kind": "snippet",
                        "expansion": text,
                        "count": count,
                    }
                )
            if count >= vocabulary_threshold:
                suggestions.append(
                    {
                        "kind": "vocabulary",
                        "phrase": text,
                        "count": count,
                    }
                )
        return suggestions

    def delete_correction(self, original: str, corrected: str) -> bool:
        original = original.strip()
        corrected = corrected.strip()
        if not original or not corrected:
            return False
        connection = self._connect()
        try:
            cursor = connection.execute(
                "DELETE FROM corrections WHERE original = ? AND corrected = ?",
                (original, corrected),
            )
            connection.commit()
            return cursor.rowcount > 0
        finally:
            connection.close()

    def formatter_hints(self, vocabulary_limit: int = 20, correction_limit: int = 20) -> list[str]:
        hints = self._list_display_vocabulary(vocabulary_limit)
        hints.extend(
            f"{row['original']} -> {row['corrected']}"
            for row in self.list_correction_pairs(limit=correction_limit)
        )
        return hints

    def asr_hints(self, vocabulary_limit: int = 20, correction_limit: int = 20) -> str:
        terms = self._list_display_vocabulary(vocabulary_limit)
        seen = {term.casefold() for term in terms}
        for row in self.list_correction_pairs(limit=correction_limit):
            corrected = str(row["corrected"])
            if corrected.casefold() not in seen:
                terms.append(corrected)
                seen.add(corrected.casefold())
        return ", ".join(terms)

    def _init_schema(self) -> None:
        schema_path = Path(__file__).resolve().parents[2] / "db" / "schema.sql"
        connection = self._connect()
        try:
            connection.executescript(schema_path.read_text(encoding="utf-8"))
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(vocabulary)").fetchall()
            }
            if "display_word" not in columns:
                connection.execute("ALTER TABLE vocabulary ADD COLUMN display_word TEXT")
            connection.commit()
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    @staticmethod
    def _normalize(word: str) -> str:
        return " ".join(word.casefold().strip().split())

    @staticmethod
    def _display_word(word: str) -> str:
        return " ".join(word.strip().split())

    @staticmethod
    def _best_display_word(existing: str | None, candidate: str, normalized: str) -> str:
        if not existing:
            return candidate
        if existing == normalized and candidate != normalized:
            return candidate
        return existing

    def _list_display_vocabulary(self, limit: int | None = None) -> list[str]:
        sql = """
            SELECT word, COALESCE(display_word, word), frequency
            FROM vocabulary
            ORDER BY frequency DESC, word ASC
        """
        params: tuple[int, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        connection = self._connect()
        try:
            rows = connection.execute(sql, params).fetchall()
        finally:
            connection.close()
        return [row[1] for row in rows]
