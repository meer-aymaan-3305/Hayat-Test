"""Keep the suite offline, whatever a developer's local .env holds."""

import os

os.environ["APP_ENV"] = "test"
os.environ["GROQ_API_KEY"] = ""
os.environ["SUPABASE_URL"] = ""
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = ""
os.environ["EXTENDED_INTAKE"] = "false"
os.environ["COLLECT_DIAGNOSIS"] = "false"
os.environ["DEV_FAKE_OTP"] = "false"
os.environ["SIGNUP_HANDOFF"] = "false"
os.environ["SIGNUP_URL"] = ""
