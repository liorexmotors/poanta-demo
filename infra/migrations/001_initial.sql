-- Poanta production skeleton schema
-- Feed versions are immutable publish snapshots; feed_items belong to a version.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS sources (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  logo TEXT,
  url TEXT,
  is_foreign BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (name)
);

CREATE TABLE IF NOT EXISTS feed_versions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  version_key TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL DEFAULT 'published',
  source TEXT NOT NULL DEFAULT 'legacy_import',
  published_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  legacy_updated_at TEXT,
  item_count INTEGER NOT NULL DEFAULT 0,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS feed_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  feed_version_id UUID NOT NULL REFERENCES feed_versions(id) ON DELETE CASCADE,
  source_id UUID REFERENCES sources(id),
  source_name TEXT NOT NULL,
  source_logo TEXT,
  source_url TEXT,
  original_title TEXT,
  headline TEXT NOT NULL,
  summary TEXT NOT NULL,
  takeaway TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT 'חדשות',
  category_class TEXT,
  image_url TEXT,
  published_at TIMESTAMPTZ,
  has_source_date BOOLEAN NOT NULL DEFAULT FALSE,
  editor_status TEXT,
  position INTEGER NOT NULL,
  raw JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (feed_version_id, position)
);

CREATE INDEX IF NOT EXISTS idx_feed_versions_published_at ON feed_versions (published_at DESC);
CREATE INDEX IF NOT EXISTS idx_feed_items_version_position ON feed_items (feed_version_id, position ASC);
CREATE INDEX IF NOT EXISTS idx_feed_items_published_at ON feed_items (published_at DESC);
CREATE INDEX IF NOT EXISTS idx_feed_items_source_name ON feed_items (source_name);

CREATE TABLE IF NOT EXISTS devices (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  device_id TEXT NOT NULL UNIQUE,
  platform TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS feedback_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  device_id TEXT,
  card_key TEXT NOT NULL,
  source_url TEXT,
  source_name TEXT,
  category TEXT,
  headline TEXT,
  feedback TEXT NOT NULL CHECK (feedback IN ('up', 'down', 'clear')),
  client_ts TIMESTAMPTZ,
  received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_feedback_events_received_at ON feedback_events (received_at DESC);
CREATE INDEX IF NOT EXISTS idx_feedback_events_card_key ON feedback_events (card_key);
CREATE INDEX IF NOT EXISTS idx_feedback_events_source_name ON feedback_events (source_name);
CREATE INDEX IF NOT EXISTS idx_feedback_events_feedback_received_at ON feedback_events (feedback, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_feedback_events_source_url ON feedback_events (source_url);
