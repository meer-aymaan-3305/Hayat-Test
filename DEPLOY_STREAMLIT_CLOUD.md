# Deploying Hayat to Streamlit Community Cloud (team testing)

This is a **test deployment**. The Streamlit app starts the Hayat API inside the same
process, so there is only one thing to deploy. Conversations are kept in memory (wiped on
restart) and no real SMS is sent.

## 1. What you need
- The code on GitHub (private repo `Trawell-Care/Hayat`, branch with these files).
- A Streamlit Community Cloud account: https://share.streamlit.io (sign in with GitHub and
  allow access to the private `Trawell-Care` repo).
- A Groq API key (see "Groq limits" below before inviting the whole team).

## 2. Deploy
1. share.streamlit.io -> **Create app** -> **Deploy a public app from GitHub** (it can still
   be made private in step 4).
2. Repository: `Trawell-Care/Hayat`, Branch: the branch you pushed, Main file path:
   `cloud_app.py`.
3. **Advanced settings**
   - Python version: **3.13** (the code is tested on 3.13 and 3.14; 3.12 also works).
   - Secrets: paste the contents of `.streamlit/secrets.toml.example` with real values
     (at minimum `GROQ_API_KEY` and `APP_PASSWORD`).
4. **Deploy**. The first start takes a few minutes while dependencies install.

## 3. Share with the team
- App menu -> **Share** -> turn **public access off** and add your teammates' emails as
  viewers. (Without this, anyone with the link can open the app.)
- `APP_PASSWORD` adds a second gate in the app itself. Give the password to the team.

## 4. What the team will see
- A warm, time-aware greeting, then the guided intake: medical or wellness, specifics,
  destination, timing, budget, travellers, name, phone, OTP, consent.
- **OTP is a test code: 123456.** No SMS is sent.
- Coordinator contact details stay hidden (Policy Addendum 1.1 is not approved).
- The knowledge Hayat answers from is in `knowledge_seed/`. Replace the files there and
  redeploy to change it.
- The app sleeps after a period of inactivity and restarts fresh (in-memory data is lost).

## 5. Groq limits (important)
On Groq's free tier the limits are per **organization**, not per key: about 200,000 tokens
per day per model, and 7,000 input tokens per minute for `qwen3.8-27b`. One chat turn uses
roughly 2-4K tokens, so a team testing together will hit the limit quickly. When a model is
limited Hayat fails over to the next in `GROQ_FALLBACK_MODELS`; when all are limited it
tells the visitor it is having trouble. For real team testing, upgrade to Groq Dev Tier.

## 6. Optional: keep conversations in Supabase
Set `USE_SUPABASE = "true"`, `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` in the secrets.
Use a **staging** project, not production.

## 7. Updating
Push to the same branch; Streamlit Cloud redeploys automatically. Change secrets under
App -> Settings -> Secrets (the app restarts).

## 8. Running it locally the same way
```
uv run streamlit run cloud_app.py
```
