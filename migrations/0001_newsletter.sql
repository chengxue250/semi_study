CREATE TABLE IF NOT EXISTS subscribers (
  email TEXT PRIMARY KEY,
  status TEXT NOT NULL DEFAULT 'pending',
  lang TEXT NOT NULL DEFAULT 'both',
  confirmation_token TEXT,
  unsubscribe_token TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  confirmed_at TEXT,
  unsubscribed_at TEXT,
  last_sent_date TEXT,
  send_count INTEGER NOT NULL DEFAULT 0,
  source TEXT,
  user_agent TEXT
);

CREATE INDEX IF NOT EXISTS idx_subscribers_status
  ON subscribers(status);

CREATE INDEX IF NOT EXISTS idx_subscribers_confirmation_token
  ON subscribers(confirmation_token);

CREATE INDEX IF NOT EXISTS idx_subscribers_unsubscribe_token
  ON subscribers(unsubscribe_token);

CREATE TABLE IF NOT EXISTS newsletter_sends (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL,
  edition_date TEXT NOT NULL,
  status TEXT NOT NULL,
  provider_id TEXT,
  error TEXT,
  created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_newsletter_sends_once
  ON newsletter_sends(email, edition_date);
