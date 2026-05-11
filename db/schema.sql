CREATE TABLE IF NOT EXISTS vocabulary (
  id INTEGER PRIMARY KEY,
  word TEXT NOT NULL UNIQUE,
  display_word TEXT,
  frequency INTEGER DEFAULT 1,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS app_profiles (
  id INTEGER PRIMARY KEY,
  app_name TEXT NOT NULL,
  app_category TEXT NOT NULL,
  custom_system_prompt TEXT,
  tone TEXT DEFAULT 'formal'
);

CREATE TABLE IF NOT EXISTS snippets (
  id INTEGER PRIMARY KEY,
  trigger_phrase TEXT NOT NULL UNIQUE,
  expansion TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transcription_history (
  id INTEGER PRIMARY KEY,
  raw_transcript TEXT,
  polished_text TEXT,
  app_context TEXT,
  duration_ms INTEGER,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS corrections (
  id INTEGER PRIMARY KEY,
  original TEXT NOT NULL,
  corrected TEXT NOT NULL,
  count INTEGER DEFAULT 1
);
