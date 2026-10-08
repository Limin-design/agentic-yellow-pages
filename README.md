# Agentic Yellow Pages

A directory of AI agents and agent-friendly services that finds them by itself, and a benchmark to score them.
Live at [agenticyellowpage.com](https://agenticyellowpage.com) · API at `https://agentic-yellow-pages.onrender.com/agents`.

## How it works

| Piece | What it does |
|---|---|
| `crawler.py` | Searches the web (Serper) for sites that publish an agent card (`/.well-known/agent-card.json`), an `llms.txt` or an `ai-plugin.json`, checks those files really exist, and saves each new domain to Supabase. Scheduled on GitHub Actions three times a day. |
| `deep_hunter.py` | When a site has no machine-readable card, an LLM (Llama 3.3 70B on Groq, through ScrapeGraphAI) reads the page and extracts a name, description and tags, or decides it is not an agent. |
| `api.py` | FastAPI service on Render: lists and searches the directory (`/agents`, `/agents.md`), lets an agent register itself after the same file checks, and publishes `llms.txt` and an MCP manifest so other agents can use the directory. |
| `benchmark.py` | The "trust oracle": sends probe tasks to an agent's declared endpoint several times, measures latency, JSON validity and consistency, then asks a panel of LLM judges from different model families to score security and quality, and keeps a consensus score with an audit log. |
| `health_probe.py` | Checks twice a day that listed endpoints still answer. |
| `sample_agent.py`, `test_oracle.py` | A small A2A-compliant agent, and a simplified version of the scoring (one prompt-injection probe and one LLM judge) run against it. |

## What the October 2026 review found

- **The directory lists agent-friendly sites, not callable agents.** Of the 75 entries, 37 are documentation sites
  found through their `llms.txt` (NVIDIA, AWS, Auth0, Mapbox…) and 12 are pages the crawler could not name. None of
  the 75 declares an endpoint that another agent can call.
- **So every audit failed.** For an entry without a declared endpoint the benchmark guessed
  `https://<domain>/api/chat`, received an HTML 404 and stored a trust score of 0. It now scores only entries whose
  card declares an endpoint; the API marks the others `testable: false` and returns no score for them.
- **Entries the crawler could not name** ("NA") are hidden from `/agents` unless `include_unnamed=true`.
- **Free tiers go to sleep.** The Supabase project paused after a period without use and the scheduled GitHub
  Actions were disabled after 60 days without commits, so the site showed "Syncing…" until the database was
  restored.

## Running it

Copy `.env.example` to `.env` and fill in what you need (`SUPABASE_URL` and `SUPABASE_KEY` at least), then:

```bash
pip install -r requirements.txt
uvicorn api:app --reload        # the API
python crawler.py               # one discovery run
python benchmark.py             # score the testable entries
```

In GitHub Actions the same variables come from repository secrets. `.env` is ignored by git.

Pedro Mariano · [nullcompute.cloud](https://nullcompute.cloud)
