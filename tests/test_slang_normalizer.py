import pytest
from unittest.mock import AsyncMock, MagicMock
from slang_normalizer import (
    SlangNormalizer,
    HinglishNormalizer,
    has_native_script,
    UNIVERSAL_SLANG_TO_ENGLISH_PROMPT,
)

def test_has_native_script_detection():
    # Native non-Latin scripts must return True to trigger 0-token Azure bypass
    assert has_native_script("नमस्ते भाई") is True  # Hindi Devanagari
    assert has_native_script("مرحبا يا صديقي") is True  # Arabic
    assert has_native_script("Привет как дела") is True  # Russian Cyrillic
    assert has_native_script("こんにちは") is True  # Japanese Kana
    assert has_native_script("สบายดีไหม") is True  # Thai
    assert has_native_script("γειά σου") is True  # Greek

    # Romanized chat, slang, and Latin scripts must return False to route to Slang Normalizer
    assert has_native_script("kya haal hai bhai") is False  # Hinglish
    assert has_native_script("gw mw maen sm lu bntr lg") is False  # Indonesian chat slang
    assert has_native_script("keifak ya akhi 7abibi") is False  # Arabizi
    assert has_native_script("privet kak dela") is False  # Russian Translit
    assert has_native_script("arigatou gozaimasu") is False  # Japanese Romaji
    assert has_native_script("Hello everyone!") is False  # English

def test_backward_compatibility_alias():
    # HinglishNormalizer must be an exact alias of SlangNormalizer
    assert HinglishNormalizer is SlangNormalizer

    norm = HinglishNormalizer(api_key="mock_key")
    assert hasattr(norm, "normalize_hinglish")
    assert hasattr(norm, "normalize_slang")
    assert callable(norm.normalize_hinglish)
    assert callable(norm.normalize_slang)

@pytest.mark.asyncio
async def test_slang_normalizer_prompt_minification():
    norm = SlangNormalizer(api_key="mock_key")
    norm._call_llm = AsyncMock(return_value="I want to play with you in a bit")

    result = await norm.normalize_slang("gw mw maen sm lu bntr lg")
    assert result == "I want to play with you in a bit"
    assert norm.stats["groq_normalizations"] == 1

    # Verify that minified prompt was passed to _call_llm
    norm._call_llm.assert_called_once()
    call_args = norm._call_llm.call_args[1]
    messages = call_args["messages"]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == UNIVERSAL_SLANG_TO_ENGLISH_PROMPT
    assert len(messages[0]["content"].split()) < 40  # Verified minified under 40 words
