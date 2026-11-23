"""Backward-compatible wrapper re-exporting Universal Slang Normalizer as Hinglish Normalizer."""

from slang_normalizer import (
    SlangNormalizer,
    HinglishNormalizer,
    UNIVERSAL_SLANG_TO_ENGLISH_PROMPT,
    HINGLISH_TO_ENGLISH_PROMPT,
    ENGLISH_TO_HINGLISH_PROMPT,
    has_native_script,
)

__all__ = [
    "SlangNormalizer",
    "HinglishNormalizer",
    "UNIVERSAL_SLANG_TO_ENGLISH_PROMPT",
    "HINGLISH_TO_ENGLISH_PROMPT",
    "ENGLISH_TO_HINGLISH_PROMPT",
    "has_native_script",
]
