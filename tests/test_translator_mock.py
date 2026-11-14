import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from deep_translator.exceptions import TooManyRequests
from translator import TranslationService, googleapis_translate, azure_translate

@pytest.mark.asyncio
async def test_mymemory_success_when_no_keys():
    service = TranslationService()

    with patch("translator.AZURE_TRANSLATOR_KEY", ""), \
         patch("translator.DEEPL_API_KEY", ""), \
         patch("translator.MyMemoryTranslator") as mock_mm:
        instance = MagicMock()
        instance.translate.return_value = "Hola mundo"
        mock_mm.return_value = instance

        result = await service.translate("Hello world", source_lang="en", target_lang="es")

        assert result == ["Hola mundo"]
        assert service.stats["mymemory_success"] == 1
        assert service.stats["errors"] == 0

@pytest.mark.asyncio
async def test_failover_from_mymemory_to_google():
    service = TranslationService()

    with patch("translator.AZURE_TRANSLATOR_KEY", ""), \
         patch("translator.DEEPL_API_KEY", ""), \
         patch("translator.MyMemoryTranslator") as mock_mm, \
         patch("translator.googleapis_translate", return_value="Hola desde Google gtx") as mock_gt:

        # MyMemory fails with 429
        mm_inst = MagicMock()
        mm_inst.translate.side_effect = Exception("MyMemory Rate limit")
        mock_mm.return_value = mm_inst

        result = await service.translate("Hello failover", source_lang="en", target_lang="es")

        assert result == ["Hola desde Google gtx"]
        assert service.stats["mymemory_success"] == 0
        assert service.stats["google_success"] == 1
        assert service.stats["errors"] == 0
        mock_gt.assert_called_once()

@pytest.mark.asyncio
async def test_all_providers_fail():
    service = TranslationService()

    with patch("translator.AZURE_TRANSLATOR_KEY", ""), \
         patch("translator.DEEPL_API_KEY", ""), \
         patch("translator.MyMemoryTranslator") as mock_mm, \
         patch("translator.googleapis_translate", side_effect=TooManyRequests("Google 429")) as mock_gt:

        mm_inst = MagicMock()
        mm_inst.translate.side_effect = Exception("MyMemory Down")
        mock_mm.return_value = mm_inst

        result = await service.translate("Hello crash", source_lang="en", target_lang="es")

        assert len(result) == 1
        assert "All providers exhausted" in result[0]
        assert "Hello crash" in result[0]
        assert service.stats["errors"] == 1

@pytest.mark.asyncio
async def test_llm_failover_when_traditional_providers_fail():
    mock_llm = MagicMock()
    mock_llm.translate_general = AsyncMock(return_value="Hola desde LLM Pool")
    service = TranslationService(llm_service=mock_llm)

    with patch("translator.AZURE_TRANSLATOR_KEY", ""), \
         patch("translator.DEEPL_API_KEY", ""), \
         patch("translator.MyMemoryTranslator") as mock_mm, \
         patch("translator.googleapis_translate", side_effect=TooManyRequests("Google 429")) as mock_gt:

        mm_inst = MagicMock()
        mm_inst.translate.side_effect = Exception("MyMemory TooManyRequests")
        mock_mm.return_value = mm_inst

        result = await service.translate("Hello after rate limit", source_lang="en", target_lang="es")

        assert result == ["Hola desde LLM Pool"]
        assert service.stats["llm_success"] == 1
        mock_llm.translate_general.assert_called_once()

@pytest.mark.asyncio
async def test_same_language_skips_all_providers():
    service = TranslationService()

    with patch("translator.AZURE_TRANSLATOR_KEY", ""), \
         patch("translator.DEEPL_API_KEY", ""), \
         patch("translator.MyMemoryTranslator") as mock_mm, \
         patch("translator.googleapis_translate") as mock_gt:

        result = await service.translate("Already english", source_lang="en", target_lang="en")

        assert result == ["Already english"]
        mock_mm.assert_not_called()
        mock_gt.assert_not_called()

@pytest.mark.asyncio
async def test_azure_translator_success_when_key_configured():
    service = TranslationService()

    with patch("translator.AZURE_TRANSLATOR_KEY", "fake_azure_key"), \
         patch("translator.AZURE_REGION", "westus2"), \
         patch("translator.azure_translate", return_value="Hola desde Azure") as mock_azure:

        result = await service.translate("Hello Azure", source_lang="en", target_lang="es")

        assert result == ["Hola desde Azure"]
        assert service.stats["azure_success"] == 1
        assert service.stats["errors"] == 0

@pytest.mark.asyncio
async def test_azure_failover_to_mymemory_on_rate_limit():
    service = TranslationService()

    with patch("translator.AZURE_TRANSLATOR_KEY", "fake_azure_key"), \
         patch("translator.AZURE_REGION", "westus2"), \
         patch("translator.azure_translate", side_effect=TooManyRequests("Azure 429 TooManyRequests")) as mock_azure, \
         patch("translator.MyMemoryTranslator") as mock_mm:

        # MyMemory succeeds
        mm_inst = MagicMock()
        mm_inst.translate.return_value = "Hola desde MyMemory Fallback"
        mock_mm.return_value = mm_inst

        result = await service.translate("Hello failover", source_lang="en", target_lang="es")

        assert result == ["Hola desde MyMemory Fallback"]
        assert service.stats["azure_success"] == 0
        assert service.stats["mymemory_success"] == 1
        assert service.circuit_breakers["azure"].is_healthy is False

def test_azure_translate_json_parsing_and_429():
    # 1. Test successful parsing
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [{"translations": [{"text": "Hola mundo", "to": "es"}]}]

    mock_session = MagicMock()
    mock_session.post.return_value = mock_resp

    res = azure_translate("Hello world", "en", "es", api_key="test_key", region="westus2", session=mock_session)
    assert res == "Hola mundo"

    # 2. Test 429 raises TooManyRequests
    mock_429 = MagicMock()
    mock_429.status_code = 429
    mock_session.post.return_value = mock_429
    with pytest.raises(TooManyRequests):
        azure_translate("Hello world", "en", "es", api_key="test_key", region="westus2", session=mock_session)

def test_googleapis_translate_json_parsing_and_429():
    # 1. Test successful parsing
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [[["Bonjour le monde", "Hello world", None, None]]]
    
    with patch("requests.get", return_value=mock_resp):
        res = googleapis_translate("Hello world", "en", "fr")
        assert res == "Bonjour le monde"

    # 2. Test 429 raises TooManyRequests
    mock_429 = MagicMock()
    mock_429.status_code = 429
    with patch("requests.get", return_value=mock_429):
        with pytest.raises(TooManyRequests):
            googleapis_translate("Hello world", "en", "fr")
