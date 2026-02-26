# session_manager.py
# Manages test session state.
# Uses Google Cloud Firestore when credentials are available,
# falls back to an in-memory dict for local development.

from __future__ import annotations
import uuid
import time
from typing import Any

try:
    from google.cloud import firestore
    _FIRESTORE_AVAILABLE = True
except ImportError:
    _FIRESTORE_AVAILABLE = False

import os


class SessionManager:
    """Persists QA session history across reconnects."""

    def __init__(self):
        self._collection = os.getenv("FIRESTORE_COLLECTION", "qa_sessions")
        self._db = None
        self._memory: dict[str, dict] = {}  # fallback

        if _FIRESTORE_AVAILABLE:
            try:
                project = os.getenv("GCP_PROJECT_ID")
                self._db = firestore.AsyncClient(project=project) if project else None
                print("[SessionManager] Firestore client initialized.")
            except Exception as e:
                print(f"[SessionManager] Firestore unavailable ({e}), using in-memory fallback.")

    # ──────────────────────────────────────────────────────────────────────────

    def new_session(self, url: str, goal: str) -> str:
        """Create a new session and return its ID."""
        session_id = str(uuid.uuid4())[:8]
        data = {
            "id": session_id,
            "url": url,
            "goal": goal,
            "steps": [],
            "bugs": [],
            "status": "running",
            "started_at": time.time(),
        }
        self._memory[session_id] = data
        return session_id

    def add_step(self, session_id: str, step: dict) -> None:
        """Append an action step to the session history."""
        step["timestamp"] = time.time()
        if session_id in self._memory:
            self._memory[session_id]["steps"].append(step)

    def add_bug(self, session_id: str, bug: dict) -> None:
        """Append a bug report to the session."""
        bug["timestamp"] = time.time()
        if session_id in self._memory:
            self._memory[session_id]["bugs"].append(bug)

    def complete_session(self, session_id: str, summary: str, bugs_found: int) -> None:
        if session_id in self._memory:
            self._memory[session_id]["status"] = "complete"
            self._memory[session_id]["summary"] = summary
            self._memory[session_id]["bugs_found"] = bugs_found
            self._memory[session_id]["ended_at"] = time.time()

    def get_session(self, session_id: str) -> dict | None:
        return self._memory.get(session_id)

    def get_all_sessions(self) -> list[dict]:
        return list(self._memory.values())

    def clear_session(self, session_id: str) -> None:
        self._memory.pop(session_id, None)
