"""模型配置只读取本项目 .env 或环境变量，不读取其他项目的密钥。"""
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent.parent


def settings():
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=False)
    except ImportError:
        pass  # 离线演示不需要安装依赖。
    provider = os.getenv("GOLD_PROVIDER", "openai")
    return {
        "provider": provider,
        "api_key": os.getenv("OPENAI_API_KEY", ""),
        "base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        "model": os.getenv("GOLD_CODEX_MODEL", "gpt-5.5") if provider == "codex" else os.getenv("GOLD_MODEL", "gpt-4.1-mini"),
    }


def public_settings():
    cfg = settings()
    if cfg["provider"] == "codex":
        from .providers.codex import has_login
        ready = has_login() and bool(cfg["model"])
    else:
        ready = cfg["provider"] == "openai" and bool(cfg["api_key"] and cfg["base_url"] and cfg["model"])
    return {"model_ready": ready, "provider": cfg["provider"],
            "model": cfg["model"], "search_ready": ready}
