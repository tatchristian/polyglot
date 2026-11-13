import pytest
from unittest.mock import MagicMock, AsyncMock
import discord
from relay import WebhookRelayManager
from translator import TranslationService

@pytest.mark.asyncio
async def test_reply_snippet_translation_english_to_spanish():
    bot_mock = MagicMock(spec=discord.Client)
    bot_mock.user = MagicMock()
    service = TranslationService()
    db_mock = MagicMock()
    mgr = WebhookRelayManager(bot_mock, service, db_mock)

    mgr.translator.translate = AsyncMock(return_value=["Espero que la gente hable más"])

    header = await mgr._build_reply_header(
        author_name="shadows",
        raw_snippet="I hope people will talk more now",
        source_lang="en",
        target_lang="es",
        is_target_romanized=False,
        is_source_romanized=False
    )

    assert "Replying to **@shadows**" in header
    assert "Espero que la gente hable más" in header

@pytest.mark.asyncio
async def test_reply_snippet_translation_hinglish_to_english():
    bot_mock = MagicMock(spec=discord.Client)
    bot_mock.user = MagicMock()
    service = TranslationService()
    db_mock = MagicMock()
    mgr = WebhookRelayManager(bot_mock, service, db_mock)

    mgr.normalizer.normalize_hinglish = AsyncMock(return_value="I hope people talk more now")

    header = await mgr._build_reply_header(
        author_name="shadows",
        raw_snippet="Umeed hai ki ab log aapas mein zyada baat kar paayenge",
        source_lang="hi",
        target_lang="en",
        is_target_romanized=False,
        is_source_romanized=True
    )

    assert "Replying to **@shadows**" in header
    assert "I hope people talk more now" in header

@pytest.mark.asyncio
async def test_reply_header_empty_snippet():
    bot_mock = MagicMock(spec=discord.Client)
    mgr = WebhookRelayManager(bot_mock, MagicMock(), MagicMock())

    header = await mgr._build_reply_header(
        author_name="Spider",
        raw_snippet="",
        source_lang="en",
        target_lang="es"
    )

    assert header == "┌ 💬 Replying to **@Spider**\n"
