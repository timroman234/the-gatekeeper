# The Gatekeeper — Security Review

> **Scope:** LangGraph pipeline security controls, data handling, and production readiness gaps.
> **Date:** 2026-06-20

---

## Part 1 — Security Controls Currently in Place

### 1. Prompt Injection Mitigation via Template Variables
**Files:** `src/agents/triage.py`, `src/agents/drafter.py`

Email content (sender, subject, body) is always passed as named template variables to `ChatPromptTemplate.from_messages()`, never concatenated directly into the prompt string with f-strings. This is the single most important injection defence: it enforces a hard boundary between the *instruction* layer and the *data* layer, preventing a malicious email body from rewriting the system prompt.

Both nodes also include an explicit `SECURITY NOTICE` in their system prompt instructing the model to ignore commands embedded in email fields.

```python
# Safe — email fields arrive as data, not instruction text
chain.invoke({"sender": email.sender, "subject": email.subject, "body": email.body})
```

### 2. Structured Output Constraint on Triage
**File:** `src/agents/triage.py`

The triage LLM is bound to `TriageResult` via `llm.with_structured_output(TriageResult)`. The `category` field is a `Literal` type constrained to exactly five values. This means even if a prompt injection attack partially succeeds, the LLM cannot output an arbitrary category or embed rogue instructions in the classification result — pydantic validation will reject anything outside the allowed set.

### 3. Human-in-the-Loop Interrupt Before Send
**File:** `src/graph.py`

```python
workflow.compile(checkpointer=checkpointer, interrupt_before=["send_email"])
```

The graph halts at the `send_email` node and cannot resume without explicit human action (`graph.update_state()` + `graph.invoke(None, ...)`). No email is ever dispatched autonomously. This is the last line of defence against a compromised draft reaching a real recipient.

### 4. SqliteSaver Checkpoint Persistence
**File:** `src/graph.py`

`SqliteSaver` persists the full `GatekeeperState` after every node execution. This serves two security purposes:
- **Replay integrity:** If the Streamlit process restarts between triage and approval, the state (including the original email and the LLM's reasoning) is recovered exactly — an attacker cannot substitute a different email into an already-approved checkpoint thread.
- **Thread isolation:** Each email runs as a separate graph thread keyed by `email.id`. A compromised or malformed email in one thread cannot affect the state of any other thread.

### 5. Parameterised SQL — No SQL Injection
**File:** `src/database/local_store.py`

Every database operation uses `?` parameter binding. Email content, thread IDs, and draft bodies are never concatenated into SQL strings. SQLite's foreign key enforcement (`PRAGMA foreign_keys=ON`) and WAL journaling (`PRAGMA journal_mode=WAL`) are also enabled.

### 6. OAuth2 Scoped Gmail Access
**File:** `src/providers/google_prov.py`

The Gmail OAuth flow requests only two scopes:
- `gmail.readonly` — fetch unread messages
- `gmail.send` — send replies

No access to contacts, calendar, Drive, or full account management is granted. The OAuth token is refreshed automatically and stored locally in `token.json`.

### 7. Minimal Email Body Extraction
**File:** `src/providers/google_prov.py`

`_extract_body()` only extracts `text/plain` MIME parts. HTML email bodies, embedded images, and attachments are silently ignored. This prevents HTML-formatted phishing content (e.g., hidden `<script>` tags or CSS-based exfiltration) from ever reaching the LLM or being rendered in the UI.

---

## Part 2 — Security Gaps: Critical Review for Production

### CRITICAL

---

#### C1. No Authentication on the Streamlit UI
**File:** `app/main.py`

Anyone who can reach `http://localhost:8501` — or wherever this is deployed — can read every email in your inbox and send replies as you. There is no login screen, no session token, no IP allowlist.

**Fix:** Place the app behind an authenticated reverse proxy (Nginx + `auth_request`, Cloudflare Access, or similar) or use `streamlit-authenticator`. At minimum, bind only to `127.0.0.1` in production and require VPN or SSH tunnel access.

---

#### C2. Email Content Sent to LangSmith by Default
**File:** `config/settings.py`

```python
langchain_tracing_v2: bool = True
```

With tracing enabled, every email body, sender address, subject, generated draft, and LLM reasoning string is transmitted to Langchain's LangSmith cloud service and stored there. This is a significant **data privacy and compliance risk** — particularly if emails contain PII, financial data, legal correspondence, or anything covered by GDPR, HIPAA, or NDA obligations.

**Fix:** Set `LANGCHAIN_TRACING_V2=false` in production, or use a self-hosted LangSmith instance, or carefully review what LangSmith's data retention and DPA policies allow for your use case.

---

#### C3. OAuth Token and API Keys Stored as Plaintext on Disk
**Files:** `token.json`, `.env`, `config/settings.py`

`token.json` is a full OAuth2 refresh token. Anyone who can read the filesystem can use it indefinitely to access Gmail (send/read). Similarly, `.env` holds the Anthropic API key and LangChain API key in plaintext.

**Fix:**
- Encrypt `token.json` at rest or store it in the OS keychain / a secrets manager (AWS Secrets Manager, HashiCorp Vault, Azure Key Vault).
- Never commit `.env`, `token.json`, or `credentials.json` to git. Verify `.gitignore` covers all three.
- For cloud deployment, inject secrets via environment variables from the platform (Railway, Render, ECS task role, etc.) rather than file-based secrets.

---

#### C4. No HTTPS — Email Content Transmitted in Plaintext
**File:** deployment (no TLS config present)

Streamlit runs HTTP on port 8501. Any email body, draft, or API response crossing the network is unencrypted.

**Fix:** Put the app behind a TLS-terminating reverse proxy (Nginx, Caddy, Traefik). Caddy handles certificate renewal automatically with a single config line.

---

### HIGH

---

#### H1. Prompt Injection Defence is Best-Effort Only
**Files:** `src/agents/triage.py`, `src/agents/drafter.py`

The `SECURITY NOTICE` in each system prompt is a soft guardrail. A sufficiently crafted email body can still cause jailbreaks — especially with GPT-4o which has been shown to be susceptible to multi-step indirect injection. A malicious email body could potentially manipulate the drafter into generating a reply that forwards sensitive thread history, exfiltrates data via a URL, or impersonates the user in a damaging way.

**Fix:**
- Add a post-LLM output validation step that checks the generated draft for red flags: external URLs not present in the original thread, suspicious headers, or unexpected length changes.
- Consider running a second, cheaper "safety checker" LLM call on the draft before it's shown to the user.
- Log and alert on any triage classification that deviates significantly from the model's reasoning (e.g., a body saying "ignore all previous instructions" was classified as "informational").

---

#### H2. No Rate Limiting on Email Send
**Files:** `src/graph.py`, `app/main.py`

There is no limit on how many emails can be sent per hour. An attacker with UI access (see C1) or a bug in the approval flow could trigger a burst of outbound emails, potentially causing account suspension or reputational damage.

**Fix:** Add a send counter in `LocalStore` with a per-hour cap. Track `sent_at` timestamps in the `drafts` table and enforce a limit (e.g., 20 sends/hour) in `send_email_node`.

---

#### H3. SQLite Not Safe for Multi-User / Multi-Process Production
**File:** `src/graph.py`, `src/database/local_store.py`

`check_same_thread=False` is used to share the SQLite connection across Streamlit's internal threads, but SQLite does not support concurrent writes from multiple processes. If a second Streamlit worker or a background job accesses `gatekeeper.db` or `checkpoints.db` simultaneously, data corruption is possible.

**Fix:** For single-user local use, this is acceptable. For any production deployment serving more than one user or process, migrate to PostgreSQL with `langgraph-checkpoint-postgres` for checkpoints and a proper connection pool (e.g., `psycopg2` with `pgbouncer`) for the email store.

---

#### H4. Sender Name Injected into HTML Without Escaping
**File:** `app/main.py`

```python
sender_short = email.sender.split("<")[0].strip()[:28]
st.markdown(f"<span ...>{sender_short}</span>", unsafe_allow_html=True)
```

The `split("<")[0]` incidentally strips anything after a `<` character, which blocks the most obvious XSS vector. However, a sender display name containing `">`, `&`, or JavaScript event attributes (e.g., `onmouseover=alert(1) x="`) could still inject into the rendered HTML.

**Fix:** HTML-escape all email-derived content before injecting into `unsafe_allow_html` markup:

```python
import html
sender_safe = html.escape(sender_short)
```

---

#### H5. No Audit Trail of Approvals
**Files:** `src/database/local_store.py`, `src/graph.py`

The `drafts` table records `status` ('pending', 'sent', 'rejected') but does not record *when* the action was taken, *what* the user's final edited text was before sending, or *which user* approved it. For any business use, an immutable audit log is required for accountability.

**Fix:** Add an `approved_at` timestamp and `final_body` column to the `drafts` table. Log approval/rejection events with the session context to an append-only audit table.

---

### MEDIUM

---

#### M1. No Input Size Limits on Email Body
**Files:** `src/providers/google_prov.py`, `src/agents/triage.py`

An email with a 500,000-character body is passed to the LLM without truncation. This can cause unexpectedly high API costs, context window overflow errors (which surface as unhandled exceptions), and very slow triage runs that block the UI.

**Fix:** Truncate `email.body` to a reasonable maximum (e.g., 8,000 characters) before passing to LLM nodes. Store the full body in the database but feed the LLM a truncated version with a note like `[body truncated at 8000 chars]`.

---

#### M2. LangSmith URL Constructed with Unvalidated Email ID
**File:** `app/main.py`

```python
return f"https://smith.langchain.com/projects/{settings.langchain_project}?filter=email-{email_id}"
```

`email_id` comes from the Gmail API, which is safe in practice, but it is not validated or URL-encoded before being interpolated into the link. A malformed ID could produce a broken or misleading URL.

**Fix:** URL-encode the `email_id`:
```python
from urllib.parse import quote
return f"https://smith.langchain.com/projects/{quote(settings.langchain_project)}?filter=email-{quote(email_id)}"
```

---

#### M3. InstalledAppFlow OAuth Not Suitable for Server Deployment
**File:** `src/providers/google_prov.py`

`InstalledAppFlow.run_local_server(port=0)` opens a browser window to complete OAuth consent. This works on a developer's machine but will hang indefinitely on a headless server.

**Fix:** For server deployment, pre-generate `token.json` on a local machine and copy it to the server. Add a startup health check that validates the token is present and not expired. Document the re-authentication procedure for when the refresh token expires.

---

#### M4. Graph Singleton Not Thread-Safe Under Streamlit
**File:** `src/graph.py`

```python
_graph = None

def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph
```

Streamlit can invoke handlers from multiple threads. Two concurrent requests hitting `get_graph()` simultaneously when `_graph is None` could call `build_graph()` twice, opening two SQLite connections to `checkpoints.db`, leading to a race condition.

**Fix:**

```python
import threading
_lock = threading.Lock()

def get_graph():
    global _graph
    with _lock:
        if _graph is None:
            _graph = build_graph()
    return _graph
```

---

#### M5. Rejection Reason Stored But Never Acted On
**File:** `src/graph.py`, `app/main.py`

When a draft is rejected, `rejection_reason` is written to graph state and `is_processed` is set to `True` in the DB, but the reason is never stored in the `drafts` table or used to improve future drafts. More importantly, the email itself gets no further action — it stays unread in Gmail with no follow-up.

This is not a security vulnerability per se, but it is a process gap: rejected emails silently disappear from the workflow with no record of why.

**Fix:** Add a `rejection_reason` column to the `drafts` table. Consider a "regenerate draft" flow instead of simply discarding the work.

---

## Summary Table

| ID | Severity | Area | Status |
|----|----------|------|--------|
| C1 | Critical | Authentication | Missing |
| C2 | Critical | Data Privacy (LangSmith) | Active risk |
| C3 | Critical | Secrets Management | Plaintext on disk |
| C4 | Critical | Transport Security | No TLS |
| H1 | High | Prompt Injection | Partial mitigation only |
| H2 | High | Rate Limiting | Missing |
| H3 | High | Database Concurrency | SQLite only |
| H4 | High | XSS via Sender Name | Partial mitigation only |
| H5 | High | Audit Trail | Insufficient |
| M1 | Medium | Input Validation (body size) | Missing |
| M2 | Medium | URL Encoding | Missing |
| M3 | Medium | OAuth Headless Deployment | Not handled |
| M4 | Medium | Thread Safety (graph singleton) | Race condition |
| M5 | Medium | Rejection Flow | No persistence |

---

*The most impactful single change for production is **C2** (disable LangSmith tracing or self-host it) — it is currently exfiltrating every email you process to a third-party service. The most impactful security posture change is **C1** (authentication) since the entire pipeline — inbox read, draft generation, and email send — is currently open to anyone with network access.*
