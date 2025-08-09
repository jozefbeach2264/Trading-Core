CREATE TABLE IF NOT EXISTS mt_filters (
  id BIGSERIAL PRIMARY KEY,
  module_timestamp TIMESTAMPTZ NOT NULL,
  candle_timestamp TIMESTAMPTZ NULL,
  filter_name TEXT NOT NULL,
  score DOUBLE PRECISION NOT NULL,
  flag TEXT NOT NULL,
  metrics JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS mt_trades (
  id BIGSERIAL PRIMARY KEY,
  module_timestamp TIMESTAMPTZ NOT NULL,
  candle_timestamp TIMESTAMPTZ NULL,
  direction TEXT NOT NULL,
  quantity DOUBLE PRECISION NOT NULL,
  entry_price DOUBLE PRECISION NOT NULL,
  simulated BOOLEAN NOT NULL,
  failed BOOLEAN NOT NULL,
  reason TEXT NOT NULL,
  order_data JSONB NOT NULL,
  ai_verdict JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS mt_verdicts (
  id BIGSERIAL PRIMARY KEY,
  module_timestamp TIMESTAMPTZ NOT NULL,
  candle_timestamp TIMESTAMPTZ NULL,
  direction TEXT NOT NULL,
  entry_price DOUBLE PRECISION NOT NULL,
  verdict TEXT NOT NULL,
  confidence DOUBLE PRECISION NOT NULL,
  reason TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_mt_filters_modts  ON mt_filters  (module_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_mt_trades_modts   ON mt_trades   (module_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_mt_verdicts_modts ON mt_verdicts (module_timestamp DESC);