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
from translator import TranslationService, shield_syntax, restore_syntax, is_passthrough_text
from database import DatabaseManager
from hinglish_gatekeeper import is_potential_hinglish, is_already_english
from hinglish_normalizer import HinglishNormalizer
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
        # Dynamic channels dictionary: channel_id -> {"lang": str, "is_romanized": bool}
        self.channels: Dict[int, Dict[str, Any]] = {}
        self.safe_mentions = discord.AllowedMentions.none()

    async def sync_channel_cache(self):
        """Loads active channels and their Romanized settings from SQLite into memory."""
        self.channels = await self.db.get_active_channels()

    def add_channel_to_cache(self, channel_id: int, lang: str, is_romanized: bool):
        """Immediately updates memory cache when a channel is added via slash command."""
        self.channels[channel_id] = {
            "lang": lang,
            "is_romanized": is_romanized
        }

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

        # Normalize source to base English
        base_en = None
        if source_lang == "hi" and is_source_romanized:
            base_en = await self.normalizer.normalize_hinglish(raw_snippet)

        if not base_en:
            if source_lang == "en":
                base_en = raw_snippet
            else:
                en_chunks = await self.translator.translate(
                    text=raw_snippet,
                    source_lang=source_lang,
                    target_lang="en"
                )
                base_en = en_chunks[0] if en_chunks else raw_snippet

        # Render into target language
        if target_lang == "en":
            translated = base_en
        elif target_lang == "hi" and is_target_romanized:
            roman_raw = await self.normalizer.to_romanized_hindi(base_en)
            translated = roman_raw if roman_raw else base_en
        else:
            chunks = await self.translator.translate(
                text=base_en,
                source_lang="en",
                target_lang=target_lang
            )
            translated = chunks[0] if chunks else base_en

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

        # Check Romanized Flag or Heuristic Gatekeeper
        should_use_ai = is_romanized_channel or is_potential_hinglish(text_to_translate, source_lang)
        if is_passthrough_text(text_to_translate):
            should_use_ai = False
        elif is_romanized_channel and is_already_english(text_to_translate):
            # Already English in a Romanized channel: zero-token direct bypass!
            should_use_ai = False
            normalized_english = text_to_translate
        if text_to_translate and should_use_ai:
            self.normalizer.stats["hinglish_detections"] += 1
            parent_context = None
            if message.reference and message.reference.resolved:
                parent_context = getattr(message.reference.resolved, "content", None)

            # Shield mentions, emojis, and code tokens so AI doesn't mangle user IDs
            shielded_input, in_tokens = shield_syntax(text_to_translate)
            raw_normalized = await self.normalizer.normalize_hinglish(
                shielded_input,
                parent_context=parent_context
            )
            if not raw_normalized and is_romanized_channel:
                # Retry once without parent context if first attempt timed out
                raw_normalized = await self.normalizer.normalize_hinglish(shielded_input)

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
                if not text_to_translate:
                    return [""]
                if is_passthrough_text(text_to_translate):
                    return [text_to_translate]
                # If target channel is configured as Romanized Hindi, deliver conversational Hinglish
                if target_lang == "hi" and dest_info.get("is_romanized", False):
                    base_english = normalized_english
                    if not base_english:
                        en_chunks = await self.translator.translate(
                            text=text_to_translate,
                            source_lang=source_lang,
                            target_lang="en"
                        )
                        base_english = en_chunks[0] if en_chunks else text_to_translate

                    shielded_en, en_tokens = shield_syntax(base_english)
                    romanized_raw = await self.normalizer.to_romanized_hindi(shielded_en)
                    if romanized_raw:
                        return [restore_syntax(romanized_raw, en_tokens)]
                    else:
                        return await self.translator.translate(
                            text=base_english,
                            source_lang="en",
                            target_lang="hi"
                        )
                elif normalized_english:
                    if target_lang == "en":
                        return [normalized_english]
                    else:
                        return await self.translator.translate(
                            text=normalized_english,
                            source_lang="en",
                            target_lang=target_lang
                        )
                else:
                    return await self.translator.translate(
                        text=text_to_translate,
                        source_lang=source_lang,
                        target_lang=target_lang
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

            if reply_header and chunks:
                chunks[0] = reply_header + chunks[0]

            if attachment_text:
                if chunks:
                    chunks[-1] += attachment_text
                else:
                    chunks = [attachment_text.strip()]

            wh = await self.get_or_create_webhook(dest_channel)
            if hasattr(message.author.display_avatar, "with_size"):
                author_avatar = message.author.display_avatar.with_size(64).url
            else:
                author_avatar = message.author.display_avatar.url

            async with self.semaphore:
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

        # Fan-out to all destination channels simultaneously in parallel
        delivery_tasks = [
            deliver_to_channel(dest_id, dest_info)
            for dest_id, dest_info in self.channels.items()
            if dest_id != message.channel.id
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

        # Check if edited text in a Romanized channel is Hinglish requiring AI interpretation
        normalized_english = None
        if source_lang == "hi" and is_source_romanized:
            shielded_input, in_tokens = shield_syntax(updated_text)
            raw_normalized = await self.normalizer.normalize_hinglish(shielded_input)
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

            if target_lang == "hi" and is_target_romanized:
                base_en = normalized_english
                if not base_en:
                    en_chunks = await self.translator.translate(
                        text=updated_text,
                        source_lang=source_lang,
                        target_lang="en"
                    )
                    base_en = en_chunks[0] if en_chunks else updated_text
                shielded_en, en_tokens = shield_syntax(base_en)
                romanized = await self.normalizer.to_romanized_hindi(shielded_en)
                chunks = [restore_syntax(romanized, en_tokens)] if romanized else [base_en]
            elif normalized_english:
                if target_lang == "en":
                    chunks = [normalized_english]
                else:
                    chunks = await self.translator.translate(
                        text=normalized_english,
                        source_lang="en",
                        target_lang=target_lang
                    )
            else:
                chunks = await self.translator.translate(
                    text=updated_text,
                    source_lang=source_lang,
                    target_lang=target_lang
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

            content_to_send = (reply_header + chunks[0]) if reply_header else chunks[0]

            wh = await self.get_or_create_webhook(dest_channel)
            async with self.semaphore:
                try:
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

            wh = await self.get_or_create_webhook(dest_channel)
            async with self.semaphore:
                try:
                    await wh.delete_message(webhook_msg_id)
                except Exception as e:
                    print(f"Error deleting relayed message in #{dest_channel.name}: {e}")

        delete_tasks = [
            delete_single_channel(dest_channel_id, webhook_msg_id)
            for dest_channel_id, webhook_msg_id in relayed_entries
        ]
        if delete_tasks:
            await asyncio.gather(*delete_tasks)
