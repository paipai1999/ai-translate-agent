import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from brain.memory import MovieState


def get_db_path(output_dir: str = "outputs") -> str:
    os.makedirs(output_dir, exist_ok=True)
    return os.path.join(output_dir, "movie_metadata.db")


def ensure_db(output_dir: str = "outputs") -> str:
    db_path = get_db_path(output_dir)
    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS movie_state (
                project_dir TEXT PRIMARY KEY,
                movie_name TEXT,
                movie_path TEXT,
                language TEXT,
                whisper_model TEXT,
                progress INTEGER,
                current_phase TEXT,
                updated_at TEXT,
                state_json TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_key_usage (
                masked_key TEXT,
                model_name TEXT,
                used_today INTEGER DEFAULT 0,
                status TEXT DEFAULT 'active',
                utc_date TEXT,
                last_updated_utc TEXT,
                PRIMARY KEY (masked_key, model_name)
            )
            """
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


def save_movie_state(state: MovieState, output_dir: str = "outputs") -> None:
    db_path = ensure_db(output_dir)
    state_json = state.model_dump_json(indent=4)
    now = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO movie_state (
                project_dir,
                movie_name,
                movie_path,
                language,
                whisper_model,
                progress,
                current_phase,
                updated_at,
                state_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                state.project_dir,
                state.movie_name,
                state.movie_path,
                getattr(state, 'language', None) or None,
                getattr(state, 'whisper_model', None) or None,
                int(state.progress or 0),
                state.current_phase or "",
                now,
                state_json,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def load_movie_state(project_dir: str, output_dir: str = "outputs") -> Optional[dict]:
    db_path = get_db_path(output_dir)
    if not os.path.exists(db_path):
        return None

    norm_slash = str(project_dir).replace("/", "\\")
    norm_fwd = str(project_dir).replace("\\", "/")

    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    try:
        cursor = conn.execute(
            "SELECT project_dir, movie_name, movie_path, language, whisper_model, progress, current_phase, updated_at, state_json "
            "FROM movie_state WHERE project_dir = ? OR project_dir = ? OR project_dir = ?",
            (project_dir, norm_slash, norm_fwd)
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "project_dir": row[0],
            "movie_name": row[1],
            "movie_path": row[2],
            "language": row[3],
            "whisper_model": row[4],
            "progress": row[5],
            "current_phase": row[6],
            "updated_at": row[7],
            "state_json": json.loads(row[8]) if row[8] else None,
        }
    finally:
        conn.close()


# Alias for compatibility
get_movie_state = load_movie_state


def delete_movie_state(project_dir: str, output_dir: str = "outputs") -> None:
    db_path = get_db_path(output_dir)
    if not os.path.exists(db_path):
        return

    norm_slash = str(project_dir).replace("/", "\\")
    norm_fwd = str(project_dir).replace("\\", "/")

    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    try:
        conn.execute("DELETE FROM movie_state WHERE project_dir = ? OR project_dir = ? OR project_dir = ?", (project_dir, norm_slash, norm_fwd))
        conn.commit()
    finally:
        conn.close()


def list_movie_states(output_dir: str = "outputs") -> list[dict]:
    db_path = get_db_path(output_dir)
    if not os.path.exists(db_path):
        return []

    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    try:
        cursor = conn.execute(
            "SELECT project_dir, movie_name, language, whisper_model, progress, current_phase, updated_at FROM movie_state ORDER BY updated_at DESC"
        )
        return [
            {
                "project_dir": row[0],
                "movie_name": row[1],
                "language": row[2],
                "whisper_model": row[3],
                "progress": row[4],
                "current_phase": row[5],
                "updated_at": row[6],
            }
            for row in cursor.fetchall()
        ]
    finally:
        conn.close()
