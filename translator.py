"""Translation service with cascading multi-provider failover, syntax shielding, and chunking."""

import re
import asyncio
from typing import List, Tuple, Dict, Optional, Callable
from deep_translator import (
    GoogleTranslator,
    MyMemoryTranslator,
    DeeplTranslator,
    MicrosoftTranslator,
)
from config import (
    MAX_DISCORD_MESSAGE_LENGTH,
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

class TranslationService:
    """Manages translation with automatic multi-provider fallback, LLM failover, and retry logic."""

    def __init__(self, llm_service=None):
        self.llm_service = llm_service
        self.stats = {
            "total_translated": 0,
            "deepl_success": 0,
            "azure_success": 0,
            "mymemory_success": 0,
            "google_success": 0,
            "llm_success": 0,
            "errors": 0,
        }

    def _get_providers(self, source_lang: str, target_lang: str) -> List[Tuple[str, Callable[[str], str]]]:
        """Returns the ordered list of active translation providers."""
        providers = []

        # 1. DeepL Free API (if key provided)
        if DEEPL_API_KEY:
            providers.append((
                "deepl",
                lambda t: DeeplTranslator(
                    api_key=DEEPL_API_KEY,
                    source=source_lang,
                    target=target_lang,
                    use_free_api=True
                ).translate(t)
            ))

        # 2. Azure Microsoft Translator (if key provided)
        if AZURE_TRANSLATOR_KEY:
            providers.append((
                "azure",
                lambda t: MicrosoftTranslator(
                    api_key=AZURE_TRANSLATOR_KEY,
                    region=AZURE_REGION,
                    source=source_lang,
                    target=target_lang
                ).translate(t)
            ))

        # 3. MyMemory API (zero-key free tier, 50k words/day with email)
        mm_src = MYMEMORY_LANG_MAP.get(source_lang, source_lang)
        mm_target = MYMEMORY_LANG_MAP.get(target_lang, target_lang)
        providers.append((
            "mymemory",
            lambda t: MyMemoryTranslator(
                source=mm_src,
                target=mm_target,
                email=MYMEMORY_EMAIL or None
            ).translate(t)
        ))

        # 4. Google Translate (free scraping fallback)
        providers.append((
            "google",
            lambda t: GoogleTranslator(
                source=source_lang,
                target=target_lang
            ).translate(t)
        ))

        return providers

    def _sync_translate(self, text: str, source_lang: str, target_lang: str) -> str:
        """Translates text cascading through providers until one succeeds."""
        if not text or not text.strip():
            return text

        shielded_text, token_map = shield_syntax(text)
        providers = self._get_providers(source_lang, target_lang)

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
                # Provider failed or rate-limited; cascade to next provider
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
        """Translates text asynchronously using thread execution with cascading LLM failover."""
        if not text or not text.strip():
            return []

        if source_lang == target_lang:
            return chunk_message(text)

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
                    return chunk_message(restored)
            except Exception as e:
                print(f"LLM translation fallback error: {e}")

        if not translated_text:
            translated_text = text

        return chunk_message(translated_text)
