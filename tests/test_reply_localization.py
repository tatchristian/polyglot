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

@pytest.mark.asyncio
async def test_relay_message_parallel_reply_delivery():
    bot_mock = MagicMock(spec=discord.Client)
    bot_mock.user = MagicMock()
    service = TranslationService()
    db_mock = MagicMock()
    db_mock.find_conversation_uuid = AsyncMock(return_value="parent-uuid-123")
    db_mock.record_relayed_messages = AsyncMock()

    mgr = WebhookRelayManager(bot_mock, service, db_mock)
    mgr.channels = {
        1001: {"lang": "en", "is_romanized": False},
        1002: {"lang": "es", "is_romanized": False}
    }

    # Setup destination channel and webhook mock
    dest_chan = MagicMock(spec=discord.TextChannel)
    dest_chan.id = 1002
    dest_chan.name = "spanish"
    dest_chan.guild = MagicMock(id=9999)
    bot_mock.get_channel.return_value = dest_chan

    wh_mock = MagicMock()
    wh_sent = MagicMock(id=5555)
    wh_mock.send = AsyncMock(return_value=wh_sent)
    mgr.get_or_create_webhook = AsyncMock(return_value=wh_mock)

    # Setup message with reply reference
    ref_message = MagicMock()
    ref_message.author.display_name = "OriginalAuthor"
    ref_message.content = "Original question snippet"

    msg = MagicMock(spec=discord.Message)
    msg.id = 7777
    msg.channel = MagicMock(spec=discord.TextChannel)
    msg.channel.id = 1001
    msg.guild = MagicMock(id=9999)
    msg.author.bot = False
    msg.author.display_name = "ReplyingUser"
    msg.author.display_avatar.url = "https://example.com/avatar.png"
    msg.webhook_id = None
    msg.content = "Here is my answer to you"
    msg.attachments = []
    msg.reference = MagicMock()
    msg.reference.message_id = 1234
    msg.reference.resolved = ref_message

    # Mock translation calls
    service.translate = AsyncMock(side_effect=[
        ["Aquí está mi respuesta para ti"],      # Main text translation
        ["Fragmento de pregunta original"]        # Snippet translation
    ])

    await mgr.relay_message(msg)

    # Verify webhook was called with localized reply header prepended
    wh_mock.send.assert_called_once()
    call_kwargs = wh_mock.send.call_args.kwargs
    content = call_kwargs["content"]
    assert "Replying to **@OriginalAuthor**" in content
    assert "Aquí está mi respuesta para ti" in content
    assert call_kwargs["wait"] is True

@pytest.mark.asyncio
async def test_reply_snippet_shields_game_brands_and_mentions():
    bot_mock = MagicMock(spec=discord.Client)
    service = TranslationService()
    mgr = WebhookRelayManager(bot_mock, service, MagicMock())

    mgr.normalizer.normalize_hinglish = AsyncMock(
        side_effect=lambda txt, parent_context=None: txt.replace("aaj", "today").replace("khelega", "play")
    )

    header = await mgr._build_reply_header(
        author_name="Player",
        raw_snippet="aaj Valorant khelega <@123456>",
        source_lang="hi",
        target_lang="en",
        is_source_romanized=True
    )

    called_text = mgr.normalizer.normalize_hinglish.call_args.args[0]
    assert "Valorant" not in called_text
    assert "<@123456>" not in called_text
    assert "Valorant" in header
    assert "<@123456>" in header

@pytest.mark.asyncio
async def test_long_reply_rechunked_within_discord_limit():
    bot_mock = MagicMock(spec=discord.Client)
    bot_mock.user = MagicMock()
    service = TranslationService()
    db_mock = MagicMock()
    db_mock.find_conversation_uuid = AsyncMock(return_value=None)
    db_mock.record_relayed_messages = AsyncMock()

    mgr = WebhookRelayManager(bot_mock, service, db_mock)
    mgr.channels = {
        1001: {"lang": "en", "is_romanized": False, "guild_id": 1, "group_id": "1:default"},
        1002: {"lang": "es", "is_romanized": False, "guild_id": 1, "group_id": "1:default"},
    }

    dest_chan = MagicMock(spec=discord.TextChannel)
    dest_chan.id = 1002
    dest_chan.name = "spanish"
    dest_chan.guild = MagicMock(id=1)
    bot_mock.get_channel.return_value = dest_chan

    wh_mock = MagicMock()
    wh_mock.send = AsyncMock(return_value=MagicMock(id=7001))
    mgr.get_or_create_webhook = AsyncMock(return_value=wh_mock)

    ref_msg = MagicMock()
    ref_msg.author.display_name = "Alice"
    ref_msg.content = "Check this long question"

    msg = MagicMock(spec=discord.Message)
    msg.id = 999
    msg.channel = MagicMock(spec=discord.TextChannel, id=1001)
    msg.guild = MagicMock(id=1)
    msg.author.bot = False
    msg.author.id = 10
    msg.author.display_name = "Bob"
    msg.author.display_avatar.url = "https://example.com/a.png"
    msg.webhook_id = None
    msg.content = " ".join(f"messageword{i}" for i in range(140))  # ~1950 varied chars
    msg.attachments = []
    msg.reference = MagicMock(message_id=50, resolved=ref_msg)

    long_translation = "palabra " * 248  # 1984 chars (just under 2000 before reply header)
    service.translate = AsyncMock(side_effect=[
        [long_translation],
        ["Mira esta pregunta larga"]
    ])

    await mgr.relay_message(msg)

    assert wh_mock.send.call_count == 2
    for call in wh_mock.send.call_args_list:
        assert len(call.kwargs["content"]) <= 2000

