"""
LabelSafe System Configuration.
Production-grade Pydantic BaseSettings loading from environment variables.
"""

import importlib.util
from functools import lru_cache
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """System-wide configuration settings with environment variable overrides."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # General Application Settings
    app_name: str = Field(default="LabelSafe", description="Application name")
    app_version: str = Field(default="2.0.0", description="Application version")
    app_env: str = Field(default="development", description="Environment: development, testing, production")
    debug: bool = Field(default=False, description="Debug mode")
    log_level: str = Field(default="INFO", description="Logging level")

    # API Gateway Configuration
    api_host: str = Field(default="0.0.0.0", description="FastAPI host")  # noqa: S104 - container default; override with API_HOST
    api_port: int = Field(default=8000, description="FastAPI port")
    api_prefix: str = Field(default="/api/v1", description="API route prefix")

    # PostgreSQL Relational & pgvector Configuration
    database_url: str = Field(
        default="postgresql+asyncpg://labelsafe_user:labelsafe_password@localhost:5432/labelsafe_db",
        description="Async PostgreSQL connection URI",
    )
    database_pool_size: int = Field(default=10, description="Database connection pool size")

    @field_validator("database_url")
    @classmethod
    def _asyncpg_url(cls, url: str) -> str:
        """Accept the libpq-style URL Neon/Vercel provide (postgres://…?sslmode=require&channel_binding=…):
        asyncpg needs the +asyncpg driver, takes ``ssl`` instead of ``sslmode``, and rejects libpq-only
        options."""
        parts = urlsplit(url)
        if parts.scheme not in ("postgres", "postgresql"):
            return url  # already a SQLAlchemy URL (postgresql+asyncpg, sqlite+aiosqlite) or empty
        query = []
        for key, value in parse_qsl(parts.query):
            if key == "sslmode":
                query.append(("ssl", value))
            elif key not in ("channel_binding", "options", "target_session_attrs"):
                query.append((key, value))
        return urlunsplit(parts._replace(scheme="postgresql+asyncpg", query=urlencode(query)))

    database_max_overflow: int = Field(default=20, description="Max overflow connections")

    # External lookup cache (PostgreSQL external_lookup_cache)
    negative_cache_ttl_seconds: int = Field(
        default=604800, description="Negative cache TTL (7 days) for genuine 404s"
    )

    # Security, JWT & Authentication Configuration
    jwt_secret_key: str = Field(
        default="labelsafe-super-secret-jwt-key-change-in-production-minimum-32-chars",
        description="Cryptographic secret key for JWT signing",
    )
    jwt_algorithm: str = Field(default="HS256", description="JWT signing algorithm")
    cors_origins: list[str] = Field(
        default_factory=list,
        description='Other browser origins allowed to call the API, e.g. ["https://labelsafe.example"]. '
        "Empty: same origin only (the SPA is served by the API; the dev server proxies /api).",
    )

    # Abuse and cost controls (requests per client IP per window; see api/rate_limits.py)
    rate_limit_chat_per_minute: int = Field(default=10, description="Chat messages per IP per minute")
    rate_limit_explain_per_minute: int = Field(
        default=10, description="Finding explanations per IP per minute"
    )
    rate_limit_analyze_per_minute: int = Field(default=30, description="Safety checks per IP per minute")
    rate_limit_search_per_minute: int = Field(default=120, description="Search requests per IP per minute")
    rate_limit_register_per_hour: int = Field(default=5, description="Account registrations per IP per hour")
    gemini_daily_budget: int = Field(
        default=500, description="Gemini calls per day; beyond it answers fall back to quoted label text"
    )

    # Licensing: DDInter (CC BY-NC-SA 4.0) rules are for non-commercial use; switch off otherwise.
    include_ddinter: bool = Field(default=True, description="Load the generated DDInter rules")
    access_token_expire_minutes: int = Field(default=60, description="Access token expiration window")
    refresh_token_expire_days: int = Field(default=7, description="Refresh token expiration window")
    totp_issuer: str = Field(default="LabelSafe", description="TOTP 2FA Issuer name")

    # RAG, Embedding & Evaluation Models
    # MODEL_MODE=real needs `pip install -e ".[ml]"`; tests run with MODEL_MODE=fake.
    embedding_model: str = Field(
        default="BAAI/bge-small-en-v1.5", description="sentence-transformers embedding model"
    )
    embedding_dimension: int = Field(default=384, description="Embedding vector dimension (pgvector column)")
    cross_encoder_model: str = Field(
        default="BAAI/bge-reranker-base", description="Cross-encoder reranking model"
    )
    reranker_latency_budget_ms: int = Field(
        default=2000, description="Reranking slower than this is logged as a warning"
    )
    model_mode: Literal["real", "fake"] = Field(
        # Real models only when installed, so a plain install still serves the API.
        default_factory=lambda: "real" if importlib.util.find_spec("sentence_transformers") else "fake",
        description="real: transformer embeddings + cross-encoder; fake: offline test doubles",
    )
    # RAG pipeline thresholds: the only place they are set. Scores mean different things per reranker:
    # the fake one is a term-overlap sigmoid (~0.38 for no overlap), the real one a relevance probability.
    retrieval_top_k: int = Field(default=30, description="Candidates per channel (pgvector, tsvector)")
    rerank_top_k: int = Field(default=5, description="Passages kept after cross-encoder reranking")
    rerank_min_score: float = Field(
        default=0.20, description="fake: reranked passages below this are dropped"
    )
    gate_proceed_score: float = Field(default=0.55, description="fake: top rerank score to generate")
    gate_rewrite_score: float = Field(default=0.40, description="fake: below this, abstain")
    rerank_min_score_real: float = Field(default=0.02, description="real: passages below this are dropped")
    gate_proceed_score_real: float = Field(default=0.35, description="real: top rerank score to generate")
    gate_rewrite_score_real: float = Field(default=0.05, description="real: below this, abstain")
    max_rewrites: int = Field(default=1, description="CRAG: query rewrites before abstaining")
    llm_backend: Literal["template", "gemini"] = Field(
        default="template", description="Grounded narrative generator"
    )
    gemini_model: str = Field(default="gemini-3.8-flash", description="Gemini model for grounded synthesis")
    gemini_api_key: SecretStr | None = Field(
        default=None, description="GEMINI_API_KEY; the SDK also reads GEMINI_API_KEY / GOOGLE_API_KEY itself"
    )

    # External Medication API Endpoints
    dailymed_base_url: str = Field(
        default="https://dailymed.nlm.nih.gov/dailymed/services/v2",
        description="DailyMed REST web service root URL",
    )
    openfda_base_url: str = Field(
        default="https://api.fda.gov/drug/label.json",
        description="openFDA drug labeling endpoint",
    )
    openfda_api_key: str | None = Field(default=None, description="Optional openFDA API key")
    rxnav_base_url: str = Field(
        default="https://rxnav.nlm.nih.gov/REST",
        description="NIH NLM RxNav REST service root URL",
    )

    # Clinical Informatics & Regulatory Settings
    default_jurisdiction: str = Field(
        default="US", description="Default regulatory jurisdiction: US, IN, GLOBAL"
    )
    clinical_disclaimer: str = Field(
        default=(
            "LabelSafe is an experimental research and educational prototype. "
            "It does not provide medical advice, diagnosis, or treatment plans. "
            "Always consult a licensed healthcare professional before making medication decisions."
        ),
        description="Mandatory medical safety disclaimer appended to all clinical reports",
    )

    def rag_thresholds(self) -> tuple[float, float, float]:
        """(rerank_min, gate_proceed, gate_rewrite) for the active MODEL_MODE."""
        if self.model_mode == "real":
            return self.rerank_min_score_real, self.gate_proceed_score_real, self.gate_rewrite_score_real
        return self.rerank_min_score, self.gate_proceed_score, self.gate_rewrite_score


@lru_cache
def get_settings() -> Settings:
    """Returns a cached singleton instance of system configuration."""
    return Settings()
