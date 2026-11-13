import pytest
from unittest.mock import MagicMock, AsyncMock
from translator import TranslationService, is_passthrough_text

def test_passthrough_text_detection():
    # URLs should bypass
    assert is_passthrough_text("https://tenor.com/view/cat-dance-gif-12345") is True
    assert is_passthrough_text("http://example.com/test") is True

    # Pure Discord emojis & mentions should bypass
    assert is_passthrough_text("<:pepe:123456789012345678>") is True
    assert is_passthrough_text("<@123456789012345678>") is True
    assert is_passthrough_text("<#987654321098765432>") is True

    # Pure numbers and punctuation should bypass
    assert is_passthrough_text("12345") is True
    assert is_passthrough_text("???") is True
    assert is_passthrough_text("!?!?") is True

    # Universal gaming acronyms should bypass
    assert is_passthrough_text("lol") is True
    assert is_passthrough_text("gg") is True
    assert is_passthrough_text("ggwp") is True
    assert is_passthrough_text("lmao") is True
    assert is_passthrough_text("afk") is True
    assert is_passthrough_text("brb") is True
    assert is_passthrough_text("ok") is True

    # Normal conversational messages must NOT bypass
    assert is_passthrough_text("Hello everyone, how are you?") is False
    assert is_passthrough_text("bhai kya haal chaal?") is False
    assert is_passthrough_text("vamos a jugar") is False

@pytest.mark.asyncio
async def test_translation_lru_cache_hit():
    service = TranslationService(cache_size=10)

    # Pre-populate cache
    service._save_to_cache(
        source_lang="en",
        target_lang="es",
        text="thank you very much",
        translated="muchas gracias"
    )

    # Translate should return cached without calling any provider
    service._sync_translate = MagicMock()
    result = await service.translate("thank you very much", source_lang="en", target_lang="es")

    assert result == ["muchas gracias"]
    assert service.stats["cache_hits"] == 1
    assert service.stats["total_translated"] == 1
    service._sync_translate.assert_not_called()

@pytest.mark.asyncio
async def test_passthrough_message_skips_translation():
    service = TranslationService()
    service._sync_translate = MagicMock()

    result = await service.translate("https://discord.com", source_lang="en", target_lang="es")

    assert result == ["https://discord.com"]
    service._sync_translate.assert_not_called()
