import pytest
import time
from unittest.mock import MagicMock, AsyncMock, patch
import discord
from bot import translate_latency, DEFAULT_TEST_PHRASES

@pytest.mark.asyncio
async def test_translate_latency_execution():
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    interaction.channel_id = 1001

    guild = MagicMock(spec=discord.Guild)
    interaction.guild = guild

    # Setup channels
    dest_channel = MagicMock(spec=discord.TextChannel)
    dest_channel.id = 1002
    dest_channel.mention = "<#1002>"
    guild.get_channel.return_value = dest_channel

    # Setup webhook mock
    wh_mock = MagicMock()
    sent_msg = MagicMock()
    sent_msg.jump_url = "https://discord.com/channels/123/1002/999"
    wh_mock.send = AsyncMock(return_value=sent_msg)

    with patch("bot.relay_manager") as mock_relay, \
         patch("bot.translator_service") as mock_translator, \
         patch("bot.bot") as mock_bot:

        mock_bot.latency = 0.045
        mock_bot.user.display_avatar.url = "https://example.com/bot.png"
        mock_relay.channels = {
            1001: {"lang": "en"},
            1002: {"lang": "es"}
        }
        mock_relay.get_or_create_webhook = AsyncMock(return_value=wh_mock)

        mock_translator.stats = {
            "cache_hits": 0,
            "azure_success": 0,
            "deepl_success": 0,
            "mymemory_success": 0,
            "google_success": 0,
            "llm_success": 0
        }
        def mock_trans_call(*args, **kwargs):
            mock_translator.stats["azure_success"] += 1
            return ["¡Hola! Probando latencia."]

        mock_translator.translate = AsyncMock(side_effect=mock_trans_call)

        # Test execution
        await translate_latency.callback(
            interaction=interaction,
            source_language=None,
            target_language=None,
            target_channel=dest_channel,
            message="Hello! Testing latency."
        )

        interaction.response.defer.assert_called_once()
        wh_mock.send.assert_called_once()
        send_kwargs = wh_mock.send.call_args.kwargs
        assert "⚡ **[Latency Benchmark]** ¡Hola! Probando latencia." in send_kwargs["content"]
        assert send_kwargs["wait"] is True

        # Verify diagnostic embed was sent to user
        interaction.followup.send.assert_called_once()
        embed = interaction.followup.send.call_args.kwargs["embed"]
        assert "Polyglot Live Latency Benchmark" in embed.title
        assert "Total End-to-End" in embed.fields[0].value
        assert "Azure AI Translator" in embed.fields[1].value
