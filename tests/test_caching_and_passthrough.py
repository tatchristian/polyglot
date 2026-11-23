import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from deep_translator.exceptions import TooManyRequests
from translator import TranslationService, is_passthrough_text, CircuitState
from database import DatabaseManager

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

def test_thai_text_not_passthrough():
    # Thai Unicode characters (\u0E00-\u0E7F) must NOT be skipped as symbols
    assert is_passthrough_text("สวัสดี") is False
    assert is_passthrough_text("สบายดีไหม") is False
    assert is_passthrough_text("สวัสดีครับทุกคน") is False

def test_elongated_slang_passthrough():
    # Elongated slang with repeated characters should collapse to universal tokens
    assert is_passthrough_text("loooool") is True
    assert is_passthrough_text("loool") is True
    assert is_passthrough_text("yessss") is True
    assert is_passthrough_text("yess") is True
    assert is_passthrough_text("okk") is True
    assert is_passthrough_text("okkk") is True
    assert is_passthrough_text("bruhhh") is True
    assert is_passthrough_text("omgggg") is True

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

def test_circuit_breaker_on_429_and_skip():
    service = TranslationService()

    # Initially all providers should be healthy
    assert service.circuit_breakers["mymemory"].is_healthy is True
    assert service.circuit_breakers["mymemory"].state == CircuitState.HEALTHY

    # Simulate 429 TooManyRequests on MyMemory
    with patch("translator.AZURE_TRANSLATOR_KEY", ""), \
         patch("translator.DEEPL_API_KEY", ""), \
         patch("translator.MyMemoryTranslator") as mock_mm, \
         patch("translator.googleapis_translate", return_value="Hola desde Google") as mock_gt:

        mm_inst = MagicMock()
        mm_inst.translate.side_effect = TooManyRequests("MyMemory 429 Too Many Requests")
        mock_mm.return_value = mm_inst

        # Perform translation which encounters 429 on mymemory
        res = service._sync_translate("hello world", "en", "es")
        assert res == "Hola desde Google"

        # Verify circuit breaker entered COOLDOWN
        assert service.circuit_breakers["mymemory"].state == CircuitState.COOLDOWN
        assert service.circuit_breakers["mymemory"].is_healthy is False
        assert service.stats["circuit_breaker_cooldowns"] >= 1
        assert service.stats["failovers"] >= 1

        # On subsequent provider lookup, mymemory must be skipped
        providers = service._get_providers("en", "es", rotate=False)
        provider_names = [p[0] for p in providers]
        assert "mymemory" not in provider_names
        assert "google" in provider_names

def test_priority_cascade_order():
    service = TranslationService()

    # Case 1: When Azure key is configured, Azure is 100% primary driver (rotate=False default)
    with patch("translator.AZURE_TRANSLATOR_KEY", "mock_key"), \
         patch("translator.DEEPL_API_KEY", ""):
        providers = service._get_providers("en", "es")
        assert providers[0][0] == "azure"
        assert providers[1][0] == "mymemory"
        assert providers[2][0] == "google"

    # Case 2: When Azure key is empty, MyMemory is first, followed by Google gtx
    with patch("translator.AZURE_TRANSLATOR_KEY", ""), \
         patch("translator.DEEPL_API_KEY", ""):
        providers = service._get_providers("en", "es")
        assert providers[0][0] == "mymemory"
        assert providers[1][0] == "google"

@pytest.mark.asyncio
async def test_sqlite_cache_persists_across_service_instances(tmp_path):
    db_file = str(tmp_path / "persistent_cache.db")

    # Instance 1: Translate and cache into SQLite
    db1 = DatabaseManager(db_path=db_file)
    await db1.connect()

    service1 = TranslationService(db=db1)
    service1._sync_translate = MagicMock(return_value="Bonjour le monde")

    res1 = await service1.translate("Hello world", source_lang="en", target_lang="fr")
    assert res1 == ["Bonjour le monde"]
    service1._sync_translate.assert_called_once()

    await db1.close()

    # Instance 2: Fresh TranslationService instance with empty L1 RAM cache
    db2 = DatabaseManager(db_path=db_file)
    await db2.connect()

    service2 = TranslationService(db=db2)
    # Ensure L1 RAM cache is completely empty
    assert len(service2._cache) == 0

    # Ensure _sync_translate is NOT called because translation is pulled from SQLite L2
    service2._sync_translate = MagicMock()
    res2 = await service2.translate("Hello world", source_lang="en", target_lang="fr")

    assert res2 == ["Bonjour le monde"]
    service2._sync_translate.assert_not_called()
    assert service2.stats["cache_hits"] == 1
    # Verify L1 RAM cache was backfilled
    assert service2._get_from_cache("en", "fr", "Hello world") == "Bonjour le monde"

    await db2.close()

def test_negation_safe_fuzzy_cache_hit():
    service = TranslationService(cache_size=10)
    service._save_to_cache("en", "es", "thank you very much", "muchas gracias")

    # Slight slang/typo variation: "thank you very much" vs "thank you veri much" (95% ratio)
    fuzzy_result = service._get_from_cache("en", "es", "thank you veri much")
    assert fuzzy_result == "muchas gracias"
    assert service.stats.get("fuzzy_cache_hits", 0) >= 1

    # Exact key is now backfilled
    assert ("en", "es", "thank you veri much") in service._cache

def test_negation_guard_blocks_polarity_inversion():
    service = TranslationService(cache_size=10)
    service._save_to_cache("en", "es", "yes bro let's go play", "si hermano vamos a jugar")

    # "no bro let's go play" is 85-90% similar textually, but contains opposite polarity "no"
    mismatch_result = service._get_from_cache("en", "es", "no bro let's go play")
    assert mismatch_result is None

def test_game_brands_passthrough():
    assert is_passthrough_text("Valorant") is True
    assert is_passthrough_text("Apex Legends") is True
    assert is_passthrough_text("Roblox") is True
    assert is_passthrough_text("Minecraft") is True
    assert is_passthrough_text("Fortnite") is True
