---
name: db-layer
description: PostgreSQL database schema and usage for tgcf statistics
---

## Tables
- `connections` — one row per forwarding connection (source→dest mapping, active flag, timestamps)
- `message_logs` — one row per forward attempt (ok/fail status, preview, timestamps)

## Key functions (tgcf/db.py)
- `init_db()` — creates tables if not exist; called on import and in start_sync
- `upsert_connection()` — insert or update by (con_name, source_id)
- `log_message()` — record a forwarding attempt + update last_activity
- `sync_connections_from_config(forwards)` — syncs tgcf Config.forwards list to DB
- `get_all_connections()` — returns connections WITH aggregated stats (total_received, forwarded, failed)
- `get_recent_activity(cid, limit)` — last N log entries for a connection

## live.py integration
`new_message_handler` calls `_try_log()` after each forward attempt (ok or fail).
DB errors are caught and logged as DEBUG — never crash the forwarding loop.

**Why:** Stats must come from real DB records only per requirements.
