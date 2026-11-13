import pytest
from database import DatabaseManager

@pytest.mark.asyncio
async def test_db_init_and_seeding():
    db = DatabaseManager(db_path=":memory:")
    await db.connect()

    channels = {101: "en", 102: "es"}
    await db.seed_default_channels(channels)

    active = await db.get_active_channels()
    assert 101 in active
    assert active[101]["lang"] == "en"
    assert active[101]["is_romanized"] is False

    stats = await db.get_stats()
    assert stats["configured_channels"] == 2
    assert stats["total_synced_messages"] == 0

    await db.close()

@pytest.mark.asyncio
async def test_add_and_remove_channel_with_romanized():
    db = DatabaseManager(db_path=":memory:")
    await db.connect()

    # Add Hindi with Romanized flag = True
    await db.add_channel(channel_id=555, language_code="hi", is_romanized=True)

    active = await db.get_active_channels()
    assert 555 in active
    assert active[555]["lang"] == "hi"
    assert active[555]["is_romanized"] is True

    # Remove channel
    removed = await db.remove_channel(555)
    assert removed is True

    active_after = await db.get_active_channels()
    assert 555 not in active_after

    await db.close()

@pytest.mark.asyncio
async def test_record_and_retrieve_relayed_messages():
    db = DatabaseManager(db_path=":memory:")
    await db.connect()

    conv_uuid = "conv-abc-123"
    source_channel = 101
    source_msg = 9001
    relays = [(102, 9002), (103, 9003)]

    await db.record_relayed_messages(
        conversation_uuid=conv_uuid,
        source_channel_id=source_channel,
        source_message_id=source_msg,
        relays=relays
    )

    retrieved = await db.get_relayed_entries_by_source_id(source_msg)
    assert len(retrieved) == 2
    assert (102, 9002) in retrieved
    assert (103, 9003) in retrieved

    found_from_source = await db.find_conversation_uuid(source_msg)
    found_from_relay = await db.find_conversation_uuid(9002)
    assert found_from_source == conv_uuid
    assert found_from_relay == conv_uuid

    stats = await db.get_stats()
    assert stats["total_synced_messages"] == 1

    await db.close()

@pytest.mark.asyncio
async def test_delete_relayed_messages():
    db = DatabaseManager(db_path=":memory:")
    await db.connect()

    conv_uuid = "conv-del-456"
    await db.record_relayed_messages(
        conversation_uuid=conv_uuid,
        source_channel_id=101,
        source_message_id=5000,
        relays=[(102, 5001)]
    )

    deleted = await db.delete_entries_by_source_id(5000)
    assert deleted == [(102, 5001)]

    remaining = await db.get_relayed_entries_by_source_id(5000)
    assert remaining == []

    await db.close()

@pytest.mark.asyncio
async def test_get_source_message_info():
    db = DatabaseManager(db_path=":memory:")
    await db.connect()

    conv_uuid = "conv-src-info"
    await db.record_relayed_messages(
        conversation_uuid=conv_uuid,
        source_channel_id=111,
        source_message_id=222,
        relays=[(333, 444)]
    )

    # Lookup via source ID
    info_from_src = await db.get_source_message_info(222)
    assert info_from_src == (111, 222)

    # Lookup via relayed ID
    info_from_relay = await db.get_source_message_info(444)
    assert info_from_relay == (111, 222)

    # Lookup non-existent
    assert await db.get_source_message_info(999999) is None

    await db.close()

@pytest.mark.asyncio
async def test_prune_old_sync_records():
    db = DatabaseManager(db_path=":memory:")
    await db.connect()

    # Insert a simulated old record (e.g. 70 days ago) and a recent record
    await db._conn.execute("""
        INSERT INTO message_sync (conversation_uuid, source_channel_id, source_message_id, dest_channel_id, relayed_message_id, created_at)
        VALUES ('old-conv', 101, 1001, 102, 1002, datetime('now', '-70 days'));
    """)
    await db._conn.execute("""
        INSERT INTO message_sync (conversation_uuid, source_channel_id, source_message_id, dest_channel_id, relayed_message_id, created_at)
        VALUES ('new-conv', 101, 2001, 102, 2002, datetime('now', '-10 days'));
    """)
    await db._conn.commit()

    # Prune records older than 60 days
    pruned_count = await db.prune_old_sync_records(days=60)
    assert pruned_count == 1

    # Only new-conv should remain
    assert await db.find_conversation_uuid(1001) is None
    assert await db.find_conversation_uuid(2001) == "new-conv"

    await db.close()

@pytest.mark.asyncio
async def test_seed_common_translations():
    db = DatabaseManager(db_path=":memory:")
    await db.connect()

    # Pre-seed common translations
    await db.seed_common_translations()

    # Check Hinglish phrase lookup
    hi_tr = await db.get_cached_translation("hi", "en", "kya scene hai")
    assert hi_tr == "What's the plan?"

    # Check Spanish phrase lookup
    es_tr = await db.get_cached_translation("es", "en", "como estas")
    assert es_tr == "how are you"

    # Check Japanese phrase lookup
    ja_tr = await db.get_cached_translation("ja", "en", "こんにちは")
    assert ja_tr == "hello"

    await db.close()
