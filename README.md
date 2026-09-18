# ResidueCheck

Pre-harvest pesticide compliance check for fresh-produce exporters: reads a spray log and tells you which lots meet EU residue rules, with the regulation linked.

Built for the Nebius x NVIDIA Global AI Hackathon (Best Apps and Agents). Work in progress: the web preview runs on fixed rules only. The resolver agent is built and tested with a scripted model; it runs on Nemotron once Token Factory access works (set `NEBIUS_API_KEY` and `TAVILY_API_KEY` in `.env`).

## Run it

Requirements: Python 3.12, Node 20+.

```bash
pip install -r requirements.txt
cd web && npm install && npm run build && cd ..
python -m uvicorn residuecheck.api:app --port 8000
```

Open http://localhost:8000 and pick one of the demo lots (spray records are invented; the data is real).

For UI development with hot reload, run the API as above and `npm run dev` in `web/` (Vite proxies `/api` to port 8000).

### Engines: live, replay, rules

The app says on every result which engine produced it. `RESIDUECHECK_ENGINE` chooses (`residuecheck/engine.py`):

| Mode | When | Keys |
|---|---|---|
| `live` | `NEBIUS_API_KEY` is set: resolver and safer-options agents on Nemotron (Token Factory), Tavily web search if `TAVILY_API_KEY` or the Tavily CLI is available. Daily spend cap `RESIDUECHECK_DAILY_USD` (default 2.00), then fixed rules | yes |
| `replay` | no key, recordings in `data/replays/`: recorded model replies and search results are played back; the verifier and rules run live. An input outside the recording is checked by fixed rules and the result says so | no |
| `rules` | no key, no recordings: exact names, close-name suggestions, fixed rules | no |

`auto` (default) picks the first that applies. A replay only answers the exact request that was recorded; if the data the tools read has changed, it misses rather than show a stale answer (`tests/test_replay.py`).

Recording the demo lots (`data/demo_scenarios.json`, fixed reference date) once Token Factory works:

```bash
NEBIUS_API_KEY=... python scripts/record_demo.py --session demo-2026-10-05
```

Each lot is run live, then replayed from the fresh recording; it is marked as recorded only if both answers match and nothing fell back. Commit `data/replays/*.json` (model replies and public search results, no keys).

### Hosted demo (Vercel, keyless)

Live at **https://residuecheck.vercel.app**. The hosted demo is a Vercel Python function (FastAPI) that also serves the built React app. It carries no keys: it replays recordings from `data/replays/` if any, else runs on fixed rules, and says which on every result.

```bash
python scripts/build_vercel.py                 # builds the web app, assembles build/vercel/ (2.2 MB)
npx vercel login                               # once, your own Vercel account
npx vercel deploy build/vercel --prod          # prints the public URL
```

Other hosts: the `Dockerfile` builds the same app as one container on port 7860 (`PORT` overrides it) for Render, Fly, a Nebius VM or a paid Hugging Face Docker Space (`scripts/build_space.py` assembles that folder). Locally: `podman build -t residuecheck . && podman run -p 7860:7860 residuecheck`.

## Test it

```bash
python -m pytest tests                                  # unit, data, eval and API tests
python eval/run.py --suite g1 --config rules-only       # G1 dev split
python eval/run.py --suite g2 --config rules-only       # G2 dev split
cd web && npm run lint && npm run build                 # frontend checks
```

## What is in here

| Path | What |
|---|---|
| `residuecheck/rules.py` | Deterministic verdict rules (RED / CANNOT VERIFY / AMBER / GREEN) |
| `residuecheck/eu_data.py` | Frozen EU Pesticides Database snapshot: substances, limits over time |
| `residuecheck/onssa.py`, `crops.py`, `registers.py` | Moroccan ONSSA register reader, crop mapping, Türkiye/Egypt register page parsers |
| `scripts/onssa_crop_index.py` | Lists the ONSSA products registered for given crop names (citrus indexed so far) |
| `residuecheck/alternatives.py` | Safe alternatives: registered products for the crop and pest that pass the rules; agent and closed-book modes, all checked by the verifier |
| `residuecheck/agent_loop.py` | Tool-calling loop shared by the agents (trace, cost) |
| `residuecheck/resolver.py` | Resolver: exact and fuzzy matching, Nemotron agent with tools, deterministic verifier |
| `residuecheck/llm.py`, `search.py` | Token Factory client (Nemotron) and Tavily clients (API, CLI fallback, test fake) |
| `residuecheck/api.py` | FastAPI app (serves `web/dist` when built) |
| `web/` | React interface |
| `eval/` | Gold sets, runner, results (see `eval/README.md`) |
| `data/` | EU snapshot, ONSSA cache, RASFF notifications, crop map |
| `spikes/` | Early feasibility checks and their decisions |

## Limits

- Destination EU only; origin register Morocco only.
- Safer options are computed for citrus only (the ONSSA crop index covers citrus so far). For a spray that has already been applied, options are for the next spray; nothing undoes a residue.
- Checks legal limits and label intervals; does not predict measured residue levels.
- Example spray records are invented and labelled as such; regulatory data is real.

License: MIT
