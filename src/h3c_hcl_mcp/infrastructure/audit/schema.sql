-- Audit trail schema for h3c-hcl-mcp
-- Stored at {LOCALAPPDATA}\h3c-hcl-mcp\audit.db

CREATE TABLE IF NOT EXISTS audit_events (
    event_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    caller TEXT DEFAULT 'unknown',
    tool TEXT NOT NULL,
    target TEXT,  -- JSON: serialized dict with project_id, device_id, device_name
    policy_result TEXT DEFAULT 'allowed',
    outcome TEXT NOT NULL DEFAULT 'success',
    change_summary TEXT,
    timestamp TEXT NOT NULL,
    duration_ms REAL DEFAULT 0,
    error_code TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_request ON audit_events(request_id);
CREATE INDEX IF NOT EXISTS idx_audit_tool ON audit_events(tool);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_caller ON audit_events(caller);
