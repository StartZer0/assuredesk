import os
from dataclasses import dataclass, field
from pathlib import Path


def load_local_env(path=".env"):
    """Only the explicitly named local secret file; never search other projects."""
    p = Path(path)
    if p.exists():
        for line in p.read_text().splitlines():
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key, value)


@dataclass
class Settings:
    database_url: str = field(repr=False)
    object_root: str = "data/objects"
    model: str = "kimi-k3"
    api_key: str = field(default="", repr=False)
    input_price: float = 6.00  # $3 input + at most $3 default cache write; no discount assumed.
    output_price: float = 15.00
    secure_cookie: bool = True
    embedding_cache: str = "data/models"

    @classmethod
    def env(cls):
        load_local_env()
        return cls(
            database_url=os.environ.get(
                "DATABASE_URL", "postgresql+psycopg://assuredesk@localhost/assuredesk"
            ),
            object_root=os.environ.get("OBJECT_ROOT", "data/objects"),
            model=os.environ.get("GENERATION_MODEL", "kimi-k3"),
            api_key=os.environ.get("MOONSHOT_API_KEY", ""),
            input_price=float(os.environ.get("GENERATION_INPUT_PRICE", "6.00")),
            output_price=float(os.environ.get("GENERATION_OUTPUT_PRICE", "15.00")),
            secure_cookie=os.environ.get("LOCAL_HTTP", "") != "1",
            embedding_cache=os.environ.get("EMBEDDING_CACHE", "data/models"),
        )


# Versioned non-secret policy; freeze hashes include this file. No runtime auto-tuning.
LIMITS = {
    "retrieval_rounds": 3,
    "embedding_attempts": 5,
    "generation_attempts": 7,
    "active_seconds": 90,
    "input_bytes": 6000,
    "output_tokens": 1200,
    "run_usd": 0.15,
    "workbook_usd": 5.0,
    "day_usd": 5.0,
    "batch_usd": 15.0,
    "campaign_usd": 30.0,
    "retention_days": 90,
}
