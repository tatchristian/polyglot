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
                PRIMARY KEY (conversation_uuid, dest_channel_id)
            );
        """)

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
