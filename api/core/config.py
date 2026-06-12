from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        protected_namespaces=(),  # allow model_* field names
    )

    # Environment
    app_env: str = "production"  # set APP_ENV=staging on Railway staging service

    # Database
    database_url: str = "postgresql+asyncpg://billy:billy@localhost/billy"

    # Redis
    redis_url: str = "redis://localhost:6379"

    # Auth
    secret_key: str = "changeme"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # Model
    model_weights_dir: str = "./weights"
    model_device: str = "cuda"

    # Modal.com — endpoint GPU para Pet-ReID
    modal_endpoint_url: str = ""

    # Storage - MinIO (local dev)
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "billy-photos"
    minio_secure: bool = False

    # Storage - AWS S3 (produção)
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_s3_bucket: str = "appbilly-photos"
    aws_s3_region: str = "us-east-2"

    # Email (Resend)
    resend_api_key: str = ""
    resend_from_email: str = "Billy App <noreply@appbilly.com.br>"
    api_base_url: str = "https://billy-api-production-5239.up.railway.app"

    # Anthropic — Billy AI
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"

    # Google Places
    google_places_api_key: str = ""
    places_default_radius_km: int = 5

    # Quality thresholds
    min_quality_score: float = 0.6
    default_min_confidence: float = 0.75
    default_search_radius_km: int = 10
    default_top_k: int = 3
    max_image_size_mb: int = 10


def _make_settings() -> Settings:
    s = Settings()
    # Railway provides postgresql:// but asyncpg needs postgresql+asyncpg://
    url = s.database_url
    if url.startswith("postgresql://") or url.startswith("postgres://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        object.__setattr__(s, "database_url", url)
    return s


settings = _make_settings()
