"""Translation service with cascading multi-provider failover, syntax shielding, and chunking."""

import re
import time
import asyncio
import threading
import requests
from collections import OrderedDict
from typing import List, Tuple, Dict, Optional, Callable
from deep_translator import (
    MyMemoryTranslator,
    DeeplTranslator,
)
from deep_translator.exceptions import TooManyRequests
from config import (
    MAX_DISCORD_MESSAGE_LENGTH,
    MAX_LRU_CACHE_SIZE,
    DEEPL_API_KEY,
    AZURE_TRANSLATOR_KEY,
    AZURE_REGION,
    MYMEMORY_EMAIL,
)

# Regex patterns for Discord syntax shielding
EMOJI_PATTERN = re.compile(r"<a?:[a-zA-Z0-9_]+:[0-9]+>")
CODE_BLOCK_PATTERN = re.compile(r"```[\s\S]*?```")
INLINE_CODE_PATTERN = re.compile(r"`[^`\n]+`")
MENTION_PATTERN = re.compile(r"<@[!&]?[0-9]+>|<#[0-9]+>")

def shield_syntax(text: str) -> Tuple[str, Dict[str, str]]:
    """Replaces custom emojis, mentions, and code blocks with unique tokens before translation."""
    token_map: Dict[str, str] = {}
    counter = 0

    def replace_code_block(match: re.Match) -> str:
        nonlocal counter
        token = f"__DISCORD_BLOCK_{counter}__"
        token_map[token] = match.group(0)
        counter += 1
        return token

    def replace_inline_code(match: re.Match) -> str:
        nonlocal counter
        token = f"__DISCORD_INLINE_{counter}__"
        token_map[token] = match.group(0)
        counter += 1
        return token

    def replace_emoji(match: re.Match) -> str:
        nonlocal counter
        token = f"__DISCORD_EMOJI_{counter}__"
        token_map[token] = match.group(0)
        counter += 1
        return token

    def replace_mention(match: re.Match) -> str:
        nonlocal counter
        token = f"__DISCORD_MENTION_{counter}__"
        token_map[token] = match.group(0)
        counter += 1
        return token

    shielded = CODE_BLOCK_PATTERN.sub(replace_code_block, text)
    shielded = INLINE_CODE_PATTERN.sub(replace_inline_code, shielded)
    shielded = EMOJI_PATTERN.sub(replace_emoji, shielded)
    shielded = MENTION_PATTERN.sub(replace_mention, shielded)

    return shielded, token_map

def restore_syntax(text: str, token_map: Dict[str, str]) -> str:
    """Restores shielded tokens back to their original Discord syntax."""
    restored = text
    for token, original in token_map.items():
        clean_token = token.strip("_")
        pattern = re.compile(rf"__\s*{re.escape(clean_token)}\s*__", re.IGNORECASE)
        restored = pattern.sub(original, restored)
        restored = restored.replace(token, original)
    return restored

def chunk_message(text: str, max_length: int = MAX_DISCORD_MESSAGE_LENGTH) -> List[str]:
    """Splits text exceeding Discord's character limit into sequential chunks."""
    if len(text) <= max_length:
        return [text]

    chunks = []
    remaining = text

    while len(remaining) > max_length:
        split_idx = remaining.rfind("\n", 0, max_length)
        if split_idx == -1:
            split_idx = remaining.rfind(" ", 0, max_length)
        if split_idx == -1 or split_idx == 0:
            split_idx = max_length

        chunk = remaining[:split_idx].rstrip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[split_idx:].lstrip()

    if remaining:
        chunks.append(remaining)

    return chunks

# Mapping of 2-letter ISO codes to MyMemory language names
MYMEMORY_LANG_MAP = {
    "en": "english",
    "es": "spanish",
    "ja": "japanese",
    "hi": "hindi",
    "de": "german",
    "ko": "korean",
    "fr": "french",
    "pt": "portuguese",
    "ru": "russian",
    "it": "italian",
    "zh": "chinese simplified",
    "ar": "arabic",
    "id": "indonesian",
    "vi": "vietnamese",
    "th": "thai",
    "tl": "tagalog",
    "tr": "turkish",
    "pl": "polish",
    "nl": "dutch",
    "uk": "ukrainian",
}

# Universal tokens that do not require translation (saves API quota)
UNIVERSAL_TOKENS = {
    "lol", "lmao", "rofl", "gg", "ggwp", "w", "l", "f", "idk", "afk", "brb",
    "npc", "ping", "lag", "dc", "vc", "ok", "k", "ty", "thx", "pls", "plz",
    "rip", "wip", "bruh", "xd", "ez", "glhf", "mb", "omg", "wtf",
    "yes", "yeah", "yep", "no", "nah"
}

def is_passthrough_text(text: str) -> bool:
    """Returns True if the text should bypass translation APIs (URLs, emojis, numbers, universal slang)."""
    cleaned = text.strip()
    if not cleaned:
        return True

    # 1. Pure URLs
    if re.fullmatch(r"https?://\S+", cleaned, re.IGNORECASE):
        return True

    # 2. Pure Discord custom emojis or user/channel mentions
    no_discord = re.sub(r"<a?:[a-zA-Z0-9_]+:[0-9]+>|<@[!&]?[0-9]+>|<#[0-9]+>", "", cleaned).strip()
    if not no_discord:
        return True

    # 3. Pure numbers, punctuation, or unicode symbols/emojis
    # Includes Latin, Cyrillic, Arabic, Devanagari (Hindi), Thai (\u0E00-\u0E7F), Japanese, CJK, Hangul
    if not re.search(r"[a-zA-Z\u00C0-\u024F\u0400-\u04FF\u0600-\u06FF\u0900-\u097F\u0E00-\u0E7F\u3040-\u30FF\u3400-\u4DBF\u4E00-\u9FFF\uAC00-\uD7AF]", cleaned):
        return True

    # 4. Universal single-word gaming/internet tokens
    lowered = cleaned.lower()
    if lowered in UNIVERSAL_TOKENS:
        return True
    # Collapse repeated consecutive characters (e.g. loool -> lol, yessss -> yes, okk -> ok)
    collapsed = re.sub(r'(.)\1{2,}', r'\1', lowered)
    if collapsed in UNIVERSAL_TOKENS:
        return True
    collapsed_pairs = re.sub(r'(.)\1+', r'\1', lowered)
    if collapsed_pairs in UNIVERSAL_TOKENS:
        return True

    return False

def azure_translate(
    text: str,
    source_lang: str,
    target_lang: str,
    api_key: Optional[str] = None,
    region: Optional[str] = None,
    session: Optional[requests.Session] = None,
    timeout: float = 5.0
) -> str:
    """Translates text via Microsoft Azure Cognitive Services Translator using a persistent HTTP Keep-Alive session."""
    if not text or not text.strip():
        return text

    key = api_key or AZURE_TRANSLATOR_KEY
    if not key:
        raise ValueError("Azure Translator key not configured")

    reg = region or AZURE_REGION or "westus2"
    url = "https://api.cognitive.microsofttranslator.com/translate"
    params = {
        "api-version": "3.0",
        "from": source_lang,
        "to": target_lang
    }
    headers = {
        "Ocp-Apim-Subscription-Key": key,
        "Ocp-Apim-Subscription-Region": reg,
        "Content-Type": "application/json",
        "User-Agent": "PolyglotDiscordBot/2.0"
    }

    client = session if session is not None else requests
    try:
        r = client.post(url, params=params, headers=headers, json=[{"text": text}], timeout=timeout)
    except Exception as e:
        raise e

    if r.status_code == 429:
        raise TooManyRequests("Azure 429 Too Many Requests")
    r.raise_for_status()

    data = r.json()
    if isinstance(data, list) and data and "translations" in data[0]:
        return data[0]["translations"][0]["text"]
    return text

def googleapis_translate(
    text: str,
    source_lang: str,
    target_lang: str,
    session: Optional[requests.Session] = None,
    timeout: float = 5.0
) -> str:
    """Translates text via Google's public translation endpoint (client=gtx) with JSON parsing, session reuse, and timeout."""
    if not text or not text.strip():
        return text

    url = "https://translate.googleapis.com/translate_a/single"
    params = {
        "client": "gtx",
        "sl": source_lang,
        "tl": target_lang,
        "dt": "t",
        "q": text,
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    client = session if session is not None else requests
    try:
        r = client.get(url, params=params, headers=headers, timeout=timeout)
    except Exception as e:
        raise e

    if r.status_code == 429:
        raise TooManyRequests("Google gtx 429 Too Many Requests")
    r.raise_for_status()

    data = r.json()
    if not data or not data[0]:
        return text

    translated_parts = [part[0] for part in data[0] if part and part[0]]
    return "".join(translated_parts)

class CircuitState:
    HEALTHY = "HEALTHY"
    COOLDOWN = "COOLDOWN"

class CircuitBreaker:
    """Tracks provider health and cooldown periods when rate-limited."""

    def __init__(self, cooldown_duration: float = 60.0):
        self.cooldown_duration = cooldown_duration
        self.cooldown_until: float = 0.0
        self.failover_count: int = 0

    @property
    def state(self) -> str:
        if time.time() < self.cooldown_until:
            return CircuitState.COOLDOWN
        return CircuitState.HEALTHY

    @property
    def is_healthy(self) -> bool:
        return self.state == CircuitState.HEALTHY

    def mark_cooldown(self, duration: Optional[float] = None):
        dur = duration if duration is not None else self.cooldown_duration
        self.cooldown_until = time.time() + dur
        self.failover_count += 1

    def reset(self):
        self.cooldown_until = 0.0

def _is_rate_limit_error(e: Exception) -> bool:
    """Checks whether an exception indicates a 429 or rate limit."""
    if isinstance(e, TooManyRequests):
        return True
    msg = str(e).lower()
    return (
        "429" in msg or
        "too many requests" in msg or
        "toomanyrequests" in msg or
        "rate limit" in msg or
        getattr(e, "status_code", None) == 429
    )

class TranslationService:
    """Manages translation with cascading multi-provider fallback, circuit breakers, LRU & SQLite caching, and LLM failover."""

    def __init__(self, llm_service=None, db=None, cache_size: int = MAX_LRU_CACHE_SIZE):
        self.llm_service = llm_service
        self.db = db
        self.cache_size = cache_size
        self._cache: OrderedDict[Tuple[str, str, str], str] = OrderedDict()
        self._rr_index = 0
        self._lock = threading.Lock()
        self.session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=20, max_retries=1)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.circuit_breakers: Dict[str, CircuitBreaker] = {
            name: CircuitBreaker(60.0)
            for name in ["deepl", "azure", "mymemory", "google", "groq_llm"]
        }
        self.stats = {
            "total_translated": 0,
            "cache_hits": 0,
            "deepl_success": 0,
            "azure_success": 0,
            "mymemory_success": 0,
            "google_success": 0,
            "llm_success": 0,
            "errors": 0,
            "failovers": 0,
            "circuit_breaker_cooldowns": 0,
        }

    def _get_from_cache(self, source_lang: str, target_lang: str, text: str) -> Optional[str]:
        """Looks up a previously translated phrase from L1 LRU memory."""
        key = (source_lang, target_lang, text.strip().lower())
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def _save_to_cache(self, source_lang: str, target_lang: str, text: str, translated: str):
        """Stores translated phrase in bounded LRU memory."""
        if not translated or not text or "*(All providers exhausted" in translated or "*(Translation runtime error" in translated:
            return
        key = (source_lang, target_lang, text.strip().lower())
        self._cache[key] = translated
        if len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)

    async def _save_translation(self, source_lang: str, target_lang: str, text: str, translated: str):
        """Stores translated phrase in both L1 RAM cache and L2 SQLite cache."""
        self._save_to_cache(source_lang, target_lang, text, translated)
        if self.db:
            try:
                await self.db.set_cached_translation(source_lang, target_lang, text, translated)
            except Exception as e:
                print(f"L2 cache save error: {e}")

    def _get_providers(self, source_lang: str, target_lang: str, rotate: bool = False) -> List[Tuple[str, Callable[[str], str]]]:
        """Returns active translation providers in strict priority cascade order (Azure -> MyMemory -> Google gtx), skipping cooldowns."""
        all_providers: List[Tuple[str, Callable[[str], str]]] = []

        # 1. Azure Microsoft Translator (100% Primary Driver with persistent HTTP Keep-Alive)
        if AZURE_TRANSLATOR_KEY:
            all_providers.append((
                "azure",
                lambda t: azure_translate(
                    text=t,
                    source_lang=source_lang,
                    target_lang=target_lang,
                    api_key=AZURE_TRANSLATOR_KEY,
                    region=AZURE_REGION,
                    session=self.session
                )
            ))

        # 2. DeepL Free API (if key provided)
        if DEEPL_API_KEY:
            all_providers.append((
                "deepl",
                lambda t: DeeplTranslator(
                    api_key=DEEPL_API_KEY,
                    source=source_lang,
                    target=target_lang,
                    use_free_api=True
                ).translate(t)
            ))

        # 3. MyMemory API (zero-key free tier, 50k words/day with email)
        mm_src = MYMEMORY_LANG_MAP.get(source_lang, source_lang)
        mm_target = MYMEMORY_LANG_MAP.get(target_lang, target_lang)
        all_providers.append((
            "mymemory",
            lambda t: MyMemoryTranslator(
                source=mm_src,
                target=mm_target,
                email=MYMEMORY_EMAIL or None
            ).translate(t)
        ))

        # 4. Google Public API (client=gtx, high-resilience fallback with Keep-Alive)
        all_providers.append((
            "google",
            lambda t: googleapis_translate(t, source_lang, target_lang, session=self.session)
        ))

        # Filter out providers currently in cooldown
        healthy = [p for p in all_providers if self.circuit_breakers.get(p[0], CircuitBreaker()).is_healthy]
        if not healthy or not rotate:
            return healthy

        with self._lock:
            start_idx = self._rr_index % len(healthy)
            self._rr_index += 1
            return healthy[start_idx:] + healthy[:start_idx]

    def _sync_translate(self, text: str, source_lang: str, target_lang: str) -> str:
        """Translates text cascading through providers until one succeeds."""
        if not text or not text.strip():
            return text

        shielded_text, token_map = shield_syntax(text)
        providers = self._get_providers(source_lang, target_lang)

        if not providers:
            self.stats["errors"] += 1
            return f"*(All providers exhausted: RateLimitCooldown)* {text}"

        last_error = None
        for name, translate_fn in providers:
            try:
                translated = translate_fn(shielded_text)
                if translated and translated.strip():
                    self.stats[f"{name}_success"] += 1
                    self.stats["total_translated"] += 1
                    return restore_syntax(translated, token_map)
            except Exception as e:
                last_error = e
                # Provider failed or rate-limited; trigger circuit breaker on 429
                if _is_rate_limit_error(e):
                    if name in self.circuit_breakers:
                        self.circuit_breakers[name].mark_cooldown(60.0)
                    self.stats["failovers"] += 1
                    self.stats["circuit_breaker_cooldowns"] += 1
                continue

        self.stats["errors"] += 1
        err_msg = f"*(All providers exhausted: {type(last_error).__name__ if last_error else 'Unknown'})*"
        return f"{err_msg} {text}"

    async def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str
    ) -> List[str]:
        """Translates text asynchronously with passthrough filtering, two-tier caching, and cascading LLM failover."""
        if not text or not text.strip():
            return []

        if source_lang == target_lang:
            return chunk_message(text)

        # 1. Passthrough Filter: URLs, emojis, numbers, and universal gaming acronyms bypass APIs
        if is_passthrough_text(text):
            return chunk_message(text)

        # 2. L1 LRU Cache Check: Instant hit without consuming any API calls or tokens
        cached = self._get_from_cache(source_lang, target_lang, text)
        if cached:
            self.stats["cache_hits"] += 1
            self.stats["total_translated"] += 1
            return chunk_message(cached)

        # 3. L2 SQLite Cache Check: Persistent across bot restarts
        if self.db:
            try:
                l2_cached = await self.db.get_cached_translation(source_lang, target_lang, text)
                if l2_cached:
                    self.stats["cache_hits"] += 1
                    self.stats["total_translated"] += 1
                    # Backfill L1 RAM
                    self._save_to_cache(source_lang, target_lang, text, l2_cached)
                    return chunk_message(l2_cached)
            except Exception as e:
                print(f"L2 cache lookup error: {e}")

        translated_text = None
        try:
            translated_text = await asyncio.to_thread(
                self._sync_translate,
                text,
                source_lang,
                target_lang
            )
        except Exception:
            translated_text = None

        # Check if traditional providers were exhausted (e.g. TooManyRequests)
        failed_traditional = (
            not translated_text or
            "*(All providers exhausted" in translated_text or
            "*(Translation runtime error" in translated_text
        )

        if failed_traditional and self.llm_service:
            if self.circuit_breakers.get("groq_llm", CircuitBreaker()).is_healthy:
                # Shield text before passing to LLM to preserve Discord mentions and emojis
                shielded_text, token_map = shield_syntax(text)
                try:
                    llm_result = await self.llm_service.translate_general(
                        text=shielded_text,
                        source_lang=source_lang,
                        target_lang=target_lang
                    )
                    if llm_result:
                        restored = restore_syntax(llm_result, token_map)
                        self.stats["llm_success"] += 1
                        self.stats["total_translated"] += 1
                        await self._save_translation(source_lang, target_lang, text, restored)
                        return chunk_message(restored)
                except Exception as e:
                    print(f"LLM translation fallback error: {e}")
                    if _is_rate_limit_error(e):
                        self.circuit_breakers["groq_llm"].mark_cooldown(60.0)
                        self.stats["failovers"] += 1
                        self.stats["circuit_breaker_cooldowns"] += 1

        if not translated_text:
            translated_text = text
        elif not failed_traditional:
            # Save successful traditional translation to cache (L1 + L2)
            await self._save_translation(source_lang, target_lang, text, translated_text)

        return chunk_message(translated_text)
