"""Environment-backed application settings."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError


class SettingsError(RuntimeError):
    """Raised when required application configuration is missing or invalid."""


class Settings(BaseModel):
    """Validated settings used by the API foundation."""

    model_config = ConfigDict(extra="ignore")

    app_env: Literal["development", "test", "staging", "production"] = "development"
    log_level: str = "INFO"
    jwt_system_secret: SecretStr | None = None
    groq_api_key: SecretStr | None = None
    groq_model: str = "allam-2-7b"
    groq_temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    groq_max_tokens: int = Field(default=160, ge=1, le=4096)
    groq_timeout_seconds: float = Field(default=20.0, ge=1.0, le=120.0)
    groq_analysis_model: str = "qwen/qwen3.8-27b"
    groq_fallback_models: list[str] = Field(default_factory=list)
    groq_analysis_timeout_seconds: float = Field(default=6.0, ge=1.0, le=60.0)
    supabase_url: str | None = None
    supabase_service_role_key: SecretStr | None = None
    allowed_origins: list[str] = Field(default_factory=list)
    max_request_chars: int = Field(default=8_000, ge=100, le=100_000)
    sms_provider_name: str | None = None
    sms_provider_api_url: str | None = None
    sms_provider_api_key: SecretStr | None = None
    firebase_api_key: SecretStr | None = None
    firebase_project_id: str | None = None
    firebase_service_account_json: SecretStr | None = None
    policy_addendum_1_1_approved: bool = False
    medical_ai_replies: bool = False
    medical_ai_shadow: bool = False
    extended_intake: bool = False
    dev_fake_otp: bool = False
    collect_diagnosis: bool = False
    trawellcare_crm_webhook_url: str | None = None
    knowledge_dir: str = "data/knowledge"
    attachments_dir: str = "data/attachments"
    visitor_attachments_enabled: bool = False
    attachment_retention_days: int = Field(default=90, ge=0)
    max_upload_mb: int = Field(default=10, ge=1, le=50)
    groq_stt_model: str = "whisper-large-v3"
    groq_stt_language: str | None = None
    groq_tts_model_en: str = "canopylabs/orpheus-v1-english"
    groq_tts_model_ar: str = "canopylabs/orpheus-arabic-saudi"
    groq_tts_voice_en: str = "hannah"
    groq_tts_voice_ar: str = "noura"
    groq_tts_style_en: str = "warm"

    @property
    def missing_integrations(self) -> list[str]:
        """Return integrations that are not configured without exposing secrets."""
        missing: list[str] = []
        if not self.groq_api_key or _is_placeholder(self.groq_api_key.get_secret_value()):
            missing.append("GROQ_API_KEY")
        if not self.supabase_url or _is_placeholder(self.supabase_url):
            missing.append("SUPABASE_URL")
        if (
            not self.supabase_service_role_key
            or _is_placeholder(self.supabase_service_role_key.get_secret_value())
        ):
            missing.append("SUPABASE_SERVICE_ROLE_KEY")
        return missing

    def validate_integrations(self) -> None:
        """Require external integrations outside local development and tests."""
        missing = self.missing_integrations
        if missing and self.app_env in {"staging", "production"}:
            raise SettingsError(
                "Missing required integration configuration: " + ", ".join(missing)
            )


def _is_placeholder(value: str) -> bool:
    return not value or value.lower().startswith(("your_", "replace_", "changeme"))


def _environment_values() -> dict[str, str]:
    file_values = {
        key: value
        for key, value in dotenv_values(".env").items()
        if value is not None
    }
    return {**file_values, **os.environ}


def load_settings() -> Settings:
    """Load and validate settings without logging their values."""
    values = _environment_values()
    try:
        settings = Settings(
            app_env=values.get("APP_ENV", "development"),
            log_level=values.get("LOG_LEVEL", "INFO"),
            jwt_system_secret=values.get("JWT_SYSTEM_SECRET") or None,
            groq_api_key=values.get("GROQ_API_KEY"),
            groq_model=values.get("GROQ_MODEL", "allam-2-7b"),
            groq_temperature=values.get("GROQ_TEMPERATURE", 0.2),
            groq_max_tokens=values.get("GROQ_MAX_TOKENS", 160),
            groq_timeout_seconds=values.get("GROQ_TIMEOUT_SECONDS", 20.0),
            groq_analysis_model=values.get("GROQ_ANALYSIS_MODEL", "qwen/qwen3.8-27b"),
            groq_fallback_models=[
                m.strip() for m in values.get(
                    "GROQ_FALLBACK_MODELS", "openai/gpt-oss-120b,openai/gpt-oss-20b"
                ).split(",") if m.strip()
            ],
            groq_analysis_timeout_seconds=values.get("GROQ_ANALYSIS_TIMEOUT_SECONDS", 6.0),
            supabase_url=values.get("SUPABASE_URL"),
            supabase_service_role_key=values.get("SUPABASE_SERVICE_ROLE_KEY"),
            allowed_origins=[
                origin.strip()
                for origin in values.get("ALLOWED_ORIGINS", "").split(",")
                if origin.strip()
            ],
            max_request_chars=values.get("MAX_REQUEST_CHARS", 8_000),
            sms_provider_name=values.get("SMS_PROVIDER_NAME"),
            sms_provider_api_url=values.get("SMS_PROVIDER_API_URL"),
            sms_provider_api_key=values.get("SMS_PROVIDER_API_KEY"),
            firebase_api_key=values.get("FIREBASE_API_KEY"),
            firebase_project_id=values.get("FIREBASE_PROJECT_ID"),
            firebase_service_account_json=values.get("FIREBASE_SERVICE_ACCOUNT_JSON"),
            policy_addendum_1_1_approved=values.get("POLICY_ADDENDUM_1_1_APPROVED", "false").lower() in ("true", "1", "yes"),
            medical_ai_replies=values.get("MEDICAL_AI_REPLIES", "false").lower() in ("true", "1", "yes"),
            medical_ai_shadow=values.get("MEDICAL_AI_SHADOW", "false").lower() in ("true", "1", "yes"),
            dev_fake_otp=values.get("DEV_FAKE_OTP", "false").lower() in ("true", "1", "yes"),
            extended_intake=values.get("EXTENDED_INTAKE", "false").lower() in ("true", "1", "yes"),
            collect_diagnosis=values.get("COLLECT_DIAGNOSIS", "false").lower() in ("true", "1", "yes"),
            trawellcare_crm_webhook_url=values.get("TRAWELLCARE_CRM_WEBHOOK_URL"),
            knowledge_dir=values.get("KNOWLEDGE_DIR", "data/knowledge"),
            attachments_dir=values.get("ATTACHMENTS_DIR", "data/attachments"),
            visitor_attachments_enabled=values.get("VISITOR_ATTACHMENTS_ENABLED", "false").lower() in ("true", "1", "yes"),
            attachment_retention_days=values.get("ATTACHMENT_RETENTION_DAYS", 90),
            max_upload_mb=values.get("MAX_UPLOAD_MB", 10),
            groq_stt_model=values.get("GROQ_STT_MODEL", "whisper-large-v3"),
            groq_stt_language=values.get("GROQ_STT_LANGUAGE") or None,
            groq_tts_model_en=values.get("GROQ_TTS_MODEL_EN", "canopylabs/orpheus-v1-english"),
            groq_tts_model_ar=values.get("GROQ_TTS_MODEL_AR", "canopylabs/orpheus-arabic-saudi"),
            groq_tts_voice_en=values.get("GROQ_TTS_VOICE_EN", "hannah"),
            groq_tts_voice_ar=values.get("GROQ_TTS_VOICE_AR", "noura"),
            groq_tts_style_en=values.get("GROQ_TTS_STYLE_EN", "warm"),
        )
        settings.validate_integrations()
        return settings
    except (ValidationError, SettingsError) as exc:
        raise SettingsError("Invalid application configuration.") from exc


@lru_cache
def get_settings() -> Settings:
    """Return process-wide settings loaded once per process."""
    return load_settings()
