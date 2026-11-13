import pytest
from unittest.mock import patch, MagicMock
from translator import TranslationService

@pytest.mark.asyncio
async def test_mymemory_success_when_no_keys():
    service = TranslationService()

    with patch("translator.MyMemoryTranslator") as mock_mm:
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

    with patch("translator.MyMemoryTranslator") as mock_mm, \
         patch("translator.GoogleTranslator") as mock_gt:

        # MyMemory fails with 429
        mm_inst = MagicMock()
        mm_inst.translate.side_effect = Exception("MyMemory Rate limit")
        mock_mm.return_value = mm_inst

        # Google succeeds
        gt_inst = MagicMock()
        gt_inst.translate.return_value = "Hola desde Google"
        mock_gt.return_value = gt_inst

        result = await service.translate("Hello failover", source_lang="en", target_lang="es")

        assert result == ["Hola desde Google"]
        assert service.stats["mymemory_success"] == 0
        assert service.stats["google_success"] == 1
        assert service.stats["errors"] == 0

@pytest.mark.asyncio
async def test_all_providers_fail():
    service = TranslationService()

    with patch("translator.MyMemoryTranslator") as mock_mm, \
         patch("translator.GoogleTranslator") as mock_gt:

        mm_inst = MagicMock()
        mm_inst.translate.side_effect = Exception("MyMemory Down")
        mock_mm.return_value = mm_inst

        gt_inst = MagicMock()
        gt_inst.translate.side_effect = Exception("Google TooManyRequests")
        mock_gt.return_value = gt_inst

        result = await service.translate("Hello crash", source_lang="en", target_lang="es")

        assert len(result) == 1
        assert "All providers exhausted" in result[0]
        assert "Hello crash" in result[0]
        assert service.stats["errors"] == 1

@pytest.mark.asyncio
async def test_same_language_skips_all_providers():
    service = TranslationService()

    with patch("translator.MyMemoryTranslator") as mock_mm, \
         patch("translator.GoogleTranslator") as mock_gt:

        result = await service.translate("Already english", source_lang="en", target_lang="en")

        assert result == ["Already english"]
        mock_mm.assert_not_called()
        mock_gt.assert_not_called()
