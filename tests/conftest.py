"""Keep the suite offline, whatever a developer's local .env holds."""

import os

os.environ["APP_ENV"] = "test"
os.environ["GROQ_API_KEY"] = ""
os.environ["SUPABASE_URL"] = ""
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = ""
