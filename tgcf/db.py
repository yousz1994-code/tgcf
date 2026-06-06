"""PostgreSQL database layer for tgcf statistics and connection management."""

import os
import logging
from datetime import datetime
from typing import Optional
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.getenv("DATABASE_URL")


def get_conn():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    """Create all required tables."""
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS connections (
                id SERIAL PRIMARY KEY,
                con_name TEXT NOT NULL DEFAULT '',
                source_username TEXT NOT NULL DEFAULT '',
                source_id BIGINT DEFAULT 0,
                dest_channels TEXT NOT NULL DEFAULT '',
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                last_activity TIMESTAMP,
                last_forwarded_text TEXT DEFAULT ''
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS message_logs (
                id SERIAL PRIMARY KEY,
                connection_id INTEGER REFERENCES connections(id) ON DELETE CASCADE,
                con_name TEXT NOT NULL DEFAULT '',
                source_id BIGINT DEFAULT 0,
                dest_id BIGINT DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'ok',
                message_preview TEXT DEFAULT '',
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_message_logs_connection
            ON message_logs(connection_id)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_message_logs_status
            ON message_logs(status)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_message_logs_created
            ON message_logs(created_at DESC)
        """)

        conn.commit()
        logging.info("Database tables initialized.")
    except Exception as e:
        conn.rollback()
        logging.error(f"DB init error: {e}")
        raise
    finally:
        cur.close()
        conn.close()


def upsert_connection(con_name: str, source_username: str, source_id: int, dest_channels: str, is_active: bool = True) -> int:
    """Insert or update a connection record, return its id."""
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id FROM connections WHERE con_name = %s AND source_id = %s
        """, (con_name, source_id))
        row = cur.fetchone()
        if row:
            cur.execute("""
                UPDATE connections
                SET source_username=%s, dest_channels=%s, is_active=%s
                WHERE id=%s
                RETURNING id
            """, (source_username, dest_channels, is_active, row[0]))
            cid = cur.fetchone()[0]
        else:
            cur.execute("""
                INSERT INTO connections (con_name, source_username, source_id, dest_channels, is_active)
                VALUES (%s, %s, %s, %s, %s) RETURNING id
            """, (con_name, source_username, source_id, dest_channels, is_active))
            cid = cur.fetchone()[0]
        conn.commit()
        return cid
    except Exception as e:
        conn.rollback()
        logging.error(f"upsert_connection error: {e}")
        return -1
    finally:
        cur.close()
        conn.close()


def sync_connections_from_config(forwards):
    """Sync tgcf.config.json forwards into the DB connections table."""
    conn = get_conn()
    cur = conn.cursor()
    try:
        for fwd in forwards:
            source = str(fwd.source).strip()
            dest = ", ".join(str(d) for d in fwd.dest)
            name = fwd.con_name or source

            cur.execute("SELECT id FROM connections WHERE con_name=%s", (name,))
            row = cur.fetchone()
            if row:
                cur.execute("""
                    UPDATE connections SET source_username=%s, dest_channels=%s, is_active=%s
                    WHERE id=%s
                """, (source, dest, fwd.use_this, row[0]))
            else:
                cur.execute("""
                    INSERT INTO connections (con_name, source_username, source_id, dest_channels, is_active)
                    VALUES (%s, %s, %s, %s, %s)
                """, (name, source, 0, dest, fwd.use_this))
        conn.commit()
    except Exception as e:
        conn.rollback()
        logging.error(f"sync_connections error: {e}")
    finally:
        cur.close()
        conn.close()


def log_message(connection_id: Optional[int], con_name: str, source_id: int, dest_id: int, status: str, message_preview: str = ""):
    """Record a forwarding attempt."""
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO message_logs (connection_id, con_name, source_id, dest_id, status, message_preview)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (connection_id, con_name, source_id, dest_id, status, message_preview[:200]))

        if status == "ok" and connection_id:
            cur.execute("""
                UPDATE connections
                SET last_activity=NOW(), last_forwarded_text=%s
                WHERE id=%s
            """, (message_preview[:200], connection_id))

        conn.commit()
    except Exception as e:
        conn.rollback()
        logging.error(f"log_message error: {e}")
    finally:
        cur.close()
        conn.close()


def get_all_connections():
    """Return all connections with statistics."""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT
                c.*,
                COUNT(ml.id) AS total_received,
                SUM(CASE WHEN ml.status='ok' THEN 1 ELSE 0 END) AS total_forwarded,
                SUM(CASE WHEN ml.status='fail' THEN 1 ELSE 0 END) AS total_failed
            FROM connections c
            LEFT JOIN message_logs ml ON ml.connection_id = c.id
            GROUP BY c.id
            ORDER BY c.created_at DESC
        """)
        return cur.fetchall()
    except Exception as e:
        logging.error(f"get_all_connections error: {e}")
        return []
    finally:
        cur.close()
        conn.close()


def get_connection_by_id(cid: int):
    """Return single connection with stats."""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT
                c.*,
                COUNT(ml.id) AS total_received,
                SUM(CASE WHEN ml.status='ok' THEN 1 ELSE 0 END) AS total_forwarded,
                SUM(CASE WHEN ml.status='fail' THEN 1 ELSE 0 END) AS total_failed
            FROM connections c
            LEFT JOIN message_logs ml ON ml.connection_id = c.id
            WHERE c.id = %s
            GROUP BY c.id
        """, (cid,))
        return cur.fetchone()
    except Exception as e:
        logging.error(f"get_connection_by_id error: {e}")
        return None
    finally:
        cur.close()
        conn.close()


def get_recent_activity(connection_id: int, limit: int = 5):
    """Return last N log entries for a connection."""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT * FROM message_logs
            WHERE connection_id = %s
            ORDER BY created_at DESC
            LIMIT %s
        """, (connection_id, limit))
        return cur.fetchall()
    except Exception as e:
        logging.error(f"get_recent_activity error: {e}")
        return []
    finally:
        cur.close()
        conn.close()


def set_connection_active(cid: int, active: bool):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE connections SET is_active=%s WHERE id=%s", (active, cid))
        conn.commit()
    except Exception as e:
        conn.rollback()
        logging.error(f"set_connection_active error: {e}")
    finally:
        cur.close()
        conn.close()


def delete_connection(cid: int):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM connections WHERE id=%s", (cid,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        logging.error(f"delete_connection error: {e}")
    finally:
        cur.close()
        conn.close()


def update_connection_source_id(cid: int, source_id: int):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE connections SET source_id=%s WHERE id=%s", (source_id, cid))
        conn.commit()
    except Exception as e:
        conn.rollback()
        logging.error(f"update_connection_source_id error: {e}")
    finally:
        cur.close()
        conn.close()


def get_global_stats():
    """Return global forwarding statistics."""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT
                COUNT(DISTINCT connection_id) AS active_connections,
                COUNT(*) AS total_messages,
                SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) AS total_forwarded,
                SUM(CASE WHEN status='fail' THEN 1 ELSE 0 END) AS total_failed
            FROM message_logs
        """)
        return cur.fetchone()
    except Exception as e:
        logging.error(f"get_global_stats error: {e}")
        return {}
    finally:
        cur.close()
        conn.close()


def get_today_stats():
    """Return today's forwarding statistics."""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT
                COUNT(*) AS total_messages,
                SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) AS total_forwarded,
                SUM(CASE WHEN status='fail' THEN 1 ELSE 0 END) AS total_failed
            FROM message_logs
            WHERE created_at >= CURRENT_DATE
        """)
        return cur.fetchone()
    except Exception as e:
        logging.error(f"get_today_stats error: {e}")
        return {}
    finally:
        cur.close()
        conn.close()


# Initialize on import
try:
    init_db()
except Exception as e:
    logging.warning(f"DB init skipped: {e}")
