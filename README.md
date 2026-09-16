# ResidueCheck

Pre-harvest pesticide compliance check for fresh-produce exporters: reads a spray log and tells you which lots meet EU residue rules, with the regulation linked.

Built for the Nebius x NVIDIA Global AI Hackathon (Best Apps and Agents). Work in progress: the current preview runs on fixed rules only; the Nemotron agents are not connected yet.

## Run it

Requirements: Python 3.12, Node 20+.

```bash
pip install -r requirements.txt
cd web && npm install && npm run build && cd ..
python -m uvicorn residuecheck.api:app --port 8000
```

Open http://localhost:8000 and click **Load example (seeded)**.

For UI development with hot reload, run the API as above and `npm run dev` in `web/` (Vite proxies `/api` to port 8000).

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
| `residuecheck/onssa.py`, `crops.py` | Moroccan ONSSA register reader and crop mapping |
| `residuecheck/api.py` | FastAPI app (serves `web/dist` when built) |
| `web/` | React interface |
| `eval/` | Gold sets, runner, results (see `eval/README.md`) |
| `data/` | EU snapshot, ONSSA cache, RASFF notifications, crop map |
| `spikes/` | Early feasibility checks and their decisions |

## Limits

- Destination EU only; origin register Morocco only.
- Checks legal limits and label intervals; does not predict measured residue levels.
- Example spray records are invented and labelled as such; regulatory data is real.

License: MIT
