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
     (at minimum `GROQ_API_KEY`).
4. **Deploy**. The first start takes a few minutes while dependencies install.

## 3. Share it
**Public test link (anyone with the link):** App -> Settings -> **Sharing** -> "Who can view
this app" -> **This app is public and searchable** (or the **Share** button -> **Make this app
public**). This works for apps deployed from a private repository; only the app's developers
can change it.

Before making it public:
- `PUBLIC_MAX_MESSAGES` (default 40) caps messages per browser session, so one visitor cannot
  use up the AI quota for everyone.
- A short notice under the title asks testers not to share real medical records or contact
  details. Set `PUBLIC_NOTICE = "false"` to hide it.
- The team debug panel only opens with `?debug=<DEBUG_KEY>`; with no `DEBUG_KEY` set it is off.
- The API runs inside the app on 127.0.0.1 and is not reachable from the internet.
- Quota: the free Groq tier allows about 200,000 tokens per model per day (roughly 60 to 70
  chat turns per model). When the models are limited, Hayat keeps working on its code-only path
  (approved wording and correct memory, less natural phrasing). Upgrade Groq to Dev Tier, or add
  a paid Gemini key, before sharing widely.

**Team only:** turn public access off and add teammates' emails as viewers (Community Cloud
allows one private app per account).

## 4. What the team will see
- Only the chat is shown. Hayat greets by the visitor's browser time, introduces herself as an
  AI, optionally asks what to call them, then understands the need one question at a time.
- She never takes contact details, diagnoses, reports or consent in chat. When enough is
  shared (or by the fifth message, or when asked for a person) she offers the free consultation
  (medical) or free call (wellness) through signup or login. Set `SIGNUP_URL` for the link.
- Add `?debug=<DEBUG_KEY>` to the app address to see the AI connection check and the last turn's record.
- The knowledge Hayat answers from is in `knowledge_seed/`. Replace the files there and
  redeploy to change it.
- The app sleeps after a period of inactivity and restarts fresh (in-memory data is lost).

## Page features
- **One composer, like a modern assistant:** type, attach a document with the paperclip, or
  record your voice with the microphone, all in the same box.
- **Welcome cards** for the three signature programmes (HAYAT-100, Zoé, FFounders). Tapping
  one asks Hayat about it. After the first message they stay available under "Signature
  programmes".
- **Suggested next steps** as pills under each reply, written from what was just said.
- **Documents:** attach a PDF, Word, PNG or JPG; the visitor must tap "Allow and upload" first.
  Hayat answers from the document text, names it, and never says whether a medical value is
  normal or concerning. (Scanned files need `tesseract-ocr`, listed in `packages.txt`.)
- **Voice:** a Listen button under each reply and a "Read aloud" switch at the top.
- **Reference number:** after the free consultation is offered, a short number such as
  `HYT-261112-48213` is shown to quote at signup. It is also on the coordinator card.
- **Wording:** the scenario replies S1 to S17 are the training document's own words, and
  "trawellcare" is always written in lower case.

## Voice
- Tap the microphone above the message box and speak (English or Arabic); Hayat transcribes
  with Groq `whisper-large-v3` (the most accurate Whisper model) and answers like a typed chat.
- Turn on **Read Hayat's replies aloud** in the sidebar (replies to a spoken message are
  always read aloud). English uses the Orpheus voice `hannah` with a warm style, Arabic uses
  the Saudi Orpheus voice `noura`. Change them with `GROQ_TTS_VOICE_EN` / `GROQ_TTS_VOICE_AR`
  (English: autumn, diana, hannah, austin, daniel, troy. Arabic: lulwa, noura, aisha,
  abdullah, fahad, sultan).
- The browser asks for microphone permission the first time.

## 5. Groq limits (important)
On Groq's free tier the limits are per **organization**, not per key: about 200,000 tokens
per day per model, and 7,000 input tokens per minute for `qwen3.8-27b`. One chat turn uses
roughly 2-4K tokens, so a team testing together will hit the limit quickly. When a model is
limited Hayat fails over to the next in `GROQ_FALLBACK_MODELS`; when all are limited it
tells the visitor it is having trouble. For real team testing, upgrade to Groq Dev Tier.

### Backup AI provider (fixes "I can't reach my AI service")
Groq's free quota is shared by the whole organization and runs out. Add a second provider and
Hayat switches to it automatically. Get a free Gemini key at https://aistudio.google.com/apikey
and add to the secrets:
```
LLM_FALLBACK_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
LLM_FALLBACK_API_KEY = "your-gemini-key"
LLM_FALLBACK_MODEL = "gemini-3.5-flash"
```
Any OpenAI-compatible service works (OpenRouter, OpenAI, ...).

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
