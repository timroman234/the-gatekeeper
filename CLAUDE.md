# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies (Python 3.12 required)
uv pip install -r requirements.txt

# Run the app
uv run streamlit run app/main.py

# Run all tests
uv run pytest tests/ -v

# Run a single test file
uv run pytest tests/test_triage.py -v
```

First launch opens a browser for Gmail OAuth; `token.json` is saved and reused (auto-refreshed) on subsequent runs.

## Environment

Copy `.env.example` to `.env`. Required: `ANTHROPIC_API_KEY`. Optional but recommended: `LANGCHAIN_API_KEY` for LangSmith tracing. Place `credentials.json` (downloaded from GCP Console) in the project root before running.

`LANGCHAIN_TRACING_V2=true` is the default — this sends email content to LangSmith. Set it to `false` for privacy-sensitive use.

## Architecture

See [TECHNICAL.md](TECHNICAL.md) for the full architecture diagram and file reference. See [SECURITY_REVIEW.md](SECURITY_REVIEW.md) for the security audit (26 findings).

### LangGraph DAG

```
triage_node → researcher_node → drafter_node → [INTERRUPT] → send_email_node → END
```

- Each email runs in an isolated LangGraph **thread keyed by `email.id`**, persisted in `data/checkpoints.db` via `SqliteSaver`.
- The graph **halts before `send_email_node`** (`interrupt_before=["send_email"]`). The Streamlit UI resumes it by calling `graph.update_state()` then `graph.invoke(None, config=config)`.
- No email is ever sent without explicit user approval.

### Layers

| Layer | Location | Purpose |
|---|---|---|
| UI | `app/main.py` | Monolithic Streamlit app — sidebar email list, main panel detail/draft/approval |
| Orchestration | `src/graph.py` | LangGraph DAG builder + `send_email_node` |
| Agents | `src/agents/` | `triage`, `researcher`, `drafter` nodes + `GatekeeperState` TypedDict |
| Database | `src/database/local_store.py` | `LocalStore` — SQLite context manager for emails, drafts, sender_rules, triage_corrections |
| Providers | `src/providers/` | `ICommunicationProvider` ABC; `GmailProvider` (implemented); `OutlookProvider` (stub) |
| Config | `config/settings.py` | Pydantic Settings singleton loaded from `.env` |

### Two-layer triage classification

`triage_node` first checks `LocalStore.get_sender_rule(sender)` (exact email match, then `@domain` suffix). If a rule exists, the category is set deterministically without an LLM call. Only if no rule matches does it call the LLM with few-shot examples drawn from the user's recent correction history (`triage_corrections` table).

### LLM in use

**Agents currently use `ChatOpenAI(model="gpt-4o")`** (`langchain-openai`), not Claude — despite the README. `ANTHROPIC_API_KEY` is loaded by `config/settings.py` but not yet wired to the agents. Switching models requires updating the `ChatOpenAI(...)` calls in `src/agents/triage.py` and `src/agents/drafter.py`.

## Streamlit UI patterns

- IBM Carbon Light design system — colors and typography set in `.streamlit/config.toml` and injected CSS at the top of `app/main.py`.
- DOM manipulation (e.g., sidebar button styling) uses `st.components.v1.html(html, height=0)` with `window.parent.document` — **not** `st.markdown`, which does not execute scripts.
- Session state keys: `emails`, `selected_email_id`, `graph_states` (dict of LangGraph outputs keyed by email id), `processed_ids`, `errors`.
