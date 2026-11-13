"""Configuration and environment management for Polyglot Discord Bot."""

import os
from typing import Dict
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()

# Optional Provider API Keys for Cascading Failover & Intelligence
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
DEEPL_API_KEY = os.getenv("DEEPL_API_KEY", "").strip()
AZURE_TRANSLATOR_KEY = os.getenv("AZURE_TRANSLATOR_KEY", "").strip()
AZURE_REGION = os.getenv("AZURE_REGION", "eastus").strip()
MYMEMORY_EMAIL = os.getenv("MYMEMORY_EMAIL", "").strip()

# Groq Model Pool with Automatic Cascading Failover
GROQ_MODELS = [
    "qwen/qwen3.8-27b",
    "llama-3.1-8b-instant",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
]

# OpenRouter Free Fallback Models (activated when OPENROUTER_API_KEY is configured)
OPENROUTER_MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemini-2.0-flash:free",
    "qwen/qwen-2.5-72b-instruct:free",
]

# Supported language codes mapped to their environment variable names
LANGUAGE_CONFIG_KEYS = {
    "en": "CHANNEL_EN",
    "es": "CHANNEL_ES",
    "ja": "CHANNEL_JA",
    "hi": "CHANNEL_HI",
    "de": "CHANNEL_DE",
}

# Command prefixes to ignore so bot commands are not relayed/translated
COMMAND_PREFIXES = ("!", "/", "$", ".", "-", "?")

MAX_DISCORD_MESSAGE_LENGTH = 2000
MAX_LRU_CACHE_SIZE = 1000
MAX_CONCURRENT_RELAYS = 5

def load_channel_mappings() -> Dict[int, str]:
    """
    Parses environment variables and returns active channel mappings.
    Only channels with a valid integer ID > 0 are included.
    """
    mappings: Dict[int, str] = {}
    for lang, env_var in LANGUAGE_CONFIG_KEYS.items():
        val = os.getenv(env_var, "0").strip()
        try:
            channel_id = int(val)
            if channel_id > 0:
                mappings[channel_id] = lang
        except ValueError:
            continue
    return mappings

CHANNELS = load_channel_mappings()
