"""Main Discord client entry point, event dispatcher, and slash command interface for Polyglot Bot."""

import time
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from config import DISCORD_TOKEN, CHANNELS
from translator import TranslationService
from relay import WebhookRelayManager
from database import DatabaseManager

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
db_manager = DatabaseManager()
translator_service = TranslationService()
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

@bot.event
async def on_ready():
    await db_manager.connect()
    await db_manager.seed_default_channels(CHANNELS)
    await relay_manager.sync_channel_cache()

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

    stats_text = (
        f"• Total Translations: **{stats['total_translated']}**\n"
        f"• Cache Hits (Zero-API Saved): **{stats.get('cache_hits', 0)}**\n"
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
