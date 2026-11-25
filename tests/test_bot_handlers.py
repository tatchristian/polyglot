import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import discord
from bot import on_guild_channel_delete, on_raw_reaction_add, translate_status

@pytest.mark.asyncio
async def test_on_guild_channel_delete_unlinks_only_target_channel():
    deleted_ch = MagicMock(spec=discord.TextChannel)
    deleted_ch.id = 2001
    deleted_ch.name = "english"
    deleted_ch.guild = MagicMock(id=222, name="UDA")

    with patch("bot.db_manager") as mock_db, patch("bot.relay_manager") as mock_relay:
        mock_relay.channels = {
            1001: {"lang": "en", "guild_id": 111, "group_id": "111:default"},
            2001: {"lang": "en", "guild_id": 222, "group_id": "222:default"},
        }
        mock_db.remove_channel = AsyncMock(return_value=True)

        await on_guild_channel_delete(deleted_ch)

        mock_db.remove_channel.assert_called_once_with(2001, guild_id=222)
        mock_relay.remove_channel_from_cache.assert_called_once_with(2001)

@pytest.mark.asyncio
async def test_on_raw_reaction_add_flag_translation():
    payload = MagicMock(spec=discord.RawReactionActionEvent)
    payload.emoji = "🇪🇸"
    payload.user_id = 555
    payload.channel_id = 1001
    payload.message_id = 9001

    msg = MagicMock(spec=discord.Message)
    msg.content = "Hello team"
    msg.author.bot = False
    msg.author.display_name = "Alice"
    msg.author.display_avatar.url = "https://example.com/a.png"
    msg.webhook_id = None

    channel = MagicMock(spec=discord.TextChannel)
    channel.fetch_message = AsyncMock(return_value=msg)
    channel.send = AsyncMock()

    user = MagicMock(display_name="Bob")

    with patch("bot.bot") as mock_bot, patch("bot.translator_service") as mock_tr:
        mock_bot.user = MagicMock(id=9999)
        mock_bot.get_channel.return_value = channel
        mock_bot.get_user.return_value = user
        mock_tr.translate = AsyncMock(return_value=["Hola equipo"])

        await on_raw_reaction_add(payload)

        mock_tr.translate.assert_called_once_with(text="Hello team", source_lang="auto", target_lang="es")
        channel.send.assert_called_once()
        embed = channel.send.call_args.kwargs["embed"]
        assert "Hola equipo" in embed.description

@pytest.mark.asyncio
async def test_translate_status_filters_strictly_by_guild():
    guild_kachix = MagicMock(spec=discord.Guild, id=111, name="KachiX")
    ch_kachix = MagicMock(spec=discord.TextChannel, id=1001, name="english")
    guild_kachix.get_channel.side_effect = lambda cid: ch_kachix if cid == 1001 else None

    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = guild_kachix
    interaction.response.send_message = AsyncMock()

    with patch("bot.relay_manager") as mock_relay, \
         patch("bot.db_manager") as mock_db, \
         patch("bot.translator_service") as mock_tr, \
         patch("bot.bot") as mock_bot:
        mock_bot.latency = 0.03
        mock_relay.channels = {
            1001: {"lang": "en", "is_romanized": False, "guild_id": 111, "group_id": "111:default"},
            2001: {"lang": "en", "is_romanized": False, "guild_id": 222, "group_id": "222:default"},
        }
        mock_relay.normalizer.stats = {"hinglish_detections": 0, "groq_normalizations": 0}
        mock_db.get_stats = AsyncMock(return_value={"total_synced_messages": 5, "configured_channels": 1})
        mock_tr.stats = {
            "total_translated": 10, "cache_hits": 4,
            "deepl_success": 0, "azure_success": 6, "mymemory_success": 0, "google_success": 0,
            "errors": 0
        }
        mock_tr.circuit_breakers = {}

        await translate_status.callback(interaction)

        mock_db.get_stats.assert_called_once_with(guild_id=111)
        embed = interaction.response.send_message.call_args.kwargs["embed"]
        channels_field = embed.fields[3].value
        assert "<#1001>" in channels_field
        assert "<#2001>" not in channels_field
