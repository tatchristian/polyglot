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

def test_spam_messages_ignored_by_relay(relay_manager):
    channel_id = 123
    relay_manager.channels[channel_id] = {"lang": "en", "is_romanized": False}

    # 1. Keyboard smash / repeated character spam
    msg_smash = MagicMock(spec=discord.Message)
    msg_smash.author.bot = False
    msg_smash.author.id = 777
    msg_smash.webhook_id = None
    msg_smash.channel = MagicMock(spec=discord.TextChannel)
    msg_smash.channel.id = channel_id
    msg_smash.content = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    msg_smash.attachments = []
    assert relay_manager.should_process_message(msg_smash) is False

    # 2. Duplicate spam in short burst
    msg_dup = MagicMock(spec=discord.Message)
    msg_dup.author.bot = False
    msg_dup.author.id = 888
    msg_dup.webhook_id = None
    msg_dup.channel = MagicMock(spec=discord.TextChannel)
    msg_dup.channel.id = channel_id
    msg_dup.content = "check this out friends"
    msg_dup.attachments = []

    # First send is allowed
    assert relay_manager.should_process_message(msg_dup) is True
    # Immediate second identical send is blocked
    assert relay_manager.should_process_message(msg_dup) is False

@pytest.mark.asyncio
async def test_group_isolation_and_normalizer_cache(relay_manager):
    from unittest.mock import AsyncMock
    relay_manager.db.find_conversation_uuid = AsyncMock(return_value=None)
    relay_manager.db.record_relayed_messages = AsyncMock()

    # Two groups in the same guild (guild_id=10) + one channel in another guild (guild_id=20)
    relay_manager.channels = {
        101: {"lang": "hi", "is_romanized": True, "guild_id": 10, "group_id": "10:default"},
        102: {"lang": "en", "is_romanized": False, "guild_id": 10, "group_id": "10:default"},
        103: {"lang": "en", "is_romanized": False, "guild_id": 10, "group_id": "10:vip"},
        201: {"lang": "en", "is_romanized": False, "guild_id": 20, "group_id": "20:default"},
    }

    chan_map = {}
    webhooks = {}
    for cid, gid in [(101, 10), (102, 10), (103, 10), (201, 20)]:
        ch = MagicMock(spec=discord.TextChannel)
        ch.id = cid
        ch.name = f"ch-{cid}"
        ch.guild = MagicMock(id=gid)
        chan_map[cid] = ch
        wh = MagicMock()
        wh.send = AsyncMock(return_value=MagicMock(id=cid + 9000))
        webhooks[cid] = wh

    relay_manager.bot.get_channel = MagicMock(side_effect=lambda cid: chan_map.get(cid))
    relay_manager.get_or_create_webhook = AsyncMock(side_effect=lambda ch: webhooks[ch.id])
    relay_manager.normalizer.normalize_hinglish = AsyncMock(return_value="What is the plan bro")

    def make_msg(mid, content):
        m = MagicMock(spec=discord.Message)
        m.id = mid
        m.author.bot = False
        m.author.id = 42
        m.author.display_name = "Player"
        m.author.display_avatar.url = "https://example.com/a.png"
        m.webhook_id = None
        m.channel = chan_map[101]
        m.guild = chan_map[101].guild
        m.content = content
        m.attachments = []
        m.reference = None
        return m

    # First send calls Groq normalizer and delivers ONLY to ch 102 (same guild & group)
    await relay_manager.relay_message(make_msg(1, "kya naya plan hai bro"))
    relay_manager.normalizer.normalize_hinglish.assert_called_once()
    webhooks[102].send.assert_called_once()
    webhooks[103].send.assert_not_called()
    webhooks[201].send.assert_not_called()

    # Second identical send hits L1 normalizer cache -> zero extra Groq call!
    await relay_manager.relay_message(make_msg(2, "kya naya plan hai bro"))
    relay_manager.normalizer.normalize_hinglish.assert_called_once()

@pytest.mark.asyncio
async def test_webhook_failure_in_one_channel_does_not_abort_others(relay_manager):
    from unittest.mock import AsyncMock
    relay_manager.db.find_conversation_uuid = AsyncMock(return_value=None)
    relay_manager.db.record_relayed_messages = AsyncMock()
    relay_manager.translator.translate = AsyncMock(return_value=["Hola"])

    relay_manager.channels = {
        101: {"lang": "en", "is_romanized": False, "guild_id": 10, "group_id": "10:default"},
        102: {"lang": "es", "is_romanized": False, "guild_id": 10, "group_id": "10:default"},
        103: {"lang": "fr", "is_romanized": False, "guild_id": 10, "group_id": "10:default"},
    }

    chan_map = {}
    for cid in (101, 102, 103):
        ch = MagicMock(spec=discord.TextChannel)
        ch.id = cid
        ch.name = f"ch-{cid}"
        ch.guild = MagicMock(id=10)
        chan_map[cid] = ch

    good_wh = MagicMock()
    good_wh.send = AsyncMock(return_value=MagicMock(id=9103))

    async def fake_wh(ch):
        if ch.id == 102:
            raise RuntimeError("Missing Manage Webhooks")
        return good_wh

    relay_manager.bot.get_channel = MagicMock(side_effect=lambda cid: chan_map.get(cid))
    relay_manager.get_or_create_webhook = AsyncMock(side_effect=fake_wh)

    m = MagicMock(spec=discord.Message)
    m.id = 88
    m.author.bot = False
    m.author.id = 42
    m.author.display_name = "Player"
    m.author.display_avatar.url = "https://example.com/a.png"
    m.webhook_id = None
    m.channel = chan_map[101]
    m.guild = chan_map[101].guild
    m.content = "Hello team"
    m.attachments = []
    m.reference = None

    await relay_manager.relay_message(m)
    good_wh.send.assert_called_once()

@pytest.mark.asyncio
async def test_edit_skips_unchanged_and_updates_changed(relay_manager):
    from unittest.mock import AsyncMock
    relay_manager.db.get_relayed_entries_by_source_id = AsyncMock(return_value=[(102, 5002)])
    relay_manager.translator.translate = AsyncMock(return_value=["Hola mundo"])

    relay_manager.channels = {
        101: {"lang": "en", "is_romanized": False, "guild_id": 10, "group_id": "10:default"},
        102: {"lang": "es", "is_romanized": False, "guild_id": 10, "group_id": "10:default"},
    }
    dest_ch = MagicMock(spec=discord.TextChannel, id=102, name="es", guild=MagicMock(id=10))
    relay_manager.bot.get_channel = MagicMock(return_value=dest_ch)
    wh = MagicMock()
    wh.edit_message = AsyncMock()
    relay_manager.get_or_create_webhook = AsyncMock(return_value=wh)

    def make_msg(content):
        m = MagicMock(spec=discord.Message)
        m.id = 77
        m.author.bot = False
        m.author.id = 99
        m.webhook_id = None
        m.channel = MagicMock(spec=discord.TextChannel, id=101)
        m.guild = MagicMock(id=10)
        m.content = content
        m.attachments = []
        m.reference = None
        return m

    # Unchanged embed-unfurl edit must skip translation and webhook edit
    await relay_manager.handle_message_edit(make_msg("https://youtu.be/abc"), make_msg("https://youtu.be/abc"))
    relay_manager.translator.translate.assert_not_called()
    wh.edit_message.assert_not_called()

    # Actual text edit must re-translate and edit webhook
    await relay_manager.handle_message_edit(make_msg("Hello"), make_msg("Hello world"))
    wh.edit_message.assert_called_once()

@pytest.mark.asyncio
async def test_handle_message_delete_removes_relayed_webhooks(relay_manager):
    from unittest.mock import AsyncMock
    relay_manager.db.delete_entries_by_source_id = AsyncMock(return_value=[(102, 5002)])
    dest_ch = MagicMock(spec=discord.TextChannel, id=102, name="es", guild=MagicMock(id=10))
    relay_manager.bot.get_channel = MagicMock(return_value=dest_ch)
    wh = MagicMock()
    wh.delete_message = AsyncMock()
    relay_manager.get_or_create_webhook = AsyncMock(return_value=wh)

    msg = MagicMock(spec=discord.Message)
    msg.id = 77
    msg.guild = MagicMock(id=10)

    await relay_manager.handle_message_delete(msg)
    wh.delete_message.assert_called_once_with(5002)
