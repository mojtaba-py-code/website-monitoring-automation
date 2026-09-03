-- =============================================================================
-- Website Monitoring Automation — SQLite schema (reference)
-- -----------------------------------------------------------------------------
-- Created automatically at runtime by src/webmon/database.py. Kept here for
-- reference, code review and external tooling (DB browsers, BI). You do not
-- need to run it manually.
-- =============================================================================

-- Every individual probe result (http/ssl/dns/port/ping/content/api/change).
CREATE TABLE IF NOT EXISTS checks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    target     TEXT NOT NULL,
    kind       TEXT NOT NULL,
    status     TEXT NOT NULL,          -- up | warning | degraded | down | unknown
    ok         INTEGER NOT NULL,
    latency_ms REAL,
    message    TEXT,
    details    TEXT,                    -- JSON blob of probe-specific detail
    ts         TEXT NOT NULL            -- ISO-8601 UTC
);

-- Aggregated per-cycle result for a target (drives availability analytics).
CREATE TABLE IF NOT EXISTS results (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    target           TEXT NOT NULL,
    url              TEXT NOT NULL,
    status           TEXT NOT NULL,
    ok               INTEGER NOT NULL,
    response_time_ms REAL,
    ts               TEXT NOT NULL
);

-- Status-change events (up->down, down->up, warning...) for incident timelines.
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    target      TEXT NOT NULL,
    from_status TEXT,
    to_status   TEXT NOT NULL,
    message     TEXT,
    ts          TEXT NOT NULL
);

-- Alerts actually raised, with the channels they were delivered to.
CREATE TABLE IF NOT EXISTS alerts (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    target   TEXT NOT NULL,
    severity TEXT NOT NULL,            -- info | warning | critical
    title    TEXT NOT NULL,
    message  TEXT NOT NULL,
    channels TEXT,                      -- JSON array of channel names
    ts       TEXT NOT NULL
);

-- Per-target state used for flap-suppression and change detection.
CREATE TABLE IF NOT EXISTS state (
    target               TEXT PRIMARY KEY,
    last_status          TEXT,
    last_change_ts       TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_alert_ts        TEXT,
    dns_fingerprint      TEXT,          -- to detect DNS record changes
    content_checksum     TEXT           -- to detect page content changes
);

CREATE INDEX IF NOT EXISTS idx_checks_target_ts ON checks(target, ts);
CREATE INDEX IF NOT EXISTS idx_results_target_ts ON results(target, ts);
CREATE INDEX IF NOT EXISTS idx_events_target_ts ON events(target, ts);
