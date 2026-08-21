"""Safe defaults for isolated test collection."""

import os


os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "ollama")
os.environ.setdefault("LLM_BASE_URL", "http://localhost:11434/v1")
