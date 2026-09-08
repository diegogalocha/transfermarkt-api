from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    NODE_ENV: str = "development"
    RATE_LIMITING_ENABLE: bool = False
    RATE_LIMITING_FREQUENCY: str = "2/3seconds"

    # Zyte API (anti-bot fetch layer). See app/services/base.py.
    # ZYTE_MODE: "off" (default, direct only) | "fallback" (direct, then Zyte on
    # anti-bot block) | "always" (every request via Zyte).
    ZYTE_API_KEY: str = ""
    ZYTE_MODE: str = "off"
    ZYTE_RENDER: bool = False  # False = httpResponseBody (cheaper); True = browserHtml
    ZYTE_GEOLOCATION: str = ""  # e.g. "ES"; empty = Zyte default


settings = Settings()
