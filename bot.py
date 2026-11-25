"""Main Discord client entry point, event dispatcher, and slash command interface for Polyglot Bot."""

import time
import asyncio
from typing import Optional, List, Dict, Any
import discord
from discord import app_commands
from discord.ext import commands, tasks
from config import DISCORD_TOKEN, CHANNELS
from translator import TranslationService, shield_syntax, restore_syntax
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

DEFAULT_TEST_PHRASES = {
    "en": "Hello! Testing Polyglot real-time translation latency.",
    "es": "¡Hola! Probando la latencia de traducción en tiempo real de Polyglot.",
    "ja": "こんにちは！Polyglotのリアルタイム翻訳レイテンシをテストしています。",
    "hi": "नमस्ते! Polyglot रीयल-टाइम अनुवाद लेटेंसी का परीक्षण कर रहा है।",
    "ko": "안녕하세요! Polyglot 실시간 번역 대기 시간을 테스트하고 있습니다.",
    "fr": "Bonjour! Test de la latence de traduction en temps réel de Polyglot.",
    "de": "Hallo! Testen der Polyglot-Echtzeit-Übersetzungslatenz.",
    "pt": "Olá! Testando a latência de tradução em tempo real do Polyglot.",
    "zh": "你好！正在测试Polyglot实时翻译延迟。",
    "ru": "Привет! Тестирование задержки перевода в реальном времени Polyglot.",
    "it": "Ciao! Test della latenza di traduzione in tempo reale di Polyglot.",
    "ar": "مرحباً! اختبار زمن استجابة الترجمة الفورية لـ Polyglot.",
    "id": "Halo! Menguji latensi terjemahan waktu nyata Polyglot.",
    "vi": "Xin chào! Đang kiểm tra độ trễ dịch thời gian thực của Polyglot.",
    "th": "สวัสดี! กำลังทดสอบเวลาแฝงในการแปลแบบเรียลไทม์ของ Polyglot",
    "tl": "Kumusta! Sinusubukan ang real-time translation latency ng Polyglot.",
    "tr": "Merhaba! Polyglot gerçek zamanlı çeviri gecikmesi test ediliyor.",
    "pl": "Cześć! Testowanie opóźnienia tłumaczenia w czasie rzeczywistym Polyglot.",
    "nl": "Hallo! Polyglot real-time vertaalvertraging testen.",
    "uk": "Привіт! Тестування затримки перекладу в реальному часі Polyglot.",
}

@tasks.loop(hours=24)
async def database_prune_task():
    """Daily background task to prune message sync records older than 60 days and old cache."""
    try:
        deleted = await db_manager.prune_old_sync_records(days=60)
        relay_manager.anti_spam.prune_old_state()
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

    migrated_or_pruned = False
    for channel_id, info in list(relay_manager.channels.items()):
        channel = bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await bot.fetch_channel(channel_id)
            except discord.NotFound:
                # Channel was permanently deleted in Discord while bot was offline
                await db_manager.remove_channel(channel_id)
                relay_manager.remove_channel_from_cache(channel_id)
                migrated_or_pruned = True
                print(f"🧹 Pruned deleted Discord channel ID {channel_id} from DB.")
                continue
            except Exception as e:
                print(f"   • Channel ID {channel_id} -> Fetch skipped ({e})")
                continue

        if isinstance(channel, discord.TextChannel) and info.get("guild_id", 0) == 0:
            await db_manager.migrate_channel_guild(channel_id, channel.guild.id)
            migrated_or_pruned = True

    if migrated_or_pruned:
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
            try:
                wh = await relay_manager.get_or_create_webhook(channel)
                try:
                    # Pre-warm TLS connection pool to Discord webhook edge
                    await wh.fetch(prefer_auth=False)
                    print(f"   • [{channel.guild.name}] #{channel.name} [{lang}]{mode} -> Webhook Ready & Pre-Warmed")
                except Exception:
                    print(f"   • [{channel.guild.name}] #{channel.name} [{lang}]{mode} -> Webhook Ready")
            except Exception as e:
                print(f"   • [{channel.guild.name}] #{channel.name} [{lang}]{mode} -> Webhook Setup Skipped ({e})")
        else:
            print(f"   • Channel ID {channel_id} [{lang}]{mode} -> Not cached or not TextChannel")

@bot.event
async def on_guild_channel_delete(channel: discord.abc.GuildChannel):
    """Automatically unlinks a deleted Discord channel from only its own guild."""
    if channel.id in relay_manager.channels:
        removed = await db_manager.remove_channel(channel.id, guild_id=channel.guild.id)
        relay_manager.remove_channel_from_cache(channel.id)
        if removed:
            print(f"🗑️ Auto-unlinked deleted channel #{channel.name} ({channel.id}) in guild '{channel.guild.name}'.")

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
        if len(translated_text) > 4096:
            translated_text = translated_text[:4093] + "..."
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
    try:
        await relay_manager.relay_message(message)
    except Exception as e:
        print(f"Relay error processing message {message.id}: {e}")
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
    is_romanized="Romanized/slang input (e.g. Hinglish/Bahasa Gaul); outbound slang currently targets Hindi",
    group="Optional translation group name inside this server (default: 'default')"
)
@app_commands.choices(language=SUPPORTED_LANGUAGES)
async def translate_add(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    language: app_commands.Choice[str],
    is_romanized: bool = False,
    group: str = "default"
):
    """Links a channel to this server's translation group with optional Romanized AI processing."""
    await interaction.response.defer(ephemeral=False)
    if not interaction.guild:
        await interaction.followup.send("❌ This command can only be used inside a Discord server.")
        return

    lang_code = language.value.lower()
    guild_id = interaction.guild.id
    scoped_group = db_manager.scoped_group_id(guild_id, group)
    await db_manager.add_channel(
        channel.id,
        lang_code,
        is_romanized=is_romanized,
        group_id=group,
        guild_id=guild_id
    )
    relay_manager.add_channel_to_cache(
        channel.id,
        lang_code,
        is_romanized,
        guild_id=guild_id,
        group_id=scoped_group
    )

    # Initialize webhook immediately
    try:
        wh = await relay_manager.get_or_create_webhook(channel)
        wh_status = f"Webhook `{wh.name}` ready."
    except Exception as e:
        wh_status = f"Warning: Could not create webhook ({e}). Check bot permissions."

    roman_tag = " *(AI Romanized Normalization Active)*" if is_romanized else ""
    group_label = group.strip().lower() or "default"
    embed = discord.Embed(
        title="✅ Language Channel Linked",
        description=f"Channel {channel.mention} is now linked to **{language.name}** in group **`{group_label}`**{roman_tag}!\n{wh_status}",
        color=0x2ECC71
    )
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="translate-remove", description="Unlink a channel from this server's translation network.")
@app_commands.default_permissions(manage_channels=True)
@app_commands.describe(channel="The channel to unlink")
async def translate_remove(interaction: discord.Interaction, channel: discord.TextChannel):
    """Removes a channel from this server's translation network."""
    await interaction.response.defer(ephemeral=False)
    guild_id = interaction.guild_id

    removed = await db_manager.remove_channel(channel.id, guild_id=guild_id)
    relay_manager.remove_channel_from_cache(channel.id)

    if removed:
        embed = discord.Embed(
            title="🗑️ Channel Unlinked",
            description=f"Channel {channel.mention} has been removed from **{interaction.guild.name if interaction.guild else 'this server'}**'s translation network.",
            color=0xE74C3C
        )
    else:
        embed = discord.Embed(
            title="⚠️ Channel Not Found",
            description=f"Channel {channel.mention} was not found in this server's active channels.",
            color=0xF1C40F
        )
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="translate-reset", description="Unlinks all translation channels (or one group) in THIS server only.")
@app_commands.default_permissions(manage_channels=True)
@app_commands.describe(group="Optional group name to reset (leave blank to reset all groups in this server)")
async def translate_reset(interaction: discord.Interaction, group: Optional[str] = None):
    """Safely unlinks all translation channels for the current server without affecting other servers."""
    await interaction.response.defer(ephemeral=False)
    if not interaction.guild:
        await interaction.followup.send("❌ This command can only be used inside a Discord server.")
        return

    removed_ids = await db_manager.remove_guild_channels(interaction.guild.id, group_name=group)
    for cid in removed_ids:
        relay_manager.remove_channel_from_cache(cid)

    scope_desc = f"group **`{group}`** in " if group else ""
    if removed_ids:
        embed = discord.Embed(
            title="🧹 Server Translation Links Cleared",
            description=f"Unlinked **{len(removed_ids)}** channel(s) from {scope_desc}**{interaction.guild.name}**.\nOther servers were not affected.",
            color=0xE74C3C
        )
    else:
        embed = discord.Embed(
            title="ℹ️ Nothing to Reset",
            description=f"No configured translation channels were found for {scope_desc}**{interaction.guild.name}**.",
            color=0x3498DB
        )
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="translate-setup", description="1-Click Wizard: Automatically creates category and paired language channels.")
@app_commands.default_permissions(manage_channels=True)
@app_commands.describe(group="Optional group name for these channels inside this server (default: 'default')")
async def translate_setup(interaction: discord.Interaction, group: str = "default"):
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
        clean_group = (group or "default").strip().lower() or "default"
        category_name = "🌍 Polyglot Network" if clean_group == "default" else f"🌍 Polyglot ({clean_group})"
        category = discord.utils.get(guild.categories, name=category_name)
        if not category:
            category = await guild.create_category(category_name)

        preset_channels = [
            ("english", "en", False),
            ("spanish", "es", False),
            ("japanese", "ja", False),
            ("hindi", "hi", True),
        ]

        scoped_group = db_manager.scoped_group_id(guild.id, clean_group)
        created_info = []
        for ch_name, lang_code, is_romanized in preset_channels:
            ch = discord.utils.get(category.text_channels, name=ch_name)
            if not ch:
                ch = await category.create_text_channel(name=ch_name)

            await db_manager.add_channel(
                ch.id,
                lang_code,
                is_romanized=is_romanized,
                group_id=clean_group,
                guild_id=guild.id
            )
            relay_manager.add_channel_to_cache(
                ch.id,
                lang_code,
                is_romanized,
                guild_id=guild.id,
                group_id=scoped_group
            )
            await relay_manager.get_or_create_webhook(ch)
            roman_note = " *(AI Romanized)*" if is_romanized else ""
            created_info.append(f"• {ch.mention} [**{lang_code.upper()}**]{roman_note}")

        embed = discord.Embed(
            title=f"🎉 Polyglot Network Configured ({guild.name})!",
            description=f"Group **`{clean_group}`** has been set up for this server:\n\n" + "\n".join(created_info) + "\n\nAny message sent in one of these channels will automatically relay and translate to the others!",
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
        if interaction.guild and src_channel.guild.id != interaction.guild.id:
            await interaction.followup.send(
                "ℹ️ Original message belongs to a different server and cannot be viewed here.",
                ephemeral=True
            )
            return
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

@bot.tree.command(name="translate-status", description="Displays Polyglot translation bot health, channels, and metrics for this server.")
async def translate_status(interaction: discord.Interaction):
    """Slash command to display bot status, ping, this server's channels, and statistics."""
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("❌ This command can only be used inside a Discord server.", ephemeral=True)
        return

    uptime_seconds = int(time.time() - start_time)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{hours}h {minutes}m {seconds}s"

    latency_ms = round(bot.latency * 1000, 1)

    embed = discord.Embed(
        title=f"🌐 Polyglot Dashboard — {guild.name}",
        color=0x2ECC71
    )
    embed.add_field(name="Bot Status", value="🟢 Online & Relaying", inline=True)
    embed.add_field(name="Gateway Ping", value=f"`{latency_ms} ms`", inline=True)
    embed.add_field(name="Uptime", value=f"`{uptime_str}`", inline=True)

    channel_lines = []
    for cid, info in relay_manager.channels.items():
        ch = guild.get_channel(cid)
        if not ch or not isinstance(ch, discord.TextChannel):
            continue
        raw_group = info.get("group_id", "default")
        group_label = raw_group.split(":", 1)[-1] if ":" in raw_group else raw_group
        roman = " *(AI Romanized)*" if info.get("is_romanized") else ""
        channel_lines.append(f"• **{info['lang'].upper()}**: <#{cid}> (`#{ch.name}` | group: `{group_label}`){roman}")
    channels_display = "\n".join(channel_lines) if channel_lines else "No channels configured in this server."

    embed.add_field(name=f"Active Language Channels ({len(channel_lines)})", value=channels_display, inline=False)

    stats = translator_service.stats
    db_stats = await db_manager.get_stats(guild_id=guild.id)
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

@bot.tree.command(name="translate-latency", description="Sends a live test message to any channel and measures translation, LLM, and webhook latency.")
@app_commands.describe(
    target_channel="Channel to test delivery to (e.g. #hindi, #spanish, #japanese)",
    message="Custom message to test with (optional, defaults to standard language test phrase)",
    source_language="Source language (optional override, defaults to current channel)"
)
@app_commands.choices(source_language=SUPPORTED_LANGUAGES)
async def translate_latency(
    interaction: discord.Interaction,
    target_channel: Optional[discord.TextChannel] = None,
    message: Optional[str] = None,
    source_language: Optional[app_commands.Choice[str]] = None
):
    """Sends a live benchmark message and records gateway, translation, LLM, and webhook delivery latency."""
    await interaction.response.defer(ephemeral=False)
    guild = interaction.guild
    if not guild:
        await interaction.followup.send("❌ This command must be used inside a Discord server.")
        return

    # 1. Determine Source Channel & Language
    src_info = relay_manager.channels.get(interaction.channel_id)
    is_src_romanized = src_info.get("is_romanized", False) if src_info else False
    if source_language:
        src_lang = source_language.value
    elif src_info:
        src_lang = src_info["lang"]
    else:
        src_lang = "en"

    # 2. Determine Destination Channel & Target Language (strictly within the same guild & group)
    dest_channel = target_channel
    src_group = src_info.get("group_id", "default") if src_info else None
    if not dest_channel:
        for cid, info in relay_manager.channels.items():
            if cid != interaction.channel_id:
                if src_group and info.get("group_id", "default") != src_group:
                    continue
                candidate = guild.get_channel(cid)
                if isinstance(candidate, discord.TextChannel):
                    dest_channel = candidate
                    break
    if not dest_channel:
        dest_channel = interaction.channel

    if not isinstance(dest_channel, discord.TextChannel):
        await interaction.followup.send("❌ Destination must be a valid text channel.")
        return

    dest_info = relay_manager.channels.get(dest_channel.id)
    is_target_romanized = dest_info.get("is_romanized", False) if dest_info else False
    if dest_info:
        tgt_lang = dest_info["lang"]
    else:
        tgt_lang = "es" if src_lang != "es" else "en"

    # 3. Determine Text to Test
    text_to_test = message.strip() if message and message.strip() else DEFAULT_TEST_PHRASES.get(src_lang, "Hello! Testing Polyglot real-time translation latency.")

    # 4. Measure Translation & LLM Pipeline
    llm_ms = 0.0
    translation_ms = 0.0
    provider_name = ""
    translated_text = text_to_test

    try:
        # Case A: Delivering to a Romanized channel (e.g. #hindi) -> Requires Groq LLM Romanizer!
        if tgt_lang == "hi" and is_target_romanized:
            if src_lang == "en":
                base_english = text_to_test
            else:
                t_tr0 = time.perf_counter()
                en_chunks = await translator_service.translate(text_to_test, source_lang=src_lang, target_lang="en")
                t_tr1 = time.perf_counter()
                translation_ms = round((t_tr1 - t_tr0) * 1000, 2)
                base_english = en_chunks[0] if en_chunks else text_to_test

            shielded_en, en_tokens = shield_syntax(base_english)
            t_llm0 = time.perf_counter()
            romanized_raw = await relay_manager.normalizer.to_romanized_hindi(shielded_en)
            t_llm1 = time.perf_counter()
            llm_ms = round((t_llm1 - t_llm0) * 1000, 2)
            translated_text = restore_syntax(romanized_raw, en_tokens) if romanized_raw else base_english
            provider_name = f"🤖 Groq LPU AI Romanizer ({llm_ms} ms)"
            if translation_ms > 0:
                provider_name = f"🔷 Azure ({translation_ms} ms) ➔ 🤖 Groq LPU ({llm_ms} ms)"

        # Case B: Sent from a Romanized channel (e.g. #hindi, #indonesian) -> Requires Groq LLM Normalizer!
        elif is_src_romanized:
            shielded_in, in_tokens = shield_syntax(text_to_test)
            t_llm0 = time.perf_counter()
            norm_en = await relay_manager.normalizer.normalize_slang(shielded_in)
            t_llm1 = time.perf_counter()
            llm_ms = round((t_llm1 - t_llm0) * 1000, 2)
            normalized_english = restore_syntax(norm_en, in_tokens) if norm_en else text_to_test

            if tgt_lang == "en":
                translated_text = normalized_english
                provider_name = f"🤖 Groq LPU AI Normalizer ({llm_ms} ms)"
            else:
                t_tr0 = time.perf_counter()
                chunks = await translator_service.translate(normalized_english, source_lang="en", target_lang=tgt_lang)
                t_tr1 = time.perf_counter()
                translation_ms = round((t_tr1 - t_tr0) * 1000, 2)
                translated_text = chunks[0] if chunks else normalized_english
                provider_name = f"🤖 Groq LPU ({llm_ms} ms) ➔ 🔷 Azure ({translation_ms} ms)"

        # Case C: Standard Translation Cascade (Azure -> MyMemory -> Google gtx)
        else:
            before_stats = translator_service.stats.copy()
            t0 = time.perf_counter()
            chunks = await translator_service.translate(
                text=text_to_test,
                source_lang=src_lang,
                target_lang=tgt_lang
            )
            t1 = time.perf_counter()
            translation_ms = round((t1 - t0) * 1000, 2)
            translated_text = chunks[0] if chunks else text_to_test

            # Identify Which Provider Answered
            if translator_service.stats["cache_hits"] > before_stats["cache_hits"]:
                provider_name = "⚡ L1/L2 Cache (0 ms computation)"
            elif translator_service.stats["azure_success"] > before_stats["azure_success"]:
                provider_name = "🔷 Azure AI Translator (westus2, Keep-Alive)"
            elif translator_service.stats["deepl_success"] > before_stats["deepl_success"]:
                provider_name = "🟧 DeepL Free API"
            elif translator_service.stats["mymemory_success"] > before_stats["mymemory_success"]:
                provider_name = "🟪 MyMemory API"
            elif translator_service.stats["google_success"] > before_stats["google_success"]:
                provider_name = "🌐 Google Public Client (client=gtx)"
            elif translator_service.stats.get("llm_success", 0) > before_stats.get("llm_success", 0):
                provider_name = "🤖 Groq / OpenRouter AI Pool"
            else:
                provider_name = "Passthrough / Same Language"

    except Exception as e:
        await interaction.followup.send(f"❌ Translation / LLM engine error: `{e}`")
        return

    # 5. Measure Webhook Delivery Step
    try:
        wh = await relay_manager.get_or_create_webhook(dest_channel)
        t2 = time.perf_counter()
        avatar_url = None
        if bot.user:
            if hasattr(bot.user.display_avatar, "with_size"):
                avatar_url = bot.user.display_avatar.with_size(64).url
            else:
                avatar_url = bot.user.display_avatar.url

        mode_badge = " [AI Romanized]" if is_target_romanized else ""
        sent_msg = await wh.send(
            content=f"⚡ **[Latency Benchmark]** {translated_text}",
            username=f"Polyglot Ping [{src_lang.upper()} ➔ {tgt_lang.upper()}]{mode_badge}",
            avatar_url=avatar_url,
            allowed_mentions=discord.AllowedMentions.none(),
            wait=True
        )
        t3 = time.perf_counter()
        webhook_ms = round((t3 - t2) * 1000, 2)
    except Exception as e:
        await interaction.followup.send(f"❌ Webhook delivery error in {dest_channel.mention}: `{e}`")
        return

    # 6. Total End-to-End Latency
    gateway_ms = round(bot.latency * 1000, 1)
    compute_ms = round(translation_ms + llm_ms, 2)
    total_pipeline_ms = round(compute_ms + webhook_ms, 2)

    # 7. Scorecard Performance Rating & Color
    if total_pipeline_ms < 350:
        embed_color = 0x2ECC71  # Emerald Green
        perf_badge = "🚀 Ultra-Fast (Near Platform Floor)"
    elif total_pipeline_ms < 600:
        embed_color = 0x3498DB  # Blue
        perf_badge = "⚡ Fast & Responsive"
    else:
        embed_color = 0xF1C40F  # Amber
        perf_badge = "⏳ Normal / Slight Network Jitter"

    embed = discord.Embed(
        title="⏱️ Polyglot Live Latency Benchmark",
        description=f"Performance rating: **{perf_badge}**",
        color=embed_color
    )

    breakdown_lines = [
        f"• 🚀 **Total End-to-End**: `{total_pipeline_ms} ms`"
    ]
    if llm_ms > 0:
        breakdown_lines.append(f"• 🤖 **Groq LPU LLM Time**: `{llm_ms} ms`")
    if translation_ms > 0:
        breakdown_lines.append(f"• ⚡ **Azure Translation**: `{translation_ms} ms`")
    breakdown_lines.extend([
        f"• 📤 **Discord Webhook (`wh.send`)**: `{webhook_ms} ms`",
        f"• 📡 **Gateway WebSocket Ping**: `{gateway_ms} ms`"
    ])

    embed.add_field(
        name="📊 Latency Breakdown",
        value="\n".join(breakdown_lines),
        inline=False
    )

    embed.add_field(
        name="🌐 Active Pipeline Provider",
        value=f"**{provider_name}**",
        inline=False
    )

    embed.add_field(
        name=f"📝 Source Message [{src_lang.upper()}]",
        value=f"```{text_to_test}```",
        inline=False
    )

    dest_roman_str = " *(AI Romanized)*" if is_target_romanized else ""
    embed.add_field(
        name=f"🎯 Relayed Webhook [{tgt_lang.upper()}]{dest_roman_str}",
        value=f"```{translated_text}```\nDelivered to: {dest_channel.mention} • [Jump to Message]({sent_msg.jump_url})",
        inline=False
    )

    embed.set_footer(text="Polyglot Latency Diagnostic • Platform floor is ~350ms")
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="translate-ping", description="Quick shortcut to benchmark relay, LLM, and webhook latency to any channel.")
@app_commands.describe(
    target_channel="Channel to test delivery to (e.g. #hindi, #spanish, #japanese)",
    message="Custom message to test with (optional)"
)
async def translate_ping(
    interaction: discord.Interaction,
    target_channel: Optional[discord.TextChannel] = None,
    message: Optional[str] = None
):
    """Shortcut command calling translate_latency with target_channel."""
    await translate_latency.callback(interaction, target_channel=target_channel, message=message)

async def setup_bot():
    """Initializes command trees and event loops."""
    async def setup_hook():
        try:
            synced = await bot.tree.sync()
            print(f"Synced {len(synced)} application commands.")
        except Exception as e:
            print(f"Failed to sync application commands: {e}")

    bot.setup_hook = setup_hook
    async with bot:
        try:
            await bot.start(DISCORD_TOKEN)
        finally:
            await db_manager.close()

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise ValueError("DISCORD_TOKEN is missing from .env")
    asyncio.run(setup_bot())
