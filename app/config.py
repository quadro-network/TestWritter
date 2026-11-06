from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    db_host: str = "127.0.0.1"
    db_port: int = 3306
    db_name: str = "quiz"
    db_user: str = "quiz"
    db_password: str = ""

    import_token: str = ""
    web_url: str = "http://127.0.0.1:2323"
    tz: str = "Europe/Moscow"
    inbox_dir: str = "/app/inbox"
    inbox_poll_seconds: float = 5.0
    examples_dir: str = "/app/examples"
    books_dir: str = "/app/books"

    ollama_base_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "qwen2.5:7b"
    ollama_timeout: float = 300.0
    ollama_retries: int = 5
    # legacy alias — prefer book_questions_per_test
    book_questions_per_page: int = 15
    book_questions_per_test: int = 15
    book_pages_per_chunk: int = 4
    book_min_page_chars: int = 80
    book_max_pages: int = 400


    @property
    def database_url(self) -> str:
        return (
            f"mysql+pymysql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
            f"?charset=utf8mb4"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
