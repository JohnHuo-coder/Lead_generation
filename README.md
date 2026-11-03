# hotel-research-agent

LangGraph agent for hotel / venue research: chat to define criteria, scrape Google Maps candidates, then research each property against each requirement with web evidence.

Repo: [github.com/JohnHuo-coder/hotel-research-agent](https://github.com/JohnHuo-coder/hotel-research-agent)

## What it does

1. **Planner** — conversational agent that locks a research plan (requirements + skills) and a scrape target (location, company type, count), then starts a run.
2. **Orchestrator** — loads that run context, scrapes places via Apify Google Maps, fans out **company × requirement** research jobs, aggregates pass/fail stats, and persists pair-level results.
3. **Research subgraph** — tool-using agent that searches the web, selects URLs, extracts evidence, and verifies claims until it can decide whether the requirement is satisfied.

Plan / scrape / run **status** live in the Agent Server Store (`runtime.store` / `get_store()`). Full per-pair outcomes (claims, sufficient/satisfied, errors) go to the app Postgres table `research_run_results`.

## Repo layout

| Path | Role |
|------|------|
| `src/services/planner_agent.py` | Planner agent + `planner_graph` |
| `src/graphs/orchestrator_graph.py` | Scrape → batch research → aggregate |
| `src/graphs/main_graph.py` | `research_subgraph` (one company × one requirement) |
| `src/components/tools.py` | Research tools (search, extract, verify) |
| `src/services/gmap_scrape.py` | Apify Google Maps scrape (+ retries) |
| `src/services/user_store.py` | Profile/run helpers; prefers platform Store |
| `src/repositories/research_results_repository.py` | Upsert pair results into app DB |
| `src/prompts/` | Planner, research, and domain skill rules |
| `langgraph.json` | Graph entrypoints for `langgraph dev` / deploy |

## Setup

Requires Python 3.12–3.13 and a Postgres database for app tables (e.g. Supabase). Under `langgraph up` / LangSmith deploy, conversation checkpoints and the Agent Server Store use the platform Postgres.

```bash
python -m venv .venv
# Windows: .\.venv\Scripts\activate
pip install -e .
```

Copy `.env` with at least:

- `OPENAI_API_KEY` (or whatever your research LLM uses)
- `TAVILY_API_KEY`
- `APIFY_API_KEY` or `APIFY_TOKEN`
- `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` (app table `research_run_results`)

Create the results table in Postgres (columns must match `research_results_repository` upsert / unique on `(run_id, company_name, requirement_id)`).

`langgraph.json` is tracked in this repo (required for LangSmith / `langgraph deploy`).

## Run

From the project root, with `PYTHONPATH=src` (or an editable install):

```bash
langgraph dev
```

Optional env for the planner → orchestrator handoff:

- By default the planner uses `langgraph_sdk.get_client(url=None)` (**in-process** ASGI) so you do **not** need the public deployment URL before deploy.
- `LANGGRAPH_API_URL` / `LANGGRAPH_DEPLOYMENT_URL` — only if calling a *remote* Agent Server
- `LANGGRAPH_API_KEY` or `LANGSMITH_API_KEY` — when talking to a remote / cloud API
- `ORCHESTRATOR_ASSISTANT_ID` — graph/assistant name (default `orchestrator`)

`start_research_run` enqueues the **orchestrator** graph via `runs.create` (platform background run).

Chat with the **planner** graph to confirm a plan and scrape target, then start a research run. Poll status via the planner’s status tool; inspect detailed rows in `research_run_results`.

## Flow (high level)

```text
User ↔ planner_graph
         │  submit plan / scrape target / start_research_run
         │  runs.create (in-process) → orchestrator
         ▼
   orchestrator_graph (background run)
         │  Apify scrape → companies
         │  research_subgraph.batch(company × requirement)
         ▼
   platform Store (run summary)  +  research_run_results (pair rows)
```

## Notes

- Scrape retries transient Apify/network failures (5xx, 429, timeouts); auth and other 4xx fail fast.
- Research concurrency is capped by `MAX_RESEARCH_CONCURRENCY` in `src/components/constants.py`.
- Domain skills under `src/prompts/rules/` specialize prompts (e.g. meetings, catering, amenities).
