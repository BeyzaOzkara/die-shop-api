from pydantic_settings import BaseSettings
from pathlib import Path
from pydantic import ConfigDict

class Settings(BaseSettings):
    database_url: str  # .env'de DATABASE_URL veya database_url olarak geliyor olabilir

    # 🔹 Bizim eklediklerimiz
    BASE_DIR: Path = Path(__file__).resolve().parent
    MEDIA_ROOT: Path = BASE_DIR / "media"
    MEDIA_URL: str = "/media"

    # 🔹 Auth / JWT (EKLENENLER)
    JWT_SECRET_KEY: str
    JWT_EXPIRES_MINUTES: int = 1440  # 1 gün

    # 🔹 Pydantic v2 config
    model_config = ConfigDict(
        env_file=".env",
        extra="ignore",   # env'de tanımlı ama modelde olmayan şeyler için hata verme
    )

settings = Settings()
