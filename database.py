"""Asynchronous SQLite storage engine for message mapping, groups, dynamic channel config, and Romanized flags."""

import uuid
from typing import Dict, List, Tuple, Optional, Any
import aiosqlite

DB_FILE = "polyglot.db"

class DatabaseManager:
    """Manages SQLite connection, WAL mode, dynamic channel management, and sync mapping queries."""

    def __init__(self, db_path: str = DB_FILE):
        self.db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None

    async def connect(self):
        """Initializes connection and configures Write-Ahead Logging (WAL) for high concurrency."""
        self._conn = await aiosqlite.connect(self.db_path)
        await self._conn.execute("PRAGMA journal_mode=WAL;")
        await self._conn.execute("PRAGMA synchronous=NORMAL;")
        await self._create_tables()

    async def close(self):
        """Closes database connection gracefully."""
        if self._conn:
            await self._conn.close()

    async def _create_tables(self):
        """Creates tables, adds missing columns safely, and builds indexes."""
        assert self._conn is not None

        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS translation_groups (
                group_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS translation_cache (
                source_lang TEXT NOT NULL,
                target_lang TEXT NOT NULL,
                source_text TEXT NOT NULL,
                translated_text TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (source_lang, target_lang, source_text)
            );
        """)

        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS group_channels (
                channel_id INTEGER PRIMARY KEY,
                group_id TEXT NOT NULL,
                language_code TEXT NOT NULL,
                is_romanized INTEGER DEFAULT 0,
                FOREIGN KEY(group_id) REFERENCES translation_groups(group_id)
            );
        """)

        # Migration check: Ensure is_romanized exists if table was created previously
        try:
            await self._conn.execute("ALTER TABLE group_channels ADD COLUMN is_romanized INTEGER DEFAULT 0;")
        except Exception:
            pass  # Column already exists

        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS message_sync (
                conversation_uuid TEXT NOT NULL,
                source_channel_id INTEGER NOT NULL,
                source_message_id INTEGER NOT NULL,
                dest_channel_id INTEGER NOT NULL,
                relayed_message_id INTEGER NOT NULL,
                parent_uuid TEXT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (conversation_uuid, dest_channel_id, relayed_message_id)
            );
        """)

        # Migration check: Upgrade message_sync to include relayed_message_id in primary key
        try:
            async with self._conn.execute("PRAGMA table_info(message_sync);") as cur:
                columns = await cur.fetchall()
                relayed_pk = any(col[1] == "relayed_message_id" and col[5] > 0 for col in columns)
                if columns and not relayed_pk:
                    await self._conn.execute("""
                        CREATE TABLE message_sync_v2 (
                            conversation_uuid TEXT NOT NULL,
                            source_channel_id INTEGER NOT NULL,
                            source_message_id INTEGER NOT NULL,
                            dest_channel_id INTEGER NOT NULL,
                            relayed_message_id INTEGER NOT NULL,
                            parent_uuid TEXT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            PRIMARY KEY (conversation_uuid, dest_channel_id, relayed_message_id)
                        );
                    """)
                    await self._conn.execute("INSERT OR IGNORE INTO message_sync_v2 SELECT * FROM message_sync;")
                    await self._conn.execute("DROP TABLE message_sync;")
                    await self._conn.execute("ALTER TABLE message_sync_v2 RENAME TO message_sync;")
        except Exception as e:
            print(f"message_sync migration notice: {e}")

        await self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_source_msg ON message_sync(source_message_id);
        """)
        await self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_relayed_msg ON message_sync(relayed_message_id);
        """)
        await self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_conv_uuid ON message_sync(conversation_uuid);
        """)
        await self._conn.commit()

    async def seed_default_channels(self, channels: Dict[int, str]):
        """Seeds default channels if tables are empty."""
        assert self._conn is not None
        if not channels:
            return

        async with self._conn.execute("SELECT COUNT(*) FROM translation_groups;") as cursor:
            row = await cursor.fetchone()
            if row and row[0] == 0:
                await self._conn.execute(
                    "INSERT INTO translation_groups (group_id, name) VALUES (?, ?);",
                    ("default", "Primary General Channels")
                )

        for channel_id, lang in channels.items():
            await self._conn.execute("""
                INSERT OR IGNORE INTO group_channels (channel_id, group_id, language_code, is_romanized)
                VALUES (?, ?, ?, 0);
            """, (channel_id, "default", lang))

        await self._conn.commit()

    async def add_channel(self, channel_id: int, language_code: str, is_romanized: bool = False, group_id: str = "default"):
        """Adds or updates a channel mapping dynamically."""
        assert self._conn is not None
        # Ensure default group exists
        await self._conn.execute(
            "INSERT OR IGNORE INTO translation_groups (group_id, name) VALUES (?, ?);",
            (group_id, "Primary General Channels")
        )
        await self._conn.execute("""
            INSERT OR REPLACE INTO group_channels (channel_id, group_id, language_code, is_romanized)
            VALUES (?, ?, ?, ?);
        """, (channel_id, group_id, language_code.lower(), 1 if is_romanized else 0))
        await self._conn.commit()

    async def remove_channel(self, channel_id: int) -> bool:
        """Removes a channel mapping dynamically."""
        assert self._conn is not None
        async with self._conn.execute("DELETE FROM group_channels WHERE channel_id = ?;", (channel_id,)) as cursor:
            await self._conn.commit()
            return cursor.rowcount > 0

    async def get_active_channels(self) -> Dict[int, Dict[str, Any]]:
        """Returns all configured channel IDs, their language codes, and romanized flags."""
        assert self._conn is not None
        async with self._conn.execute("SELECT channel_id, language_code, is_romanized FROM group_channels;") as cursor:
            rows = await cursor.fetchall()
            return {
                row[0]: {
                    "lang": row[1],
                    "is_romanized": bool(row[2])
                }
                for row in rows
            }

    async def record_relayed_messages(
        self,
        conversation_uuid: str,
        source_channel_id: int,
        source_message_id: int,
        relays: List[Tuple[int, int]],
        parent_uuid: Optional[str] = None
    ):
        """Records mapping between source message and all destination copies."""
        assert self._conn is not None
        for dest_id, relayed_id in relays:
            await self._conn.execute("""
                INSERT OR REPLACE INTO message_sync 
                (conversation_uuid, source_channel_id, source_message_id, dest_channel_id, relayed_message_id, parent_uuid)
                VALUES (?, ?, ?, ?, ?, ?);
            """, (conversation_uuid, source_channel_id, source_message_id, dest_id, relayed_id, parent_uuid))
        await self._conn.commit()

    async def get_relayed_entries_by_source_id(self, source_message_id: int) -> List[Tuple[int, int]]:
        """Returns list of (dest_channel_id, relayed_message_id) for a source message."""
        assert self._conn is not None
        async with self._conn.execute(
            "SELECT dest_channel_id, relayed_message_id FROM message_sync WHERE source_message_id = ?;",
            (source_message_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [(row[0], row[1]) for row in rows]

    async def delete_entries_by_source_id(self, source_message_id: int) -> List[Tuple[int, int]]:
        """Removes entries for a source message and returns them for webhook deletion."""
        assert self._conn is not None
        entries = await self.get_relayed_entries_by_source_id(source_message_id)
        if entries:
            await self._conn.execute(
                "DELETE FROM message_sync WHERE source_message_id = ?;",
                (source_message_id,)
            )
            await self._conn.commit()
        return entries

    async def find_conversation_uuid(self, message_id: int) -> Optional[str]:
        """Looks up the conversation UUID for either a source message or a relayed copy."""
        assert self._conn is not None
        async with self._conn.execute("""
            SELECT conversation_uuid FROM message_sync 
            WHERE source_message_id = ? OR relayed_message_id = ? 
            LIMIT 1;
        """, (message_id, message_id)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

    async def get_stats(self) -> Dict[str, int]:
        """Returns statistics for observability and monitoring dashboard."""
        assert self._conn is not None
        async with self._conn.execute("SELECT COUNT(DISTINCT conversation_uuid) FROM message_sync;") as c1:
            total_conversations = (await c1.fetchone())[0]

        async with self._conn.execute("SELECT COUNT(*) FROM group_channels;") as c2:
            total_channels = (await c2.fetchone())[0]

        return {
            "total_synced_messages": total_conversations,
            "configured_channels": total_channels,
        }

    async def get_cached_translation(
        self,
        source_lang: str,
        target_lang: str,
        text: str
    ) -> Optional[str]:
        """Retrieves a cached translation from L2 SQLite cache."""
        if not self._conn:
            return None
        clean_text = text.strip().lower()
        async with self._conn.execute("""
            SELECT translated_text FROM translation_cache
            WHERE source_lang = ? AND target_lang = ? AND source_text = ?;
        """, (source_lang.lower(), target_lang.lower(), clean_text)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

    async def set_cached_translation(
        self,
        source_lang: str,
        target_lang: str,
        text: str,
        translated: str
    ):
        """Stores a translation in L2 SQLite cache."""
        if not self._conn:
            return
        if not translated or not text or "*(All providers exhausted" in translated or "*(Translation runtime error" in translated:
            return
        clean_text = text.strip().lower()
        await self._conn.execute("""
            INSERT OR REPLACE INTO translation_cache
            (source_lang, target_lang, source_text, translated_text)
            VALUES (?, ?, ?, ?);
        """, (source_lang.lower(), target_lang.lower(), clean_text, translated))
        await self._conn.commit()

    async def get_source_message_info(self, message_id: int) -> Optional[Tuple[int, int]]:
        """Returns (source_channel_id, source_message_id) for any message ID (source or relayed)."""
        if not self._conn:
            return None
        async with self._conn.execute("""
            SELECT source_channel_id, source_message_id FROM message_sync
            WHERE source_message_id = ? OR relayed_message_id = ?
            LIMIT 1;
        """, (message_id, message_id)) as cursor:
            row = await cursor.fetchone()
            return (row[0], row[1]) if row else None

    async def prune_old_sync_records(self, days: int = 60) -> int:
        """Deletes sync records older than given number of days and prunes old translation cache to keep database lean."""
        if not self._conn:
            return 0
        async with self._conn.execute("""
            DELETE FROM message_sync 
            WHERE created_at < datetime('now', '-' || ? || ' days');
        """, (days,)) as cursor:
            sync_deleted = cursor.rowcount

        # Also clean up translation cache entries older than 90 days to prevent unbounded DB growth
        await self._conn.execute("""
            DELETE FROM translation_cache
            WHERE created_at < datetime('now', '-90 days');
        """)
        await self._conn.commit()
        return sync_deleted

    async def seed_common_translations(self):
        """Pre-seeds L2 cache with high-frequency verified Discord chat and gaming phrases."""
        if not self._conn:
            return

        common_pairs = [
            # Hinglish (hi) -> English (en)
            ("hi", "en", "kya scene hai", "What's the plan?"),
            ("hi", "en", "kya scene hai?", "What's the plan?"),
            ("hi", "en", "kya haal hai", "How are you doing?"),
            ("hi", "en", "kya haal hai?", "How are you doing?"),
            ("hi", "en", "aaja vc", "Hop in VC"),
            ("hi", "en", "ruk 2 min", "Wait 2 mins"),
            ("hi", "en", "theek hai", "Alright"),
            ("hi", "en", "thik hai", "Alright"),
            ("hi", "en", "kuch nahi", "Nothing much"),
            ("hi", "en", "haan bhai", "Yeah bro"),
            ("hi", "en", "sahi hai", "Sounds good"),
            ("hi", "en", "badhiya", "Awesome"),
            ("hi", "en", "khelna hai kya", "Anyone down to play?"),
            ("hi", "en", "khelna hai kya?", "Anyone down to play?"),
            ("hi", "en", "shuru ho gaya fir se", "Here we go again"),
            ("hi", "en", "dekhne me galat lagta hai", "It looks wrong"),
            ("hi", "en", "lagta hai bug hai", "Looks like there's a bug"),
            ("hi", "en", "kal milte hai", "See you tomorrow"),
            ("hi", "en", "shukriya bhai", "Thanks bro"),
            ("hi", "en", "alvida", "Goodbye"),
            ("hi", "en", "samajh gaya", "Got it"),

            # English (en) -> Hinglish (hi)
            ("en", "hi", "what's the plan?", "kya scene hai?"),
            ("en", "hi", "how are you?", "kya haal hai?"),
            ("en", "hi", "let's play", "chalo khelte hai"),
            ("en", "hi", "hop in vc", "aaja vc"),
            ("en", "hi", "wait 2 mins", "ruk 2 min"),
            ("en", "hi", "sounds good", "sahi hai"),
            ("en", "hi", "good night", "good night / shubh ratri"),
            ("en", "hi", "thank you", "shukriya / thanks"),
            ("en", "hi", "see you tomorrow", "kal milte hai"),
            ("en", "hi", "got it", "samajh gaya"),

            # Spanish (es) -> English (en)
            ("es", "en", "hola", "hello"),
            ("es", "en", "que tal", "what's up"),
            ("es", "en", "¿que tal?", "what's up?"),
            ("es", "en", "como estas", "how are you"),
            ("es", "en", "¿como estas?", "how are you?"),
            ("es", "en", "vamos a jugar", "let's play"),
            ("es", "en", "buenas noches", "good night"),
            ("es", "en", "buenos dias", "good morning"),
            ("es", "en", "muchas gracias", "thank you very much"),
            ("es", "en", "de nada", "you're welcome"),
            ("es", "en", "hasta mañana", "see you tomorrow"),
            ("es", "en", "esta bien", "alright"),

            # Japanese (ja) -> English (en)
            ("ja", "en", "こんにちは", "hello"),
            ("ja", "en", "こんばんは", "good evening"),
            ("ja", "en", "おはよう", "good morning"),
            ("ja", "en", "お疲れ様", "good work / thanks"),
            ("ja", "en", "ゲームしよう", "let's play a game"),
            ("ja", "en", "ありがとう", "thank you"),
            ("ja", "en", "また明日", "see you tomorrow"),
        ]

        await self._conn.executemany("""
            INSERT OR IGNORE INTO translation_cache 
            (source_lang, target_lang, source_text, translated_text)
            VALUES (?, ?, ?, ?);
        """, [(s.lower(), t.lower(), src.strip().lower(), trans) for s, t, src, trans in common_pairs])
        await self._conn.commit()
