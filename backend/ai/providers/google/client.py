import os

from django.conf import settings

from ai.exceptions import MissingAPIKeyError


def gemini_api_key() -> str:
    """Credential for the Gemini Developer API, including Omni Interactions."""
    return (getattr(settings, "GEMINI_API_KEY", "") or "").strip()


def google_api_key() -> str:
    """Raw Google key. Gemini and Omni do not use this when GEMINI_API_KEY is set."""
    return (getattr(settings, "GOOGLE_API_KEY", "") or "").strip()


def require_gemini_api_key() -> str:
    key = gemini_api_key()
    if not key:
        raise MissingAPIKeyError(
            "Gemini is not configured. Add GEMINI_API_KEY to backend/.env."
        )
    return key


def require_google_api_key() -> str:
    """Gemini configuration gate. Uses the Gemini credential, not GOOGLE_API_KEY."""
    return require_gemini_api_key()


def gemini_credential_status() -> dict:
    """Which credential Gemini and Omni will send. Never includes secret values."""
    gemini = gemini_api_key()
    google = (os.environ.get("GOOGLE_API_KEY") or "").strip()
    gemini_env = (os.environ.get("GEMINI_API_KEY") or "").strip()
    return {
        "gemini_api_key": {
            "variable": "GEMINI_API_KEY",
            "configured": bool(gemini_env or gemini),
            "used_by_gemini_omni": bool(gemini),
        },
        "google_api_key": {
            "variable": "GOOGLE_API_KEY",
            "configured": bool(google),
            "used_by_gemini_omni": bool(gemini) and gemini == google and gemini != gemini_env,
        },
    }


def get_genai_client(http_options=None):
    from google import genai

    # Drop the other key for this process. The SDK reads os.environ itself and
    # will attach GOOGLE_API_KEY beside the explicit Gemini key.
    if gemini_api_key():
        os.environ.pop("GOOGLE_API_KEY", None)
    kwargs = {"api_key": require_gemini_api_key()}
    if http_options is not None:
        kwargs["http_options"] = http_options
    return genai.Client(**kwargs)


def speech_configured() -> bool:
    credentials = (settings.GOOGLE_APPLICATION_CREDENTIALS or "").strip()
    project = (settings.GOOGLE_CLOUD_PROJECT or "").strip()
    return bool(credentials or project)


def require_speech_credentials() -> None:
    if not speech_configured():
        raise MissingAPIKeyError(
            "Google Speech is not configured. Add GOOGLE_APPLICATION_CREDENTIALS "
            "or GOOGLE_CLOUD_PROJECT to backend/.env."
        )
