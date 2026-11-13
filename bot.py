"""Main Discord client entry point, event dispatcher, and slash command interface for Polyglot Bot."""

import time
import asyncio
import discord
from discord import app_commands
from discord.ext import commands, tasks
from config import DISCORD_TOKEN, CHANNELS
from translator import TranslationService
from relay import WebhookRelayManager
from database import DatabaseManager

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
db_manager = DatabaseManager()
translator_service = TranslationService(db=db_manager)
relay_manager = WebhookRelayManager(bot, translator_service, db_manager)
start_time = time.time()

SUPPORTED_LANGUAGES = [
    app_commands.Choice(name="Korean (ko)", value="ko"),
    app_commands.Choice(name="Japanese (ja)", value="ja"),
    app_commands.Choice(name="Hindi (hi)", value="hi"),
    app_commands.Choice(name="Spanish (es)", value="es"),
    app_commands.Choice(name="English (en)", value="en"),
    app_commands.Choice(name="French (fr)", value="fr"),
    app_commands.Choice(name="German (de)", value="de"),
    app_commands.Choice(name="Portuguese (pt)", value="pt"),
    app_commands.Choice(name="Chinese Simplified (zh)", value="zh"),
    app_commands.Choice(name="Russian (ru)", value="ru"),
    app_commands.Choice(name="Italian (it)", value="it"),
    app_commands.Choice(name="Arabic (ar)", value="ar"),
    app_commands.Choice(name="Indonesian (id)", value="id"),
    app_commands.Choice(name="Vietnamese (vi)", value="vi"),
    app_commands.Choice(name="Thai (th)", value="th"),
    app_commands.Choice(name="Tagalog / Filipino (tl)", value="tl"),
    app_commands.Choice(name="Turkish (tr)", value="tr"),
    app_commands.Choice(name="Polish (pl)", value="pl"),
    app_commands.Choice(name="Dutch (nl)", value="nl"),
    app_commands.Choice(name="Ukrainian (uk)", value="uk"),
]

FLAG_LANG_MAP = {
    "🇪🇸": "es", "🇲🇽": "es",
    "🇯🇵": "ja",
    "🇫🇷": "fr",
    "🇩🇪": "de",
    "🇮🇳": "hi",
    "🇰🇷": "ko",
    "🇺🇸": "en", "🇬🇧": "en",
    "🇮🇹": "it",
    "🇵🇹": "pt", "🇧🇷": "pt",
    "🇷🇺": "ru",
    "🇨🇳": "zh",
    "🇻🇳": "vi",
    "🇹🇭": "th",
    "🇵🇭": "tl",
    "🇹🇷": "tr",
    "🇳🇱": "nl",
    "🇵🇱": "pl",
    "🇺🇦": "uk",
    "🇸🇦": "ar",
    "🇮🇩": "id"
}

@tasks.loop(hours=24)
async def database_prune_task():
    """Daily background task to prune message sync records older than 60 days."""
    try:
        deleted = await db_manager.prune_old_sync_records(days=60)
        if deleted > 0:
            print(f"🧹 Pruned {deleted} old sync records (>60 days old).")
    except Exception as e:
        print(f"Database prune task error: {e}")

@bot.event
async def on_ready():
    await db_manager.connect()
    await db_manager.seed_default_channels(CHANNELS)
    await db_manager.seed_common_translations()
    await relay_manager.sync_channel_cache()

    if not database_prune_task.is_running():
        database_prune_task.start()

    print(f"✅ Logged in as {bot.user.name} ({bot.user.id})")
    print(f"🗄️ SQLite Database connected (WAL mode active).")
    print(f"📡 Active channels in memory: {len(relay_manager.channels)}")

    for channel_id, info in relay_manager.channels.items():
        channel = bot.get_channel(channel_id)
        lang = info["lang"].upper()
        mode = " [AI Romanized]" if info.get("is_romanized") else ""
        if isinstance(channel, discord.TextChannel):
            await relay_manager.get_or_create_webhook(channel)
            print(f"   • #{channel.name} [{lang}]{mode} -> Webhook Ready")
        else:
            print(f"   • Channel ID {channel_id} [{lang}]{mode} -> Not cached or not TextChannel")

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    """Translates a message on-demand when any user reacts with a country flag emoji."""
    emoji_str = str(payload.emoji)
    target_lang = FLAG_LANG_MAP.get(emoji_str)
    if not target_lang:
        return

    # Don't translate bot reactions
    if bot.user and payload.user_id == bot.user.id:
        return

    channel = bot.get_channel(payload.channel_id)
    if not isinstance(channel, discord.TextChannel):
        return

    try:
        msg = await channel.fetch_message(payload.message_id)
        if not msg.content or (msg.author.bot and not msg.webhook_id):
            return

        user = bot.get_user(payload.user_id) or await bot.fetch_user(payload.user_id)

        # Translate on demand
        translated_chunks = await translator_service.translate(
            text=msg.content,
            source_lang="auto",
            target_lang=target_lang
        )
        if not translated_chunks:
            return

        translated_text = " ".join(translated_chunks)
        embed = discord.Embed(
            title=f"{emoji_str} Translation ({target_lang.upper()})",
            description=translated_text,
            color=0x3498DB
        )
        embed.set_author(name=msg.author.display_name, icon_url=msg.author.display_avatar.url)
        embed.set_footer(text=f"Requested by {user.display_name} • Polyglot Quick Translate")

        await channel.send(embed=embed, reference=msg, mention_author=False)
    except Exception as e:
        print(f"Flag translation error: {e}")

@bot.event
async def on_message(message: discord.Message):
    await relay_manager.relay_message(message)
    await bot.process_commands(message)

@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    await relay_manager.handle_message_edit(before, after)

@bot.event
async def on_message_delete(message: discord.Message):
    await relay_manager.handle_message_delete(message)

@bot.tree.command(name="translate-add", description="Link a Discord text channel to a translation language.")
@app_commands.default_permissions(manage_channels=True)
@app_commands.describe(
    channel="The text channel to link",
    language="The language spoken in this channel",
    is_romanized="Whether users type in Romanized/slang script (e.g. Hinglish)"
)
@app_commands.choices(language=SUPPORTED_LANGUAGES)
async def translate_add(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    language: app_commands.Choice[str],
    is_romanized: bool = False
):
    """Links a channel to the translation network with optional Romanized AI processing."""
    await interaction.response.defer(ephemeral=False)

    lang_code = language.value.lower()
    await db_manager.add_channel(channel.id, lang_code, is_romanized=is_romanized)
    relay_manager.add_channel_to_cache(channel.id, lang_code, is_romanized)

    # Initialize webhook immediately
    try:
        wh = await relay_manager.get_or_create_webhook(channel)
        wh_status = f"Webhook `{wh.name}` ready."
    except Exception as e:
        wh_status = f"Warning: Could not create webhook ({e}). Check bot permissions."

    roman_tag = " *(AI Romanized Normalization Active)*" if is_romanized else ""
    embed = discord.Embed(
        title="✅ Language Channel Linked",
        description=f"Channel {channel.mention} is now linked to **{language.name}**{roman_tag}!\n{wh_status}",
        color=0x2ECC71
    )
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="translate-remove", description="Unlink a channel from the translation network.")
@app_commands.default_permissions(manage_channels=True)
@app_commands.describe(channel="The channel to unlink")
async def translate_remove(interaction: discord.Interaction, channel: discord.TextChannel):
    """Removes a channel from the translation network."""
    await interaction.response.defer(ephemeral=False)

    removed = await db_manager.remove_channel(channel.id)
    relay_manager.remove_channel_from_cache(channel.id)

    if removed:
        embed = discord.Embed(
            title="🗑️ Channel Unlinked",
            description=f"Channel {channel.mention} has been removed from the translation network.",
            color=0xE74C3C
        )
    else:
        embed = discord.Embed(
            title="⚠️ Channel Not Found",
            description=f"Channel {channel.mention} was not found in active channels.",
            color=0xF1C40F
        )
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="translate-setup", description="1-Click Wizard: Automatically creates category and paired language channels.")
@app_commands.default_permissions(manage_channels=True)
async def translate_setup(interaction: discord.Interaction):
    """Automatically creates a '🌍 Polyglot Network' category with #english, #spanish, #japanese, #hindi."""
    await interaction.response.defer(ephemeral=False)
    guild = interaction.guild
    if not guild:
        await interaction.followup.send("❌ This command can only be used inside a Discord server.")
        return

    me = guild.me
    if not me.guild_permissions.manage_channels or not me.guild_permissions.manage_webhooks:
        await interaction.followup.send("❌ Bot needs **Manage Channels** and **Manage Webhooks** permissions to run auto-setup.")
        return

    try:
        category = discord.utils.get(guild.categories, name="🌍 Polyglot Network")
        if not category:
            category = await guild.create_category("🌍 Polyglot Network")

        preset_channels = [
            ("english", "en", False),
            ("spanish", "es", False),
            ("japanese", "ja", False),
            ("hindi", "hi", True),
        ]

        created_info = []
        for ch_name, lang_code, is_romanized in preset_channels:
            ch = discord.utils.get(category.text_channels, name=ch_name)
            if not ch:
                ch = await category.create_text_channel(name=ch_name)

            await db_manager.add_channel(ch.id, lang_code, is_romanized=is_romanized)
            relay_manager.add_channel_to_cache(ch.id, lang_code, is_romanized)
            await relay_manager.get_or_create_webhook(ch)
            roman_note = " *(AI Romanized)*" if is_romanized else ""
            created_info.append(f"• {ch.mention} [**{lang_code.upper()}**]{roman_note}")

        embed = discord.Embed(
            title="🎉 Polyglot Network Configured!",
            description="The translation network has been automatically set up:\n\n" + "\n".join(created_info) + "\n\nAny message sent in one of these channels will automatically relay and translate to the others!",
            color=0x2ECC71
        )
        embed.set_footer(text="Ready to chat! Use // at start of message to opt-out.")
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"❌ Error during auto-setup: `{e}`")

@bot.tree.command(name="translate-doctor", description="Audits channel permissions, webhooks, and translation engine health.")
@app_commands.default_permissions(manage_channels=True)
async def translate_doctor(interaction: discord.Interaction):
    """Audits all active channels for required permissions, webhooks, and provider status."""
    await interaction.response.defer(ephemeral=False)
    guild = interaction.guild
    if not guild:
        await interaction.followup.send("❌ This command can only be used inside a Discord server.")
        return

    channel_reports = []
    all_ok = True

    for cid, info in relay_manager.channels.items():
        ch = guild.get_channel(cid)
        if not ch or not isinstance(ch, discord.TextChannel):
            continue

        perms = ch.permissions_for(guild.me)
        missing_perms = []
        if not perms.manage_webhooks:
            missing_perms.append("Manage Webhooks")
        if not perms.send_messages:
            missing_perms.append("Send Messages")
        if not perms.view_channel:
            missing_perms.append("View Channel")
        if not perms.read_message_history:
            missing_perms.append("Read Message History")

        wh_ok = cid in relay_manager.webhooks
        if not wh_ok:
            try:
                await relay_manager.get_or_create_webhook(ch)
                wh_ok = True
            except Exception:
                wh_ok = False

        if missing_perms or not wh_ok:
            all_ok = False
            issues = []
            if missing_perms:
                issues.append(f"Missing perms: `{', '.join(missing_perms)}`")
            if not wh_ok:
                issues.append("Webhook creation failed")
            channel_reports.append(f"⚠️ {ch.mention} [{info['lang'].upper()}]: " + " | ".join(issues))
        else:
            channel_reports.append(f"✅ {ch.mention} [{info['lang'].upper()}]: Permissions & Webhook ready")

    cb_status = []
    for name, cb in translator_service.circuit_breakers.items():
        state_icon = "🟢 Healthy" if cb.is_healthy else f"🔴 Cooldown ({int(max(0, cb.cooldown_until - time.time()))}s left)"
        cb_status.append(f"• **{name}**: {state_icon}")

    embed = discord.Embed(
        title="🩺 Polyglot Translation Doctor",
        description="Health and permission audit across your server channels:",
        color=0x2ECC71 if all_ok else 0xE67E22
    )

    embed.add_field(
        name="Channel Permission & Webhook Audit",
        value="\n".join(channel_reports) if channel_reports else "No channels configured in this server.",
        inline=False
    )
    embed.add_field(
        name="Translation Engine Circuit Breakers",
        value="\n".join(cb_status),
        inline=False
    )

    if all_ok:
        embed.set_footer(text="Everything is healthy! All messages will relay smoothly.")
    else:
        embed.set_footer(text="Action required: Grant the missing permissions to Polyglot Bot.")

    await interaction.followup.send(embed=embed)

@bot.tree.context_menu(name="View Original Text")
async def view_original_text(interaction: discord.Interaction, message: discord.Message):
    """Context menu to view the original untranslated text of any relayed message."""
    await interaction.response.defer(ephemeral=True)

    info = await db_manager.get_source_message_info(message.id)
    if not info:
        await interaction.followup.send(
            "ℹ️ This message was not found in the translation sync database (it may be a direct message or sent before bot was installed).",
            ephemeral=True
        )
        return

    src_channel_id, src_message_id = info
    src_channel = bot.get_channel(src_channel_id)

    original_author = "Unknown"
    original_content = "Could not fetch original content."
    original_avatar = None
    created_at_str = "Unknown"

    if isinstance(src_channel, discord.TextChannel):
        try:
            src_msg = await src_channel.fetch_message(src_message_id)
            original_author = src_msg.author.display_name
            original_content = src_msg.content or "*(Attachment only)*"
            original_avatar = src_msg.author.display_avatar.url
            created_at_str = src_msg.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
        except Exception:
            original_content = "Original message may have been deleted."

    embed = discord.Embed(
        title="🔍 Original Message Details",
        description=original_content,
        color=0x3498DB
    )
    embed.add_field(name="Original Author", value=original_author, inline=True)
    embed.add_field(name="Source Channel", value=f"<#{src_channel_id}>", inline=True)
    embed.add_field(name="Sent At", value=created_at_str, inline=True)
    if original_avatar:
        embed.set_thumbnail(url=original_avatar)
    embed.set_footer(text="Polyglot Message Verification • Visible only to you")

    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="translate-status", description="Displays Polyglot translation bot health, channels, and metrics.")
async def translate_status(interaction: discord.Interaction):
    """Slash command to display bot status, ping, channels, and statistics."""
    uptime_seconds = int(time.time() - start_time)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{hours}h {minutes}m {seconds}s"

    latency_ms = round(bot.latency * 1000, 1)

    embed = discord.Embed(
        title="🌐 Polyglot Translator Dashboard",
        color=0x2ECC71
    )
    embed.add_field(name="Bot Status", value="🟢 Online & Relaying", inline=True)
    embed.add_field(name="Gateway Ping", value=f"`{latency_ms} ms`", inline=True)
    embed.add_field(name="Uptime", value=f"`{uptime_str}`", inline=True)

    channel_lines = []
    for cid, info in relay_manager.channels.items():
        ch = bot.get_channel(cid)
        name = ch.name if ch else "channel"
        roman = " *(AI Romanized)*" if info.get("is_romanized") else ""
        channel_lines.append(f"• **{info['lang'].upper()}**: <#{cid}> (`#{name}`){roman}")
    channels_display = "\n".join(channel_lines) if channel_lines else "No channels configured."

    embed.add_field(name="Active Language Channels", value=channels_display, inline=False)

    stats = translator_service.stats
    db_stats = await db_manager.get_stats()
    ai_stats = relay_manager.normalizer.stats

    total_tr = stats.get("total_translated", 0)
    cache_hits = stats.get("cache_hits", 0)
    hit_rate = round((cache_hits / total_tr * 100), 1) if total_tr > 0 else 0.0

    cb_lines = []
    for name, cb in translator_service.circuit_breakers.items():
        icon = "🟢" if cb.is_healthy else "🔴 Cooldown"
        cb_lines.append(f"`{name}`: {icon}")
    cb_text = " | ".join(cb_lines)

    stats_text = (
        f"• Total Translations: **{stats['total_translated']}**\n"
        f"• Cache Hit Rate: **{hit_rate}%** ({cache_hits} Zero-Cost Hits Saved)\n"
        f"• Circuit Breakers: {cb_text}\n"
        f"• DeepL: `{stats['deepl_success']}` | Azure: `{stats['azure_success']}`\n"
        f"• MyMemory: `{stats['mymemory_success']}` | Google: `{stats['google_success']}`\n"
        f"• LLM Cascading Failover: `{stats.get('llm_success', 0)}` (Multi-Model Pool)\n"
        f"• Hinglish AI Detected: **{ai_stats['hinglish_detections']}** (Groq: `{ai_stats['groq_normalizations']}`)\n"
        f"• Total Synced Messages (DB): **{db_stats['total_synced_messages']}**\n"
        f"• Error Count: **{stats['errors']}**"
    )
    embed.add_field(name="Translation Provider & DB Metrics", value=stats_text, inline=False)
    embed.set_footer(text="Polyglot Discord Translation Engine • v2.0")

    await interaction.response.send_message(embed=embed)

async def setup_bot():
    """Initializes command trees and event loops."""
    async with bot:
        @bot.event
        async def on_connect():
            try:
                synced = await bot.tree.sync()
                print(f"Synced {len(synced)} application commands.")
            except Exception as e:
                print(f"Failed to sync application commands: {e}")

        try:
            await bot.start(DISCORD_TOKEN)
        finally:
            await db_manager.close()

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise ValueError("DISCORD_TOKEN is missing from .env")
    asyncio.run(setup_bot())
