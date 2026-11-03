# BioPilot — AI Research Partner

ELN + Research Memory + Scientific Analysis + AI Partner, for analytical chemistry labs.
This repository is the **skeleton**: architecture, contracts, seed data and a working minimum
for every endpoint and screen, built so that many sessions can fill in details in parallel.

- Rules for contributors (human or AI): **[CLAUDE.md](CLAUDE.md)**
- Layers, modules, API contract: **[ARCHITECTURE.md](ARCHITECTURE.md)**
- Work to pick up: **[TASKS.md](TASKS.md)** · cross-module requests: **[CHANGES_REQUESTED.md](CHANGES_REQUESTED.md)**

## Quick start

```bash
cd backend
uv venv -p 3.11 .venv && source .venv/bin/activate   # or python3.11 -m venv .venv
pip install -e ".[dev]"
uvicorn app.main:app --reload          # seeds the demo project on first start
```

```bash
cd frontend
npm ci
npm run dev                            # http://localhost:5173 (proxies /api → :8000)
```

AI features run in deterministic **rules mode** by default. Set `ANTHROPIC_API_KEY` to enable
Claude generation mode (same output schemas; ungrounded output falls back to rules).

## Demo scenario

"잔류농약 QuEChERS·LC-MS/MS 회수율 최적화" — experiments #018–#024. The baseline protocol (#018)
recovers ≈ 89 %; the modified protocol (#024: 5-min extraction + GCB clean-up) drops to ≈ 62 % with
internal-standard suppression in 3 of 10 injections. Every number is computed from the committed CSVs.
