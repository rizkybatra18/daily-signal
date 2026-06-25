-- ════════════════════════════════════════════════════════════════
--  DAILY SIGNAL — Supabase PostgreSQL Migration
--  Version: 1.0.0
--  Run via Supabase SQL Editor atau psql
-- ════════════════════════════════════════════════════════════════

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- ── 1. STOCKS ─────────────────────────────────────────────────────
-- Master data seluruh saham BEI
CREATE TABLE IF NOT EXISTS stocks (
    id              UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    ticker          VARCHAR(20) NOT NULL UNIQUE,  -- e.g. "BBCA.JK"
    ticker_clean    VARCHAR(10) NOT NULL,          -- e.g. "BBCA"
    name            VARCHAR(200),
    sector          VARCHAR(100),
    sub_sector      VARCHAR(100),
    listing_date    DATE,
    is_active       BOOLEAN DEFAULT TRUE,
    is_delisted     BOOLEAN DEFAULT FALSE,
    delisted_date   DATE,
    market_cap      BIGINT,
    shares_outstanding BIGINT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_stocks_ticker ON stocks(ticker);
CREATE INDEX idx_stocks_sector ON stocks(sector);
CREATE INDEX idx_stocks_is_active ON stocks(is_active);

-- ── 2. DAILY_PRICES ───────────────────────────────────────────────
-- Harga OHLCV harian untuk semua saham
CREATE TABLE IF NOT EXISTS daily_prices (
    id          UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    ticker      VARCHAR(20) NOT NULL,
    trade_date  DATE NOT NULL,
    open        NUMERIC(15,2),
    high        NUMERIC(15,2),
    low         NUMERIC(15,2),
    close       NUMERIC(15,2),
    volume      BIGINT,
    -- Computed fields (populated by data layer)
    change_pct  NUMERIC(8,4),      -- % change dari hari sebelumnya
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_daily_prices_ticker_date UNIQUE (ticker, trade_date),
    CONSTRAINT fk_daily_prices_stock FOREIGN KEY (ticker) REFERENCES stocks(ticker)
);

CREATE INDEX idx_daily_prices_ticker ON daily_prices(ticker);
CREATE INDEX idx_daily_prices_date ON daily_prices(trade_date DESC);
CREATE INDEX idx_daily_prices_ticker_date ON daily_prices(ticker, trade_date DESC);

-- ── 3. SIGNALS ────────────────────────────────────────────────────
-- Sinyal trading yang dihasilkan setiap hari
CREATE TABLE IF NOT EXISTS signals (
    id              UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    signal_date     DATE NOT NULL,
    ticker          VARCHAR(20) NOT NULL,
    -- Signal classification
    signal_type     VARCHAR(20) NOT NULL CHECK (signal_type IN ('STRONG_BUY','BUY','WATCHLIST','AVOID')),
    composite_score NUMERIC(6,2),   -- 0-100 composite score
    -- Score breakdown
    trend_score     NUMERIC(6,2),   -- 0-25
    momentum_score  NUMERIC(6,2),   -- 0-25
    volume_score    NUMERIC(6,2),   -- 0-20
    strength_score  NUMERIC(6,2),   -- 0-15
    volatility_score NUMERIC(6,2),  -- 0-15
    -- Indicators snapshot
    close_price     NUMERIC(15,2),
    ema20           NUMERIC(15,2),
    ema50           NUMERIC(15,2),
    ema200          NUMERIC(15,2),
    rsi             NUMERIC(6,2),
    macd_line       NUMERIC(12,6),
    macd_signal     NUMERIC(12,6),
    macd_hist       NUMERIC(12,6),
    adx             NUMERIC(6,2),
    atr             NUMERIC(15,2),
    volume          BIGINT,
    avg_volume_20   BIGINT,
    volume_ratio    NUMERIC(6,2),
    rel_strength    NUMERIC(8,4),   -- RS vs IHSG
    -- Risk Management
    entry_price     NUMERIC(15,2),
    stop_loss       NUMERIC(15,2),
    target_1        NUMERIC(15,2),
    target_2        NUMERIC(15,2),
    risk_reward     NUMERIC(6,2),
    position_risk   NUMERIC(6,2),   -- % risk per trade
    -- Context
    market_regime   VARCHAR(20),    -- BULL/SIDEWAYS/BEAR
    sector          VARCHAR(100),
    sector_rank     INTEGER,
    -- Metadata
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT fk_signals_stock FOREIGN KEY (ticker) REFERENCES stocks(ticker)
);

CREATE INDEX idx_signals_date ON signals(signal_date DESC);
CREATE INDEX idx_signals_ticker ON signals(ticker);
CREATE INDEX idx_signals_type ON signals(signal_type);
CREATE INDEX idx_signals_score ON signals(composite_score DESC);
CREATE INDEX idx_signals_date_type ON signals(signal_date, signal_type);

-- ── 4. SIGNAL_UPDATES ─────────────────────────────────────────────
-- Update status sinyal (TP1/TP2/SL hit)
CREATE TABLE IF NOT EXISTS signal_updates (
    id              UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    signal_id       UUID NOT NULL,
    ticker          VARCHAR(20) NOT NULL,
    update_type     VARCHAR(20) NOT NULL CHECK (update_type IN ('TP1_HIT','TP2_HIT','SL_HIT','EXPIRED','UPDATED')),
    price_at_update NUMERIC(15,2),
    note            TEXT,
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT fk_signal_updates_signal FOREIGN KEY (signal_id) REFERENCES signals(id)
);

CREATE INDEX idx_signal_updates_signal_id ON signal_updates(signal_id);
CREATE INDEX idx_signal_updates_ticker ON signal_updates(ticker);

-- ── 5. OPEN_POSITIONS ─────────────────────────────────────────────
-- Posisi yang sedang buka (portfolio tracker)
CREATE TABLE IF NOT EXISTS open_positions (
    id              UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    ticker          VARCHAR(20) NOT NULL,
    signal_id       UUID,           -- referensi ke sinyal asal (bisa NULL jika manual)
    entry_date      DATE NOT NULL,
    entry_price     NUMERIC(15,2) NOT NULL,
    shares          INTEGER NOT NULL,
    stop_loss       NUMERIC(15,2),
    target_1        NUMERIC(15,2),
    target_2        NUMERIC(15,2),
    -- Auto-updated
    current_price   NUMERIC(15,2),
    unrealized_pnl  NUMERIC(15,2),
    unrealized_pct  NUMERIC(8,4),
    -- Meta
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT fk_open_positions_stock FOREIGN KEY (ticker) REFERENCES stocks(ticker)
);

CREATE INDEX idx_open_positions_ticker ON open_positions(ticker);

-- ── 6. CLOSED_POSITIONS ───────────────────────────────────────────
-- Posisi yang sudah ditutup (trade history)
CREATE TABLE IF NOT EXISTS closed_positions (
    id              UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    ticker          VARCHAR(20) NOT NULL,
    signal_id       UUID,
    entry_date      DATE NOT NULL,
    exit_date       DATE NOT NULL,
    entry_price     NUMERIC(15,2) NOT NULL,
    exit_price      NUMERIC(15,2) NOT NULL,
    shares          INTEGER NOT NULL,
    -- PnL
    gross_pnl       NUMERIC(15,2),
    commission      NUMERIC(15,2),  -- biaya komisi + pajak
    net_pnl         NUMERIC(15,2),
    return_pct      NUMERIC(8,4),
    -- Exit classification
    exit_reason     VARCHAR(50),    -- TP1/TP2/SL/MANUAL/EXPIRED
    holding_days    INTEGER,
    -- Journal
    entry_reason    TEXT,
    exit_reason_note TEXT,
    screenshot_url  TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_closed_positions_ticker ON closed_positions(ticker);
CREATE INDEX idx_closed_positions_exit_date ON closed_positions(exit_date DESC);

-- ── 7. PORTFOLIO_SNAPSHOTS ────────────────────────────────────────
-- Snapshot harian nilai portfolio (untuk equity curve)
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id              UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    snapshot_date   DATE NOT NULL UNIQUE,
    total_equity    NUMERIC(20,2),
    cash_balance    NUMERIC(20,2),
    invested_value  NUMERIC(20,2),
    unrealized_pnl  NUMERIC(15,2),
    realized_pnl_ytd NUMERIC(15,2),
    num_open_positions INTEGER,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_portfolio_snapshots_date ON portfolio_snapshots(snapshot_date DESC);

-- ── 8. BACKTEST_RESULTS ───────────────────────────────────────────
-- Hasil backtest per strategi per saham
CREATE TABLE IF NOT EXISTS backtest_results (
    id              UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    run_date        DATE NOT NULL,
    ticker          VARCHAR(20) NOT NULL,
    strategy_name   VARCHAR(100),
    period_start    DATE,
    period_end      DATE,
    -- Trade Statistics
    total_trades    INTEGER,
    winning_trades  INTEGER,
    losing_trades   INTEGER,
    win_rate        NUMERIC(6,4),
    -- Return Metrics
    profit_factor   NUMERIC(8,4),
    expectancy      NUMERIC(10,4),
    avg_gain_pct    NUMERIC(8,4),
    avg_loss_pct    NUMERIC(8,4),
    max_gain_pct    NUMERIC(8,4),
    max_loss_pct    NUMERIC(8,4),
    -- Risk Metrics
    max_drawdown    NUMERIC(8,4),
    sharpe_ratio    NUMERIC(8,4),
    sortino_ratio   NUMERIC(8,4),
    calmar_ratio    NUMERIC(8,4),
    -- Notes
    parameters      JSONB,          -- Strategy parameters used
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_backtest_ticker_run UNIQUE (run_date, ticker, strategy_name)
);

CREATE INDEX idx_backtest_run_date ON backtest_results(run_date DESC);
CREATE INDEX idx_backtest_ticker ON backtest_results(ticker);

-- ── 9. SECTOR_RANKINGS ────────────────────────────────────────────
-- Ranking sektor untuk sector rotation engine
CREATE TABLE IF NOT EXISTS sector_rankings (
    id              UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    rank_date       DATE NOT NULL,
    sector          VARCHAR(100) NOT NULL,
    -- Performance
    return_1d       NUMERIC(8,4),
    return_5d       NUMERIC(8,4),
    return_20d      NUMERIC(8,4),
    momentum_score  NUMERIC(6,2),
    breadth_score   NUMERIC(6,2),   -- % saham di sektor yg naik
    composite_score NUMERIC(6,2),
    rank_position   INTEGER,
    trend           VARCHAR(20),    -- RISING/STABLE/FALLING
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_sector_rank_date UNIQUE (rank_date, sector)
);

CREATE INDEX idx_sector_rankings_date ON sector_rankings(rank_date DESC);

-- ── 10. MARKET_REGIMES ────────────────────────────────────────────
-- Deteksi regime pasar harian
CREATE TABLE IF NOT EXISTS market_regimes (
    id              UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    regime_date     DATE NOT NULL UNIQUE,
    regime          VARCHAR(20) NOT NULL CHECK (regime IN ('BULL','SIDEWAYS','BEAR')),
    -- IHSG Data
    ihsg_close      NUMERIC(15,2),
    ihsg_ema20      NUMERIC(15,2),
    ihsg_ema50      NUMERIC(15,2),
    ihsg_rsi        NUMERIC(6,2),
    ihsg_adx        NUMERIC(6,2),
    -- Market Breadth
    advance_count   INTEGER,        -- Jumlah saham naik
    decline_count   INTEGER,        -- Jumlah saham turun
    advance_decline_ratio NUMERIC(6,4),
    -- Signals
    change_5d_pct   NUMERIC(8,4),
    regime_reason   TEXT,
    -- Weight multipliers untuk scoring
    bull_weight     NUMERIC(4,2) DEFAULT 1.0,
    sideways_weight NUMERIC(4,2) DEFAULT 0.7,
    bear_weight     NUMERIC(4,2) DEFAULT 0.3,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_market_regimes_date ON market_regimes(regime_date DESC);

-- ── 11. SYSTEM_LOGS ───────────────────────────────────────────────
-- Structured logging ke database
CREATE TABLE IF NOT EXISTS system_logs (
    id          UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    log_time    TIMESTAMPTZ DEFAULT NOW(),
    level       VARCHAR(10) NOT NULL CHECK (level IN ('DEBUG','INFO','WARNING','ERROR','CRITICAL')),
    module      VARCHAR(100),
    message     TEXT NOT NULL,
    details     JSONB,
    run_id      UUID            -- Untuk group log dari satu run
);

CREATE INDEX idx_system_logs_time ON system_logs(log_time DESC);
CREATE INDEX idx_system_logs_level ON system_logs(level);
CREATE INDEX idx_system_logs_module ON system_logs(module);

-- ── 12. SCAN_RUNS ─────────────────────────────────────────────────
-- Metadata setiap kali sistem scan dijalankan
CREATE TABLE IF NOT EXISTS scan_runs (
    id              UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    run_id          UUID DEFAULT uuid_generate_v4() UNIQUE,
    run_type        VARCHAR(50),    -- DAILY_SCAN / WEEKLY_MAINTENANCE / etc
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    status          VARCHAR(20) CHECK (status IN ('RUNNING','SUCCESS','FAILED','PARTIAL')),
    stocks_scanned  INTEGER,
    signals_generated INTEGER,
    error_message   TEXT,
    duration_seconds INTEGER,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ════════════════════════════════════════════════════════════════
--  VIEWS — untuk query yang sering dipakai
-- ════════════════════════════════════════════════════════════════

-- View: sinyal hari ini
CREATE OR REPLACE VIEW v_today_signals AS
SELECT
    s.*,
    st.name as stock_name,
    st.sector,
    mr.regime as market_regime
FROM signals s
LEFT JOIN stocks st ON s.ticker = st.ticker
LEFT JOIN market_regimes mr ON mr.regime_date = s.signal_date
WHERE s.signal_date = CURRENT_DATE
ORDER BY s.composite_score DESC;

-- View: portfolio summary
CREATE OR REPLACE VIEW v_portfolio_summary AS
SELECT
    COUNT(*) as total_positions,
    SUM(unrealized_pnl) as total_unrealized_pnl,
    SUM(entry_price * shares) as total_invested,
    AVG(unrealized_pct) as avg_return_pct
FROM open_positions;

-- View: performance statistics
CREATE OR REPLACE VIEW v_performance_stats AS
SELECT
    COUNT(*) as total_trades,
    COUNT(*) FILTER (WHERE net_pnl > 0) as winning_trades,
    COUNT(*) FILTER (WHERE net_pnl <= 0) as losing_trades,
    ROUND(COUNT(*) FILTER (WHERE net_pnl > 0)::NUMERIC / NULLIF(COUNT(*), 0) * 100, 2) as win_rate_pct,
    SUM(net_pnl) as total_pnl,
    AVG(return_pct) FILTER (WHERE net_pnl > 0) * 100 as avg_gain_pct,
    AVG(return_pct) FILTER (WHERE net_pnl <= 0) * 100 as avg_loss_pct,
    AVG(holding_days) as avg_holding_days
FROM closed_positions;

-- ════════════════════════════════════════════════════════════════
--  FUNCTIONS
-- ════════════════════════════════════════════════════════════════

-- Auto-update timestamp
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER stocks_updated_at BEFORE UPDATE ON stocks
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER open_positions_updated_at BEFORE UPDATE ON open_positions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ════════════════════════════════════════════════════════════════
--  ROW LEVEL SECURITY (RLS)
-- ════════════════════════════════════════════════════════════════

ALTER TABLE signals ENABLE ROW LEVEL SECURITY;
ALTER TABLE open_positions ENABLE ROW LEVEL SECURITY;
ALTER TABLE closed_positions ENABLE ROW LEVEL SECURITY;

-- Service role punya akses penuh (untuk GitHub Actions)
CREATE POLICY "service_role_all" ON signals TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "service_role_all" ON open_positions TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "service_role_all" ON closed_positions TO service_role USING (true) WITH CHECK (true);

-- Anon/authenticated bisa read saja
CREATE POLICY "anon_read" ON signals FOR SELECT TO anon USING (true);
CREATE POLICY "anon_read" ON stocks FOR SELECT TO anon USING (true);
CREATE POLICY "anon_read" ON market_regimes FOR SELECT TO anon USING (true);
CREATE POLICY "anon_read" ON sector_rankings FOR SELECT TO anon USING (true);

-- ════════════════════════════════════════════════════════════════
--  INITIAL DATA SEED — Sektor BEI
-- ════════════════════════════════════════════════════════════════

INSERT INTO sector_rankings (rank_date, sector, composite_score, rank_position, trend)
VALUES
    (CURRENT_DATE, 'Financials', 0, 1, 'STABLE'),
    (CURRENT_DATE, 'Consumer Cyclicals', 0, 2, 'STABLE'),
    (CURRENT_DATE, 'Consumer Non-Cyclicals', 0, 3, 'STABLE'),
    (CURRENT_DATE, 'Energy', 0, 4, 'STABLE'),
    (CURRENT_DATE, 'Basic Materials', 0, 5, 'STABLE'),
    (CURRENT_DATE, 'Technology', 0, 6, 'STABLE'),
    (CURRENT_DATE, 'Healthcare', 0, 7, 'STABLE'),
    (CURRENT_DATE, 'Industrials', 0, 8, 'STABLE'),
    (CURRENT_DATE, 'Infrastructure', 0, 9, 'STABLE'),
    (CURRENT_DATE, 'Properties & Real Estate', 0, 10, 'STABLE'),
    (CURRENT_DATE, 'Transportation & Logistics', 0, 11, 'STABLE')
ON CONFLICT DO NOTHING;

-- Success message
DO $$
BEGIN
    RAISE NOTICE '✅ DAILY SIGNAL Schema berhasil dibuat!';
    RAISE NOTICE '   Tables: stocks, daily_prices, signals, signal_updates,';
    RAISE NOTICE '           open_positions, closed_positions, portfolio_snapshots,';
    RAISE NOTICE '           backtest_results, sector_rankings, market_regimes,';
    RAISE NOTICE '           system_logs, scan_runs';
    RAISE NOTICE '   Views:  v_today_signals, v_portfolio_summary, v_performance_stats';
END $$;
