import pytest
from unittest.mock import MagicMock
import discord
from relay import WebhookRelayManager
from translator import TranslationService
from config import CHANNELS

@pytest.fixture
def relay_manager():
    bot_mock = MagicMock(spec=discord.Client)
    bot_mock.user = MagicMock()
    bot_mock.user.id = 9999
    service = TranslationService()
    db_mock = MagicMock()
    mgr = WebhookRelayManager(bot_mock, service, db_mock)
    mgr.channels = {
        123: {"lang": "en", "is_romanized": False},
        1570732777479995412: {"lang": "en", "is_romanized": False}
    }
    return mgr

def test_ignore_bot_authors(relay_manager):
    msg = MagicMock(spec=discord.Message)
    msg.author.bot = True
    msg.webhook_id = None
    msg.channel = MagicMock(spec=discord.TextChannel)
    msg.channel.id = list(CHANNELS.keys())[0] if CHANNELS else 123
    msg.content = "Hello"

    assert relay_manager.should_process_message(msg) is False

def test_ignore_webhook_messages(relay_manager):
    msg = MagicMock(spec=discord.Message)
    msg.author.bot = False
    msg.webhook_id = 88888888  # Any webhook
    msg.channel = MagicMock(spec=discord.TextChannel)
    msg.channel.id = list(CHANNELS.keys())[0] if CHANNELS else 123
    msg.content = "Relayed message"

    assert relay_manager.should_process_message(msg) is False

def test_ignore_bot_command_prefixes(relay_manager):
    channel_id = list(CHANNELS.keys())[0] if CHANNELS else 123
    # Temporarily ensure channel is in CHANNELS
    CHANNELS[channel_id] = "en"

    for prefix in ["!play", "/status", "$bid", ".help", "-stats", "?info"]:
        msg = MagicMock(spec=discord.Message)
        msg.author.bot = False
        msg.webhook_id = None
        msg.channel = MagicMock(spec=discord.TextChannel)
        msg.channel.id = channel_id
        msg.content = f"{prefix} song name"

        assert relay_manager.should_process_message(msg) is False

def test_ignore_non_text_channels(relay_manager):
    channel_id = list(CHANNELS.keys())[0] if CHANNELS else 123
    CHANNELS[channel_id] = "en"

    # Threads, Voice, Stage
    thread_mock = MagicMock(spec=discord.Thread)
    thread_mock.id = channel_id

    msg = MagicMock(spec=discord.Message)
    msg.author.bot = False
    msg.webhook_id = None
    msg.channel = thread_mock
    msg.content = "Thread message"

    assert relay_manager.should_process_message(msg) is False

def test_ignore_unregistered_channel(relay_manager):
    msg = MagicMock(spec=discord.Message)
    msg.author.bot = False
    msg.webhook_id = None
    msg.channel = MagicMock(spec=discord.TextChannel)
    msg.channel.id = 999999999999  # Unregistered ID
    msg.content = "Normal message"

    assert relay_manager.should_process_message(msg) is False

def test_accept_valid_message_in_registered_channel(relay_manager):
    channel_id = 1570732777479995412
    CHANNELS[channel_id] = "en"

    msg = MagicMock(spec=discord.Message)
    msg.author.bot = False
    msg.webhook_id = None
    msg.channel = MagicMock(spec=discord.TextChannel)
    msg.channel.id = channel_id
    msg.content = "This is a legitimate user message"
    msg.attachments = []

    assert relay_manager.should_process_message(msg) is True

def test_accept_attachment_only_message(relay_manager):
    channel_id = 1570732777479995412
    CHANNELS[channel_id] = "en"

    att_mock = MagicMock()
    att_mock.url = "https://cdn.discordapp.com/attachments/test.png"

    msg = MagicMock(spec=discord.Message)
    msg.author.bot = False
    msg.webhook_id = None
    msg.channel = MagicMock(spec=discord.TextChannel)
    msg.channel.id = channel_id
    msg.content = ""
    msg.attachments = [att_mock]

    assert relay_manager.should_process_message(msg) is True

@pytest.mark.asyncio
async def test_passthrough_message_bypasses_ai_normalization(relay_manager):
    from unittest.mock import AsyncMock
    # Channel 555 is a Romanized Hindi channel
    relay_manager.channels[555] = {"lang": "hi", "is_romanized": True}
    relay_manager.normalizer.normalize_hinglish = AsyncMock()

    msg = MagicMock(spec=discord.Message)
    msg.author.bot = False
    msg.webhook_id = None
    msg.channel = MagicMock(spec=discord.TextChannel)
    msg.channel.id = 555
    msg.channel.name = "hindi"
    msg.content = "https://tenor.com/view/funny-cat"
    msg.attachments = []
    msg.reference = None

    relay_manager.should_process_message = MagicMock(return_value=True)
    relay_manager.bot.get_channel = MagicMock(return_value=None)

    await relay_manager.relay_message(msg)

    # Groq AI normalizer must NOT have been called!
    relay_manager.normalizer.normalize_hinglish.assert_not_called()

def test_ignore_privacy_opt_out_prefixes(relay_manager):
    channel_id = list(CHANNELS.keys())[0] if CHANNELS else 123
    relay_manager.channels[channel_id] = {"lang": "en", "is_romanized": False}

    for prefix in ["// secret local message", "//dont relay", "/* block comment */", "//"]:
        msg = MagicMock(spec=discord.Message)
        msg.author.bot = False
        msg.webhook_id = None
        msg.channel = MagicMock(spec=discord.TextChannel)
        msg.channel.id = channel_id
        msg.content = prefix

        assert relay_manager.should_process_message(msg) is False
