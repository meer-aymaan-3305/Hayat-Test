# QA scripts from the backend handover

One-off acceptance scripts the Hayat developer used (see `docs/handover/`). Some call Groq for real, so they need `GROQ_API_KEY` and cost API credits. Run them from this folder, because they read the `.wav` samples here and write `*_results.json` here (git ignores those):

```
cd scripts/qa && uv run python qa_session4.py
```
