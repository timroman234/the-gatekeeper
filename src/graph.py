"""LangGraph DAG definition for The Contextual Gatekeeper.

Graph topology:
    triage_node -> researcher_node -> drafter_node -> [INTERRUPT] -> send_email_node -> END

Per-email execution: each email runs as a separate thread keyed by email.id.
SqliteSaver provides checkpoint persistence across Streamlit reruns.
"""
import logging
import sqlite3
from typing import Optional

from langgraph.graph import END, StateGraph
try:
    from langgraph_checkpoint_sqlite import SqliteSaver
except ImportError:
    from langgraph.checkpoint.sqlite import SqliteSaver  # type: ignore[no-redef]

from config.settings import settings
from src.agents.drafter import drafter_node
from src.agents.researcher import researcher_node
from src.agents.state import GatekeeperState
from src.agents.triage import triage_node
from src.database.local_store import LocalStore
from src.providers.base import EmailMessage
from src.providers.google_prov import GmailProvider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# send_email node — runs AFTER human approval in Streamlit
# ---------------------------------------------------------------------------

def send_email_node(state: GatekeeperState) -> dict:
    """Send the approved draft via GmailProvider and mark the email processed.

    Uses user_modifications if the human edited the draft; otherwise uses
    generated_draft. Persists draft record and marks email as processed.
    """
    email: Optional[EmailMessage] = state["current_email"]
    if email is None:
        logger.warning("send_email_node called with no current_email — skipping")
        return {}

    reply_body = state.get("user_modifications") or state.get("generated_draft") or ""

    provider = GmailProvider(
        credentials_path=settings.gmail_credentials_path,
        token_path=settings.gmail_token_path,
    )
    success = provider.send_reply(email.id, reply_body)

    with LocalStore(settings.db_path) as store:
        draft_id = store.save_draft(email.id, reply_body)
        status = "sent" if success else "failed"
        store.update_draft_status(draft_id, status)
        if success:
            store.mark_processed(email.id)

    if not success:
        logger.error("Failed to send reply for email %s", email.id)

    return {}


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_graph():
    """Build and compile the Gatekeeper LangGraph.

    Returns a CompiledStateGraph with SqliteSaver checkpoints and
    interrupt_before=['send_email'] so the Streamlit UI can review.
    """
    settings.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

    workflow = StateGraph(GatekeeperState)

    workflow.add_node("triage", triage_node)
    workflow.add_node("researcher", researcher_node)
    workflow.add_node("drafter", drafter_node)
    workflow.add_node("send_email", send_email_node)

    workflow.set_entry_point("triage")
    workflow.add_edge("triage", "researcher")
    workflow.add_edge("researcher", "drafter")
    workflow.add_edge("drafter", "send_email")
    workflow.add_edge("send_email", END)

    conn = sqlite3.connect(str(settings.checkpoint_path), check_same_thread=False)
    checkpointer = SqliteSaver(conn)

    return workflow.compile(
        checkpointer=checkpointer,
        interrupt_before=["send_email"],
    )


# ---------------------------------------------------------------------------
# Module-level singleton — built once per process
# ---------------------------------------------------------------------------
_graph = None


def get_graph():
    """Return the cached compiled graph, building it on first call."""
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph
