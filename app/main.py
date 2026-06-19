"""The Contextual Gatekeeper — Streamlit UI with IBM Carbon Light styling.

Run with: uv run streamlit run app/main.py
"""
import os
import streamlit as st

# ---------------------------------------------------------------------------
# IBM Carbon Light design tokens — injected before any st.* render calls
# ---------------------------------------------------------------------------
_CARBON_CSS = """
<style>
  /* IBM Carbon Design System — Light theme tokens */
  :root {
    --cds-background: #ffffff;
    --cds-background-hover: #e8e8e8;
    --cds-background-active: #c6c6c6;
    --cds-layer-01: #f4f4f4;
    --cds-layer-02: #ffffff;
    --cds-layer-hover-01: #e8e8e8;
    --cds-border-subtle-01: #e0e0e0;
    --cds-border-strong-01: #8d8d8d;
    --cds-text-primary: #161616;
    --cds-text-secondary: #525252;
    --cds-text-placeholder: #a8a8a8;
    --cds-link-primary: #0f62fe;
    --cds-link-primary-hover: #0043ce;
    --cds-interactive: #0f62fe;
    --cds-button-primary: #0f62fe;
    --cds-button-primary-hover: #0353e9;
    --cds-button-danger: #da1e28;
    --cds-button-danger-hover: #b81921;
    --cds-support-success: #198038;
    --cds-support-warning: #f1c21b;
    --cds-support-error: #da1e28;
    --cds-support-info: #0043ce;
    --cds-tag-urgent: #da1e28;
    --cds-tag-action: #f1c21b;
    --cds-tag-info: #0043ce;
    --cds-tag-spam: #8d8d8d;
    --cds-tag-newsletter: #198038;
    font-family: 'IBM Plex Sans', 'Helvetica Neue', Arial, sans-serif;
  }

  /* Override Streamlit default chrome */
  .stApp { background-color: var(--cds-background); }
  .block-container { padding-top: 1rem; }
  h1, h2, h3 { font-family: 'IBM Plex Sans', sans-serif; color: var(--cds-text-primary); }
  .stButton > button {
    border-radius: 0;
    font-family: 'IBM Plex Sans', sans-serif;
    font-size: 0.875rem;
    font-weight: 400;
  }
  .stTextArea textarea {
    border: 1px solid var(--cds-border-strong-01);
    border-radius: 0;
    font-family: 'IBM Plex Mono', monospace;
    background-color: var(--cds-layer-01);
  }
  /* Email list item card */
  .email-card {
    background: var(--cds-layer-01);
    border-left: 4px solid var(--cds-border-subtle-01);
    padding: 0.75rem 1rem;
    margin-bottom: 0.5rem;
  }
  /* Category tags */
  .tag {
    display: inline-block;
    padding: 2px 8px;
    font-size: 0.75rem;
    font-weight: 600;
    border-radius: 0;
    margin-left: 0.5rem;
  }
  .tag-urgent { background: var(--cds-tag-urgent); color: #fff; }
  .tag-action_required { background: var(--cds-tag-action); color: #161616; }
  .tag-informational { background: var(--cds-tag-info); color: #fff; }
  .tag-spam { background: var(--cds-tag-spam); color: #fff; }
  .tag-newsletter { background: var(--cds-tag-newsletter); color: #fff; }
</style>
"""

# ---------------------------------------------------------------------------
# Page config — must be the very first Streamlit call
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="The Contextual Gatekeeper",
    page_icon="\U0001f512",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(_CARBON_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Lazy imports (after st.set_page_config)
# ---------------------------------------------------------------------------
from pathlib import Path

from config.settings import settings
from src.agents.state import GatekeeperState
from src.database.local_store import LocalStore
from src.graph import get_graph
from src.providers.base import EmailMessage
from src.providers.google_prov import GmailProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_data_dir() -> None:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)


def _tag_html(category: str) -> str:
    css_class = f"tag-{category}"
    label = category.upper().replace("_", " ")
    return f'<span class="tag {css_class}">{label}</span>'


def _fetch_emails() -> list:
    try:
        provider = GmailProvider(
            credentials_path=settings.gmail_credentials_path,
            token_path=settings.gmail_token_path,
        )
        return provider.fetch_unread_emails(max_results=settings.email_max_results)
    except Exception as exc:
        st.error(f"Failed to fetch emails: {exc}")
        return []


def _save_emails_to_db(emails: list) -> None:
    with LocalStore(settings.db_path) as store:
        for email in emails:
            store.save_email(email)


def _run_graph_for_email(email: EmailMessage):
    graph = get_graph()
    config = {"configurable": {"thread_id": email.id}}
    initial_state = {
        "current_email": email,
        "extracted_metadata": {},
        "project_context": None,
        "generated_draft": None,
        "is_approved": False,
        "user_modifications": None,
        "rejection_reason": None,
    }
    try:
        return graph.invoke(initial_state, config=config)
    except Exception as exc:
        st.error(f"Graph error for email {email.id}: {exc}")
        return None


def _resume_graph_approved(email_id: str, edited_text: str) -> None:
    graph = get_graph()
    config = {"configurable": {"thread_id": email_id}}
    graph.update_state(config, {"user_modifications": edited_text, "is_approved": True})
    graph.invoke(None, config=config)


def _resume_graph_rejected(email_id: str, reason: str) -> None:
    graph = get_graph()
    config = {"configurable": {"thread_id": email_id}}
    graph.update_state(config, {"rejection_reason": reason, "is_approved": False})
    with LocalStore(settings.db_path) as store:
        store.mark_processed(email_id)


def _langsmith_url(email_id: str):
    if not settings.langchain_tracing_v2:
        return None
    return f"https://smith.langchain.com/projects/{settings.langchain_project}?filter=email-{email_id}"


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
def _init_session() -> None:
    if "emails" not in st.session_state:
        st.session_state.emails = []
    if "selected_email_id" not in st.session_state:
        st.session_state.selected_email_id = None
    if "graph_states" not in st.session_state:
        st.session_state.graph_states = {}
    if "processed_ids" not in st.session_state:
        st.session_state.processed_ids = set()


# ---------------------------------------------------------------------------
# Sidebar — email list
# ---------------------------------------------------------------------------
def _render_sidebar(emails: list) -> None:
    with st.sidebar:
        st.title("Inbox")
        if st.button("Refresh Inbox", use_container_width=True):
            st.session_state.emails = _fetch_emails()
            _save_emails_to_db(st.session_state.emails)
            st.rerun()

        if not emails:
            st.info("No unread emails. Click Refresh.")
            return

        st.markdown("---")
        for email in emails:
            state = st.session_state.graph_states.get(email.id)
            category = (
                state.get("extracted_metadata", {}).get("category", "...")
                if state
                else "..."
            )
            is_processed = email.id in st.session_state.processed_ids
            suffix = " ✓" if is_processed else ""

            tag_html = _tag_html(category) if category not in ("...", None) else ""
            st.markdown(
                f'<div class="email-card">'
                f"<strong>{email.sender[:30]}</strong>{suffix}<br>"
                f"<small>{email.subject[:50]}</small>{tag_html}"
                f"</div>",
                unsafe_allow_html=True,
            )
            if st.button("Open", key=f"open_{email.id}", use_container_width=True):
                st.session_state.selected_email_id = email.id
                if email.id not in st.session_state.graph_states:
                    with st.spinner(f"Analysing '{email.subject[:30]}...'"):
                        result = _run_graph_for_email(email)
                        if result:
                            st.session_state.graph_states[email.id] = result
                st.rerun()


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------
def _render_main_panel(emails: list) -> None:
    selected_id = st.session_state.selected_email_id
    if selected_id is None:
        st.markdown("## The Contextual Gatekeeper")
        st.info("Select an email from the sidebar to begin review.")
        return

    email = next((e for e in emails if e.id == selected_id), None)
    if email is None:
        st.warning("Email not found. Try refreshing.")
        return

    state = st.session_state.graph_states.get(selected_id)
    category = (state or {}).get("extracted_metadata", {}).get("category", "processing...")
    reasoning = (state or {}).get("extracted_metadata", {}).get("reasoning", "")

    col_hdr, col_tag = st.columns([4, 1])
    with col_hdr:
        st.markdown(f"### {email.subject}")
        st.caption(f"From: **{email.sender}** | Received: {email.received_at}")
    with col_tag:
        if category not in ("processing...", None):
            st.markdown(_tag_html(category), unsafe_allow_html=True)

    if reasoning:
        with st.expander("AI Classification Reasoning"):
            st.write(reasoning)

    st.markdown("---")

    with st.expander("Email Body", expanded=True):
        st.text(email.body)

    context = (state or {}).get("project_context")
    if context and "no prior" not in context.lower():
        with st.expander("Thread History"):
            st.text(context)

    st.markdown("#### AI Draft Reply")

    if state is None:
        st.info("Running AI analysis... please wait.")
        return

    if selected_id in st.session_state.processed_ids:
        st.success("This email has been processed.")
        return

    generated_draft = state.get("generated_draft", "")

    if category in ("spam", "newsletter"):
        st.info(f"Category **{category}** — no reply needed.")
        if st.button("Mark as Processed", key=f"mark_{selected_id}"):
            with LocalStore(settings.db_path) as store:
                store.mark_processed(selected_id)
            st.session_state.processed_ids.add(selected_id)
            st.success("Marked as processed.")
            st.rerun()
        return

    edited_text = st.text_area(
        "Review and edit the draft before sending:",
        value=generated_draft,
        height=300,
        key=f"draft_{selected_id}",
    )

    col_approve, col_reject = st.columns(2)

    with col_approve:
        if st.button(
            "Approve & Send",
            key=f"approve_{selected_id}",
            use_container_width=True,
            type="primary",
        ):
            with st.spinner("Sending email..."):
                _resume_graph_approved(selected_id, edited_text)
            st.session_state.processed_ids.add(selected_id)
            st.success("Email sent successfully!")
            trace_url = _langsmith_url(selected_id)
            if trace_url:
                st.caption(f"[View LangSmith trace]({trace_url})")
            st.rerun()

    with col_reject:
        rejection_reason = st.text_input(
            "Rejection reason (optional):",
            key=f"reject_reason_{selected_id}",
        )
        if st.button(
            "Reject Draft",
            key=f"reject_{selected_id}",
            use_container_width=True,
        ):
            _resume_graph_rejected(selected_id, rejection_reason)
            st.session_state.processed_ids.add(selected_id)
            st.warning("Draft rejected. Email will not be sent.")
            st.rerun()

    trace_url = _langsmith_url(selected_id)
    if trace_url:
        st.caption(f"[View LangSmith trace]({trace_url})")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    _ensure_data_dir()
    _init_session()

    if not st.session_state.emails:
        with st.spinner("Connecting to Gmail..."):
            st.session_state.emails = _fetch_emails()
            _save_emails_to_db(st.session_state.emails)

    _render_sidebar(st.session_state.emails)
    _render_main_panel(st.session_state.emails)


if __name__ == "__main__":
    main()
