"""Researcher LangGraph node — fetches thread context from SQLite."""
from src.agents.state import GatekeeperState
from src.database.local_store import LocalStore
from config.settings import settings


def researcher_node(state: GatekeeperState) -> dict:
    """Fetch thread history for the current email from the local SQLite store.

    Returns a partial state update: {'project_context': str}.
    The context is a formatted string of prior messages in the same thread,
    ordered oldest to newest. If no history exists, returns a placeholder.
    """
    email = state["current_email"]
    if email is None or not email.thread_id:
        return {"project_context": "No prior context found for this email."}

    with LocalStore(settings.db_path) as store:
        history = store.get_thread_history(email.thread_id)

    if not history:
        return {"project_context": "No prior context found for this thread."}

    lines: list[str] = ["=== Thread History (oldest to newest) ===\n"]
    for i, msg in enumerate(history, start=1):
        lines.append(
            f"--- Message {i} ---\n"
            f"From: {msg['sender']}\n"
            f"Date: {msg['received_at']}\n"
            f"Subject: {msg['subject']}\n"
            f"Body:\n{msg['body']}\n"
        )

    return {"project_context": "\n".join(lines)}
