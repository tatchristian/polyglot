"""Webhook relay management, concurrency throttling, SQLite persistence, and Romanized channel routing."""

import uuid
import asyncio
from collections import OrderedDict
from typing import Dict, List, Tuple, Optional, Any
import discord
from config import (
    COMMAND_PREFIXES,
    MAX_CONCURRENT_RELAYS,
)
from translator import TranslationService, shield_syntax, restore_syntax, is_passthrough_text, chunk_message
from database import DatabaseManager
from hinglish_gatekeeper import is_potential_hinglish, is_already_english
from slang_normalizer import SlangNormalizer, HinglishNormalizer, has_native_script
from spam_filter import AntiSpamManager

class LRUMessageMap:
    """Bounded LRU cache for in-memory L1 lookup."""

    def __init__(self, maxsize: int = 1000):
        self.maxsize = maxsize
        self._cache: OrderedDict[int, List[Tuple[int, int]]] = OrderedDict()

    def put(self, source_id: int, relays: List[Tuple[int, int]]):
        if source_id in self._cache:
            self._cache.move_to_end(source_id)
        self._cache[source_id] = relays
        if len(self._cache) > self.maxsize:
            self._cache.popitem(last=False)

    def get(self, source_id: int) -> Optional[List[Tuple[int, int]]]:
        if source_id not in self._cache:
            return None
        self._cache.move_to_end(source_id)
        return self._cache[source_id]

    def remove(self, source_id: int) -> Optional[List[Tuple[int, int]]]:
        return self._cache.pop(source_id, None)

    def __len__(self) -> int:
        return len(self._cache)

class WebhookRelayManager:
    """Manages channel webhooks, rate limits, SQLite message persistence, and Romanized channel intelligence."""

    def __init__(self, bot: discord.Client, translator: TranslationService, db: DatabaseManager):
        self.bot = bot
        self.translator = translator
        self.db = db
        if getattr(self.translator, "db", None) is None:
            self.translator.db = self.db
        self.normalizer = HinglishNormalizer()
        self.translator.llm_service = self.normalizer
        self.semaphore = asyncio.Semaphore(MAX_CONCURRENT_RELAYS)
        self.message_lru = LRUMessageMap(maxsize=1000)
        self.anti_spam = AntiSpamManager()
        self.webhooks: Dict[int, discord.Webhook] = {}
        # Dynamic channels dictionary: channel_id -> {"lang": str, "is_romanized": bool, "guild_id": int, "group_id": str}
        self.channels: Dict[int, Dict[str, Any]] = {}
        self.safe_mentions = discord.AllowedMentions.none()

    async def sync_channel_cache(self):
        """Loads active channels and their Romanized settings from SQLite into memory."""
        self.channels = await self.db.get_active_channels()

    def add_channel_to_cache(
        self,
        channel_id: int,
        lang: str,
        is_romanized: bool,
        guild_id: int = 0,
        group_id: str = "default"
    ):
        """Immediately updates memory cache when a channel is added via slash command."""
        self.channels[channel_id] = {
            "lang": lang,
            "is_romanized": is_romanized,
            "guild_id": guild_id,
            "group_id": group_id,
        }

    async def _normalize_romanized_cached(
        self,
        shielded_text: str,
        source_lang: str,
        parent_context: Optional[str] = None,
        retry_without_context: bool = False
    ) -> Optional[str]:
        """Normalizes Romanized slang to English with L1/L2 cache lookup when context-free."""
        cache_src = f"{source_lang}_roman"
        if not parent_context:
            cached = await self.translator.lookup_cache(cache_src, "en", shielded_text)
            if not cached and source_lang == "hi":
                cached = await self.translator.lookup_cache("hi", "en", shielded_text)
            if cached:
                return cached

        raw_normalized = await self.normalizer.normalize_hinglish(
            shielded_text,
            parent_context=parent_context
        )
        if not raw_normalized and retry_without_context and parent_context:
            raw_normalized = await self.normalizer.normalize_hinglish(shielded_text)

        if raw_normalized and not parent_context:
            await self.translator._save_translation(cache_src, "en", shielded_text, raw_normalized)
        return raw_normalized

    async def _to_romanized_cached(self, shielded_en: str, target_lang: str = "hi") -> Optional[str]:
        """Converts English to Romanized Hinglish with L1/L2 cache lookup."""
        cache_target = f"{target_lang}_roman"
        cached = await self.translator.lookup_cache("en", cache_target, shielded_en)
        if not cached and target_lang == "hi":
            cached = await self.translator.lookup_cache("en", "hi", shielded_en)
        if cached:
            return cached

        romanized_raw = await self.normalizer.to_romanized_hindi(shielded_en)
        if romanized_raw:
            await self.translator._save_translation("en", cache_target, shielded_en, romanized_raw)
        return romanized_raw

    def remove_channel_from_cache(self, channel_id: int):
        """Removes channel from cache and closes webhook if cached."""
        self.channels.pop(channel_id, None)
        self.webhooks.pop(channel_id, None)

    def should_process_message(self, message: discord.Message) -> bool:
        """Determines if a message is eligible for translation relay."""
        if message.author.bot or message.webhook_id is not None:
            return False

        if not isinstance(message.channel, discord.TextChannel):
            return False

        if message.channel.id not in self.channels:
            return False

        content = message.content.strip()
        # Privacy / Opt-out prefixes: '//' or '/*' allow users to chat locally without cross-channel relay
        if content.startswith("//") or content.startswith("/*"):
            return False

        if content and any(content.startswith(p) for p in COMMAND_PREFIXES):
            return False

        has_forward = hasattr(message, "message_snapshots") and bool(message.message_snapshots)
        if not content and not message.attachments and not has_forward:
            return False

        # Anti-Spam & Meaningless Message Protection
        if content:
            is_spam, reason = self.anti_spam.is_spam_or_meaningless(
                author_id=message.author.id,
                channel_id=message.channel.id,
                text=content
            )
            if is_spam:
                print(f"🛡️ Anti-spam blocked message from user {message.author.id} in channel {message.channel.id} (reason: {reason})")
                return False

        return True

    async def get_or_create_webhook(self, channel: discord.TextChannel) -> discord.Webhook:
        """Retrieves cached webhook or looks for an existing bot-owned webhook to protect quotas."""
        if channel.id in self.webhooks:
            return self.webhooks[channel.id]

        existing = await channel.webhooks()
        for wh in existing:
            if wh.user == self.bot.user or wh.name == "PolyglotRelay":
                self.webhooks[channel.id] = wh
                return wh

        wh = await channel.create_webhook(name="PolyglotRelay")
        self.webhooks[channel.id] = wh
        return wh

    async def _get_reply_context(self, message: discord.Message) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Extracts (author_name, raw_snippet, parent_uuid) if message is a reply."""
        if not message.reference or not message.reference.message_id:
            return None, None, None

        parent_uuid = await self.db.find_conversation_uuid(message.reference.message_id)

        ref_msg = message.reference.resolved
        if not ref_msg or isinstance(ref_msg, discord.DeletedReferencedMessage):
            try:
                ref_msg = await message.channel.fetch_message(message.reference.message_id)
            except Exception:
                ref_msg = None

        if not ref_msg:
            return "a previous message", None, parent_uuid

        author_name = ref_msg.author.display_name
        clean_content = ref_msg.content or ""
        # If the referenced message was already a bot relay with a reply header, strip the header
        if clean_content.startswith("┌ 💬"):
            lines = clean_content.split("\n", 1)
            clean_content = lines[1] if len(lines) > 1 else ""

        snippet = clean_content.replace("\n", " ").strip()
        return author_name, snippet, parent_uuid

    async def _render_target_chunks(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        is_target_romanized: bool = False,
        normalized_english: Optional[str] = None,
        is_source_romanized: bool = False,
        shield_source: bool = False
    ) -> List[str]:
        """Renders translated text chunks for a target channel, preserving syntax shielding."""
        if not text:
            return [""]
        if is_passthrough_text(text):
            return [text]

        base_english = normalized_english
        if base_english is None and shield_source and is_source_romanized and not has_native_script(text):
            shielded_in, in_tokens = shield_syntax(text)
            raw_norm = await self._normalize_romanized_cached(shielded_in, source_lang=source_lang)
            if raw_norm:
                base_english = restore_syntax(raw_norm, in_tokens)

        if target_lang == "hi" and is_target_romanized:
            if not base_english:
                if source_lang == "en":
                    base_english = text
                else:
                    en_chunks = await self.translator.translate(
                        text=text,
                        source_lang=source_lang,
                        target_lang="en"
                    )
                    base_english = en_chunks[0] if en_chunks else text

            shielded_en, en_tokens = shield_syntax(base_english)
            romanized_raw = await self._to_romanized_cached(shielded_en, target_lang="hi")
            if romanized_raw:
                return chunk_message(restore_syntax(romanized_raw, en_tokens))
            return await self.translator.translate(
                text=base_english,
                source_lang="en",
                target_lang="hi"
            )

        if base_english:
            if target_lang == "en":
                return chunk_message(base_english)
            return await self.translator.translate(
                text=base_english,
                source_lang="en",
                target_lang=target_lang
            )

        return await self.translator.translate(
            text=text,
            source_lang=source_lang,
            target_lang=target_lang
        )

    async def _translate_snippet(
        self,
        raw_snippet: str,
        source_lang: str,
        target_lang: str,
        is_target_romanized: bool = False,
        is_source_romanized: bool = False
    ) -> str:
        """Translates a reply snippet into the destination channel's language."""
        if not raw_snippet:
            return ""

        chunks = await self._render_target_chunks(
            text=raw_snippet,
            source_lang=source_lang,
            target_lang=target_lang,
            is_target_romanized=is_target_romanized,
            is_source_romanized=is_source_romanized,
            shield_source=True
        )
        translated = chunks[0] if chunks else raw_snippet
        if len(translated) > 60:
            translated = translated[:57] + "..."
        return translated

    async def _build_reply_header(
        self,
        author_name: Optional[str],
        raw_snippet: Optional[str],
        source_lang: str,
        target_lang: str,
        is_target_romanized: bool = False,
        is_source_romanized: bool = False
    ) -> str:
        """Constructs the localized reply header for a destination channel."""
        if not author_name:
            return ""
        if not raw_snippet:
            return f"┌ 💬 Replying to **@{author_name}**\n"

        try:
            translated_snippet = await self._translate_snippet(
                raw_snippet=raw_snippet,
                source_lang=source_lang,
                target_lang=target_lang,
                is_target_romanized=is_target_romanized,
                is_source_romanized=is_source_romanized
            )
            return f"┌ 💬 Replying to **@{author_name}**: \"{translated_snippet}\"\n"
        except Exception as e:
            print(f"Error translating reply snippet: {e}")
            snippet = raw_snippet[:57] + "..." if len(raw_snippet) > 60 else raw_snippet
            return f"┌ 💬 Replying to **@{author_name}**: \"{snippet}\"\n"

    async def relay_message(self, message: discord.Message):
        """Translates and fans out a message with Romanized AI normalizer support."""
        if not self.should_process_message(message):
            return

        channel_info = self.channels[message.channel.id]
        source_lang = channel_info["lang"]
        is_romanized_channel = channel_info.get("is_romanized", False)

        conv_uuid = str(uuid.uuid4())
        reply_author, raw_snippet, parent_uuid = await self._get_reply_context(message)

        attachment_text = ""
        if message.attachments:
            urls = [att.url for att in message.attachments]
            attachment_text = "\n" + "\n".join(urls)

        text_to_translate = message.content.strip()
        # If user forwarded a message via Discord's Forward feature, extract forwarded text
        if hasattr(message, "message_snapshots") and message.message_snapshots:
            forwarded_texts = [
                s.content for s in message.message_snapshots if getattr(s, "content", None)
            ]
            if forwarded_texts:
                forwarded_combined = "\n".join(forwarded_texts)
                if text_to_translate:
                    text_to_translate = f"{text_to_translate}\n*(Forwarded)* {forwarded_combined}"
                else:
                    text_to_translate = f"*(Forwarded)* {forwarded_combined}"

        normalized_english = None

        # Check Romanized Flag or Heuristic Gatekeeper (only on English/Hindi channels to avoid false positives)
        should_use_ai = is_romanized_channel or (
            source_lang in ("en", "hi") and is_potential_hinglish(text_to_translate, source_lang)
        )
        if is_passthrough_text(text_to_translate):
            should_use_ai = False
        elif has_native_script(text_to_translate):
            # Native non-Latin script in a Romanized channel (Devanagari, Arabic, Cyrillic, etc.)
            # Zero-token direct bypass straight to Azure AI Translator!
            should_use_ai = False
            self.normalizer.stats["native_script_bypasses"] = self.normalizer.stats.get("native_script_bypasses", 0) + 1
        elif is_romanized_channel and is_already_english(text_to_translate):
            # Already English in a Romanized channel: zero-token direct bypass!
            should_use_ai = False
            normalized_english = text_to_translate
        if text_to_translate and should_use_ai:
            self.normalizer.stats["slang_detections"] = self.normalizer.stats.get("slang_detections", 0) + 1
            self.normalizer.stats["hinglish_detections"] = self.normalizer.stats.get("hinglish_detections", 0) + 1
            parent_context = None
            if message.reference and message.reference.resolved:
                parent_context = getattr(message.reference.resolved, "content", None)

            # Shield mentions, emojis, game brands, and code tokens so AI doesn't mangle user IDs
            shielded_input, in_tokens = shield_syntax(text_to_translate)
            raw_normalized = await self._normalize_romanized_cached(
                shielded_input,
                source_lang=source_lang,
                parent_context=parent_context,
                retry_without_context=is_romanized_channel
            )

            if raw_normalized:
                normalized_english = restore_syntax(raw_normalized, in_tokens)

        relayed_entries: List[Tuple[int, int]] = []

        async def deliver_to_channel(dest_id: int, dest_info: Dict[str, Any]):
            dest_channel = self.bot.get_channel(dest_id)
            if not isinstance(dest_channel, discord.TextChannel):
                return

            # Guild Isolation: Only relay within the same Discord server
            if message.guild and dest_channel.guild.id != message.guild.id:
                return

            target_lang = dest_info["lang"]

            async def compute_chunks() -> List[str]:
                return await self._render_target_chunks(
                    text=text_to_translate,
                    source_lang=source_lang,
                    target_lang=target_lang,
                    is_target_romanized=dest_info.get("is_romanized", False),
                    normalized_english=normalized_english
                )

            async def compute_reply_header() -> str:
                if not reply_author:
                    return ""
                return await self._build_reply_header(
                    author_name=reply_author,
                    raw_snippet=raw_snippet,
                    source_lang=source_lang,
                    target_lang=target_lang,
                    is_target_romanized=dest_info.get("is_romanized", False),
                    is_source_romanized=is_romanized_channel
                )

            # Parallelize main text translation and reply snippet translation
            chunks, reply_header = await asyncio.gather(compute_chunks(), compute_reply_header())

            full_content = (reply_header + "\n".join(chunks)) if chunks else reply_header
            if attachment_text:
                full_content = (full_content + attachment_text) if full_content else attachment_text.strip()
            chunks = chunk_message(full_content) if full_content else []

            if hasattr(message.author.display_avatar, "with_size"):
                author_avatar = message.author.display_avatar.with_size(64).url
            else:
                author_avatar = message.author.display_avatar.url

            async with self.semaphore:
                try:
                    wh = await self.get_or_create_webhook(dest_channel)
                except Exception as e:
                    print(f"Error obtaining webhook for #{dest_channel.name}: {e}")
                    return

                for chunk in chunks:
                    if not chunk.strip():
                        continue
                    try:
                        sent_msg = await wh.send(
                            content=chunk,
                            username=message.author.display_name,
                            avatar_url=author_avatar,
                            allowed_mentions=self.safe_mentions,
                            wait=True
                        )
                        relayed_entries.append((dest_channel.id, sent_msg.id))
                    except Exception as e:
                        print(f"Error relaying to #{dest_channel.name}: {e}")

        # Fan-out only to destination channels in the SAME server AND translation group
        src_group = channel_info.get("group_id", "default")
        src_guild = channel_info.get("guild_id") or (message.guild.id if message.guild else 0)
        delivery_tasks = [
            deliver_to_channel(dest_id, dest_info)
            for dest_id, dest_info in self.channels.items()
            if dest_id != message.channel.id
            and dest_info.get("group_id", "default") == src_group
            and (not src_guild or not dest_info.get("guild_id") or dest_info.get("guild_id") == src_guild)
        ]
        if delivery_tasks:
            await asyncio.gather(*delivery_tasks)

        if relayed_entries:
            self.message_lru.put(message.id, relayed_entries)
            await self.db.record_relayed_messages(
                conversation_uuid=conv_uuid,
                source_channel_id=message.channel.id,
                source_message_id=message.id,
                relays=relayed_entries,
                parent_uuid=parent_uuid
            )

    async def handle_message_edit(self, before: discord.Message, after: discord.Message):
        """Synchronizes message edits to relayed webhook messages via SQLite records."""
        if before.content == after.content:
            return
        if not self.should_process_message(after):
            return

        relayed_entries = self.message_lru.get(before.id) or await self.db.get_relayed_entries_by_source_id(before.id)
        if not relayed_entries:
            return

        channel_info = self.channels[after.channel.id]
        source_lang = channel_info["lang"]
        is_source_romanized = channel_info.get("is_romanized", False)
        updated_text = after.content.strip()
        if not updated_text:
            return

        # Check if edited text in a Romanized channel requires AI slang interpretation
        normalized_english = None
        if is_source_romanized and not has_native_script(updated_text):
            shielded_input, in_tokens = shield_syntax(updated_text)
            raw_normalized = await self._normalize_romanized_cached(shielded_input, source_lang=source_lang)
            if raw_normalized:
                normalized_english = restore_syntax(raw_normalized, in_tokens)

        reply_author, raw_snippet, _ = await self._get_reply_context(after)

        async def edit_single_channel(dest_channel_id: int, webhook_msg_id: int):
            dest_info = self.channels.get(dest_channel_id)
            if not dest_info:
                return

            dest_channel = self.bot.get_channel(dest_channel_id)
            if not isinstance(dest_channel, discord.TextChannel):
                return

            # Guild Isolation: Only relay within the same Discord server
            if after.guild and dest_channel.guild.id != after.guild.id:
                return

            target_lang = dest_info["lang"]
            is_target_romanized = dest_info.get("is_romanized", False)

            chunks = await self._render_target_chunks(
                text=updated_text,
                source_lang=source_lang,
                target_lang=target_lang,
                is_target_romanized=is_target_romanized,
                normalized_english=normalized_english
            )
            if not chunks:
                return

            reply_header = ""
            if reply_author:
                reply_header = await self._build_reply_header(
                    author_name=reply_author,
                    raw_snippet=raw_snippet,
                    source_lang=source_lang,
                    target_lang=target_lang,
                    is_target_romanized=is_target_romanized,
                    is_source_romanized=channel_info.get("is_romanized", False)
                )

            full_edit = (reply_header + "\n".join(chunks)) if reply_header else "\n".join(chunks)
            content_to_send = chunk_message(full_edit)[0]

            async with self.semaphore:
                try:
                    wh = await self.get_or_create_webhook(dest_channel)
                    await wh.edit_message(webhook_msg_id, content=content_to_send, allowed_mentions=self.safe_mentions)
                except Exception as e:
                    print(f"Error updating edited message in #{dest_channel.name}: {e}")

        # Parallelize edit updates across all destination channels
        edit_tasks = [
            edit_single_channel(dest_channel_id, webhook_msg_id)
            for dest_channel_id, webhook_msg_id in relayed_entries
        ]
        if edit_tasks:
            await asyncio.gather(*edit_tasks)

    async def handle_message_delete(self, message: discord.Message):
        """Synchronizes message deletions to relayed webhook messages via SQLite records."""
        self.message_lru.remove(message.id)
        relayed_entries = await self.db.delete_entries_by_source_id(message.id)
        if not relayed_entries:
            return

        async def delete_single_channel(dest_channel_id: int, webhook_msg_id: int):
            dest_channel = self.bot.get_channel(dest_channel_id)
            if not isinstance(dest_channel, discord.TextChannel):
                return

            # Guild Isolation: Only relay within the same Discord server
            if message.guild and dest_channel.guild.id != message.guild.id:
                return

            async with self.semaphore:
                try:
                    wh = await self.get_or_create_webhook(dest_channel)
                    await wh.delete_message(webhook_msg_id)
                except Exception as e:
                    print(f"Error deleting relayed message in #{dest_channel.name}: {e}")

        delete_tasks = [
            delete_single_channel(dest_channel_id, webhook_msg_id)
            for dest_channel_id, webhook_msg_id in relayed_entries
        ]
        if delete_tasks:
            await asyncio.gather(*delete_tasks)
