import os


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes"}


class AuthSettings:
    def __init__(self) -> None:
        self.database_path = os.getenv("AUTH_DATABASE_PATH", "var/auth.db")
        self.secret_key = os.getenv("AUTH_SECRET_KEY", "local-session-secret-change-me")
        self.service_secret = os.getenv("AUTH_SERVICE_SECRET", "local-introspection-secret")
        self.bootstrap_username = os.getenv("AUTH_BOOTSTRAP_USERNAME", "admin")
        self.bootstrap_password = os.getenv("AUTH_BOOTSTRAP_PASSWORD", "admin-change-me")
        self.cookie_secure = env_bool("AUTH_COOKIE_SECURE")
        self.token_ttl_hours = int(os.getenv("AUTH_TOKEN_TTL_HOURS", "24"))
        self.rag_api_url = os.getenv("RAG_API_URL", "http://127.0.0.1:8000").rstrip("/")
