CREATE TABLE IF NOT EXISTS api_observability (
    id BIGSERIAL PRIMARY KEY,
    endpoint TEXT,
    method TEXT,
    origin TEXT,
    triggered_by TEXT,
    status TEXT,
    status_code INTEGER,
    duration_ms INTEGER,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for querying by endpoint and date
CREATE INDEX IF NOT EXISTS idx_api_observability_endpoint ON api_observability(endpoint);
CREATE INDEX IF NOT EXISTS idx_api_observability_created_at ON api_observability(created_at);
