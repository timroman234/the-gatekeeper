# The Contextual Gatekeeper

An AI-powered email triage and reply assistant built with LangGraph, Claude Opus 4.8, and Streamlit.

## Setup

1. Complete GCP pre-flight steps (see implementation plan Task 0).
2. Copy `.env.example` -> `.env` and fill in your keys.
3. Place `credentials.json` (downloaded from GCP) in the project root.
4. Install dependencies: `uv pip install -r requirements.txt`
5. Run the app: `uv run streamlit run app/main.py`

On first launch, a browser window opens for Gmail OAuth. After approving,
`token.json` is saved and future runs skip the browser step.

## Running Tests

```
uv run pytest tests/ -v
```

## Project Structure

See `the_gatekeeper_prd.pdf` for the full product requirements document.