"""The Contextual Gatekeeper — Streamlit UI with IBM Carbon Light styling.

Run with: uv run streamlit run app/main.py
"""
import os
from dotenv import load_dotenv
load_dotenv()  # puts .env values into os.environ so ChatAnthropic can find ANTHROPIC_API_KEY

import streamlit as st
import streamlit.components.v1 as components

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
  .block-container { padding-top: 3rem; max-width: 100% !important; }
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
  /* Compact sidebar email cards */
  .email-card {
    background: var(--cds-layer-01);
    border-left: 3px solid var(--cds-border-subtle-01);
    padding: 0.35rem 0.6rem;
    margin-bottom: 0.25rem;
    line-height: 1.3;
  }
  /* Sidebar email list spacing */
  [data-testid="stSidebar"] .stMarkdown { margin-bottom: 0 !important; }
  [data-testid="stSidebar"] .stButton { margin-top: 0 !important; margin-bottom: 0.1rem !important; }
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
    page_title="The Gatekeeper",
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
        st.session_state.setdefault("errors", []).append(f"Graph error for {email.id}: {exc}")
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
        if st.button("Refresh Inbox", use_container_width=True, type="primary"):
            st.session_state.emails = _fetch_emails()
            _save_emails_to_db(st.session_state.emails)
            st.rerun()

        if not emails:
            st.info("No unread emails. Click Refresh.")
            return

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
            sender_short = email.sender.split("<")[0].strip()[:28]
            subject_label = email.subject[:42] + suffix
            st.markdown(
                f'<div style="margin-bottom:0.05rem;line-height:1.2">'
                f"<span style='font-size:0.7rem;color:#525252'>{sender_short}</span>{tag_html}"
                f"</div>",
                unsafe_allow_html=True,
            )
            if st.button(subject_label, key=f"open_{email.id}"):
                st.session_state.selected_email_id = email.id
                if email.id not in st.session_state.graph_states:
                    with st.spinner(f"Analysing '{email.subject[:30]}...'"):
                        result = _run_graph_for_email(email)
                        if result:
                            st.session_state.graph_states[email.id] = result
                st.rerun()
            st.markdown("<hr style='margin:0.2rem 0;border-color:#e0e0e0'>", unsafe_allow_html=True)

        components.html("""
<script>
(function () {
  function style() {
    var doc = window.parent.document;
    var btns = Array.from(doc.querySelectorAll('[data-testid="stSidebar"] .stButton button'));
    btns = btns.filter(function(b) { return b.textContent.trim() !== 'Refresh Inbox'; });
    btns.forEach(function (btn) {
      btn.style.background     = 'none';
      btn.style.border         = 'none';
      btn.style.boxShadow      = 'none';
      btn.style.outline        = 'none';
      btn.style.borderRadius   = '0';
      btn.style.padding        = '0';
      btn.style.margin         = '0 0 0.1rem 0';
      btn.style.cursor         = 'pointer';
      btn.style.color          = '#0f62fe';
      btn.style.fontFamily     = "'IBM Plex Sans', sans-serif";
      btn.style.fontSize       = '0.78rem';
      btn.style.fontWeight     = '500';
      btn.style.textDecoration = 'underline';
      btn.style.display        = 'block';
      btn.style.width          = '100%';
      btn.style.textAlign      = 'left';
      btn.style.minHeight      = '0';
      btn.style.height         = 'auto';
      var p = btn.querySelector('p');
      if (p) {
        p.style.textAlign  = 'left';
        p.style.margin     = '0';
        p.style.padding    = '0';
        p.style.whiteSpace = 'normal';
        p.style.display    = 'block';
      }
    });
  }
  new MutationObserver(style).observe(window.parent.document.body, { childList: true, subtree: true });
  style();
  setTimeout(style, 200);
})();
</script>
""", height=0)


# ---------------------------------------------------------------------------
# Sender rule management — home panel
# ---------------------------------------------------------------------------
def _render_manage_rules() -> None:
    """Expander on the home panel for viewing, adding, and deleting sender rules."""
    with st.expander("Manage Sender Rules"):
        with LocalStore(settings.db_path) as store:
            rules = store.list_sender_rules()

        if rules:
            st.markdown("**Existing rules** — click Delete to remove:")
            for rule in rules:
                col_pat, col_cat, col_note, col_del = st.columns([3, 2, 3, 1])
                with col_pat:
                    st.markdown(f"`{rule['pattern']}`")
                with col_cat:
                    st.markdown(_tag_html(rule["override_category"]), unsafe_allow_html=True)
                with col_note:
                    st.caption(rule["note"] or "—")
                with col_del:
                    if st.button("Delete", key=f"del_rule_{rule['id']}"):
                        with LocalStore(settings.db_path) as store:
                            store.delete_sender_rule(rule["id"])
                        st.rerun()
        else:
            st.caption("No rules yet. Add one below.")

        st.markdown("---")
        st.markdown("**Add a new rule:**")
        new_pattern = st.text_input(
            "Email or domain",
            placeholder="tim@example.com  or  @example.com",
            key="new_rule_pattern",
        )
        new_category = st.selectbox(
            "Always classify as",
            ["urgent", "action_required", "informational", "spam", "newsletter"],
            index=1,
            key="new_rule_category",
        )
        new_note = st.text_input(
            "Note (optional)",
            placeholder="e.g. my work domain",
            key="new_rule_note",
        )
        if st.button("Add Rule", key="add_rule_btn", type="primary"):
            if new_pattern.strip():
                with LocalStore(settings.db_path) as store:
                    store.add_sender_rule(new_pattern.strip(), new_category, new_note.strip())
                st.success(f"Rule added: `{new_pattern}` → **{new_category}**")
                st.rerun()
            else:
                st.warning("Enter an email address or domain pattern first.")


# ---------------------------------------------------------------------------
# Reclassify widget — email detail view
# ---------------------------------------------------------------------------
def _render_reclassify_widget(email, current_category: str) -> None:
    """Expander that lets the user correct the AI triage classification."""
    _CATS = ["urgent", "action_required", "informational", "spam", "newsletter"]
    with st.expander("Correct Classification"):
        st.caption(f"Current: **{current_category}**")
        new_cat = st.selectbox(
            "Correct category",
            _CATS,
            index=_CATS.index(current_category) if current_category in _CATS else 2,
            key=f"reclassify_select_{email.id}",
        )
        also_add_rule = st.checkbox(
            f"Always classify emails from this sender as **{new_cat}**",
            key=f"reclassify_add_rule_{email.id}",
        )
        rule_note = ""
        if also_add_rule:
            rule_note = st.text_input(
                "Note (optional)",
                placeholder="e.g. my other email account",
                key=f"reclassify_note_{email.id}",
            )
        if st.button("Save Correction", key=f"reclassify_save_{email.id}"):
            with LocalStore(settings.db_path) as store:
                store.save_correction(
                    email.id, email.sender, email.subject, current_category, new_cat,
                )
                if also_add_rule:
                    store.add_sender_rule(email.sender, new_cat, rule_note)
            if email.id in st.session_state.graph_states:
                st.session_state.graph_states[email.id]["extracted_metadata"]["category"] = new_cat
                st.session_state.graph_states[email.id]["extracted_metadata"]["reasoning"] = (
                    f"Manually reclassified from '{current_category}' to '{new_cat}'."
                )
            st.success(
                f"Saved. Future emails from this sender will be classified as **{new_cat}**."
                if also_add_rule else f"Correction saved as **{new_cat}**."
            )
            st.rerun()


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------
def _render_main_panel(emails: list) -> None:
    selected_id = st.session_state.selected_email_id
    if selected_id is None:
        st.markdown("## The Gatekeeper")
        st.markdown(
            "The Gatekeeper uses AI to triage your inbox, classify each email by urgency, "
            "and draft context-aware replies for your review. "
            "Open any email from the sidebar to inspect its AI analysis and approve or reject "
            "the suggested response before it's sent."
        )
        st.info("Select an email from the sidebar to begin review.")

        # Needs Attention block — urgent/action_required emails not yet processed
        st.markdown(
            '<div style="background:#da1e28;color:#fff;padding:0.5rem 0.75rem;'
            "font-family:'IBM Plex Sans',sans-serif;font-weight:600;"
            'font-size:0.9rem;margin-top:1.5rem;margin-bottom:0.5rem;">&#9888; Needs Attention</div>',
            unsafe_allow_html=True,
        )
        attention_emails = [
            e for e in emails
            if e.id in st.session_state.graph_states
            and st.session_state.graph_states[e.id].get("extracted_metadata", {}).get("category")
            in ("urgent", "action_required")
            and e.id not in st.session_state.processed_ids
        ]
        if attention_emails:
            for e in attention_emails:
                cat = st.session_state.graph_states[e.id]["extracted_metadata"]["category"]
                sender_short = e.sender.split("<")[0].strip()[:30]
                st.markdown(
                    f'<div class="email-card" style="border-left-color:#da1e28;">'
                    f"<strong style='font-size:0.85rem'>{sender_short}</strong>"
                    f"{_tag_html(cat)}<br>"
                    f"<span style='font-size:0.78rem;color:#525252'>{e.subject[:60]}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
                if st.button("Open", key=f"attn_{e.id}", use_container_width=False):
                    st.session_state.selected_email_id = e.id
                    st.rerun()
        else:
            st.markdown(
                "<span style='color:#8d8d8d;font-size:0.85rem'>"
                "No urgent items — check back after refreshing your inbox.</span>",
                unsafe_allow_html=True,
            )

        st.markdown("<br>", unsafe_allow_html=True)
        _render_manage_rules()
        return

    email = next((e for e in emails if e.id == selected_id), None)
    if email is None:
        st.warning("Email not found. Try refreshing.")
        return

    state = st.session_state.graph_states.get(selected_id)
    category = (state or {}).get("extracted_metadata", {}).get("category", "processing...")
    reasoning = (state or {}).get("extracted_metadata", {}).get("reasoning", "")

    if st.button("← Home", key="back_home"):
        st.session_state.selected_email_id = None
        st.rerun()

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

    if category not in ("processing...", "..."):
        _render_reclassify_widget(email, category)

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

    for err in st.session_state.get("errors", []):
        st.error(err)
    st.session_state["errors"] = []

    if not st.session_state.emails:
        with st.spinner("Connecting to Gmail..."):
            st.session_state.emails = _fetch_emails()
            _save_emails_to_db(st.session_state.emails)

    _render_sidebar(st.session_state.emails)
    _render_main_panel(st.session_state.emails)


if __name__ == "__main__":
    main()
