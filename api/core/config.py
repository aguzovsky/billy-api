from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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

    # Storage (S3/MinIO)
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "billy-photos"
    minio_secure: bool = False

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
