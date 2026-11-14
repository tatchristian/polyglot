# 🗺️ Polyglot Discord Bot — Architecture & Codebase Map

> **Agent Instruction:** Read this document first before exploring the codebase. It maps all file ownership, system data flows, database schemas, quotas, and invariants to minimize search tokens.

---

## 1. High-Level System Topology & Message Lifecycle

```
[ Discord User Message ]
          │
          ▼
    `bot.py` (on_message gateway listener)
          │
          ▼
   `relay.py` (WebhookRelayManager.relay_message)
          ├─► Safety checks: ignore bots, webhooks, non-text, commands
          ├─► Passthrough check: `is_passthrough_text()` (URLs, emojis, gaming slang)
          ├─► Hinglish check: `is_potential_hinglish()` or `is_romanized` channel
          │        └─► AI Normalizer (`hinglish_normalizer.py` via Groq / OpenRouter :free)
          │
          ▼
 `translator.py` (TranslationService.translate)
          ├─► Step 1: Passthrough filter (returns unshielded raw text)
          ├─► Step 2: L1 In-Memory LRU Cache lookup
          ├─► Step 3: L2 SQLite Cache (`translation_cache` in `database.py`)
          ├─► Step 4: Strict Priority Cascade (Azure ➔ DeepL ➔ MyMemory ➔ Google gtx)
          │        └─► Circuit Breakers: 60s cooldown on HTTP 429
          └─► Step 5: Multi-Model LLM Failover (Groq ➔ OpenRouter `:free` tier)
          │
          ▼
   `relay.py` (deliver_to_channel via Discord Webhooks)
          ├─► Enforces `AllowedMentions.none()` (zero spam ping storms)
          ├─► Localized reply context header (`┌ 💬 author: quoted text`)
          ├─► Record UUID mapping in SQLite (`message_sync` table)
          └─► Edit/Delete sync listeners for cross-channel parity
```

---

## 2. Codebase Directory & File Responsibility Index

| File | Primary Responsibility | Key Classes / Functions | Depends On |
| :--- | :--- | :--- | :--- |
| **`bot.py`** | Bot bootstrap, Discord gateway events, slash commands (`/translate-add`, `/translate-remove`, `/translate-setup`, `/translate-doctor`, `/translate-status`), `View Original Text` context menu, flag emoji reactions, 60-day pruning task. | `bot`, `translate_setup()`, `translate_doctor()`, `view_original_text()`, `on_raw_reaction_add()` | `config`, `database`, `translator`, `relay` |
| **`relay.py`** | Cross-channel fan-out, webhook lifecycle/caching, reply context localization, edit/delete synchronization, loop avoidance, `//` privacy opt-out prefix. | `WebhookRelayManager`, `LRUMessageMap`, `relay_message()`, `sync_edit()`, `sync_delete()` | `database`, `translator`, `hinglish_normalizer`, `hinglish_gatekeeper`, `spam_filter` |
| **`spam_filter.py`** | Anti-spam and meaningless message protection: duplicate bursts, keyboard smashes, repetitive word loops, newline bombs. | `AntiSpamManager`, `is_spam_or_meaningless()`, `is_meaningless_text()` | *Standard Library* |
| **`translator.py`** | Strict priority cascade (`rotate=False`), circuit breakers, 2-tier caching, syntax shielding for Discord markdown/mentions/emojis, Google `gtx` public client, message chunking (<2000 chars). | `TranslationService`, `CircuitBreaker`, `is_passthrough_text()`, `shield_syntax()`, `restore_syntax()`, `chunk_message()`, `googleapis_translate()` | `config`, `database`, `hinglish_normalizer` |
| **`database.py`** | Async SQLite persistence (`aiosqlite`) with WAL mode, channel mappings, conversation UUID tracking, L2 translation cache, 60-day sync pruning, and pre-seeded common phrase corpus. | `DatabaseManager`, `get_cached_translation()`, `set_cached_translation()`, `seed_common_translations()`, `prune_old_sync_records()` | `aiosqlite` |
| **`hinglish_normalizer.py`** | Conversational Hinglish $\leftrightarrow$ English translation, multi-model failover (Groq $\to$ OpenRouter), whitespace collapsing, strict zero-cost `:free` tier enforcement. | `HinglishNormalizer`, `normalize_hinglish()`, `to_romanized_hindi()`, `translate_general()` | `config`, `groq`, `httpx` |
| **`hinglish_gatekeeper.py`** | Zero-latency heuristic pre-filter for Hinglish detection and safe English bypass in romanized channels. | `is_potential_hinglish()`, `is_already_english()`, `HINGLISH_KEYWORDS` | *Standard Library* |
| **`config.py`** | Centralized configuration, environment variable validation, language lists, and model candidate fallbacks. | `DISCORD_TOKEN`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `GROQ_MODELS`, `OPENROUTER_MODELS` | `os`, `dotenv` |

---

## 3. Database Schema (`polyglot.db`)

Engine: **SQLite 3** operating in **WAL (Write-Ahead Logging)** mode for high concurrency.

```sql
-- 1. Logical translation groups
CREATE TABLE translation_groups (
    group_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Channel registry and language configuration
CREATE TABLE group_channels (
    channel_id INTEGER PRIMARY KEY,
    group_id TEXT NOT NULL,
    language_code TEXT NOT NULL,
    is_romanized INTEGER DEFAULT 0,
    FOREIGN KEY (group_id) REFERENCES translation_groups(group_id) ON DELETE CASCADE
);

-- 3. Cross-channel message synchronization and reply tracking
CREATE TABLE message_sync (
    conversation_uuid TEXT NOT NULL,
    source_channel_id INTEGER NOT NULL,
    source_message_id INTEGER NOT NULL,
    dest_channel_id INTEGER NOT NULL,
    relayed_message_id INTEGER NOT NULL,
    parent_uuid TEXT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (conversation_uuid, dest_channel_id, relayed_message_id)
);
CREATE INDEX idx_source_msg ON message_sync(source_message_id);
CREATE INDEX idx_relayed_msg ON message_sync(relayed_message_id);
CREATE INDEX idx_conv_uuid ON message_sync(conversation_uuid);

-- 4. Persistent L2 Translation Cache (survives restarts/redeployments)
CREATE TABLE translation_cache (
    source_lang TEXT NOT NULL,
    target_lang TEXT NOT NULL,
    source_text TEXT NOT NULL,
    translated_text TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (source_lang, target_lang, source_text)
);
```

---

## 4. Quotas, Rate Limits & Failover Architecture

| Provider / Service | Tier / Quota | Circuit Breaker Cooldown | Fallback Strategy |
| :--- | :--- | :--- | :--- |
| **L1 RAM Cache** | 2,000 LRU entries | None (Instant in-memory) | Miss $\to$ Check L2 SQLite Cache |
| **L2 SQLite Cache** | Persistent disk | None (Local DB query) | Miss $\to$ Priority Cascade |
| **Azure AI Translator** | 2,000,000 chars/mo free recurring (`westus2`) | 60 seconds on HTTP 429 | 100% Primary Driver $\to$ Fails to MyMemory |
| **DeepL Free** | Optional API key (if configured) | 60 seconds on HTTP 429 | Fails $\to$ MyMemory |
| **MyMemory** | 50,000 words/day (authenticated by email) | 60 seconds on HTTP 429 | First quota failover $\to$ Google Public Client |
| **Google Public Client** | `translate.googleapis.com` (`client=gtx`) | 60 seconds on HTTP 429 | Emergency fallback $\to$ Groq LLM Failover |
| **Groq LLM** | Free Tier (~200k TPD per model) | 60 seconds on HTTP 429 | Cascades through 4 Groq models $\to$ OpenRouter |
| **OpenRouter** | 100% Free (`:free` models only) | Cascades through free models | Ensures strict \$0.00 spend guardrails |

---

## 5. Security Invariants & Golden Rules

1. **Zero Secret Leaks:** Never commit `.env` or paste API keys, emails, or tokens in logs or git commits.
2. **Zero Notification Spam:** Every webhook message sent or edited must include:
   ```python
   allowed_mentions = discord.AllowedMentions.none()
   ```
3. **Zero Financial Cost:** Any OpenRouter model identifier in `config.py` **must** include the `:free` suffix (e.g. `meta-llama/llama-3.3-70b-instruct:free`). The code actively asserts this suffix.
4. **Passthrough Safety:**
   - URLs, Discord emojis (`<:name:id>`), pure mentions (`<@id>`), and gaming slang (`lol`, `gg`, `yessss`) must bypass translation APIs via `is_passthrough_text()`.
   - Thai characters (`\u0E00-\u0E7F`) are non-Latin alphabets and **must not** be classified as symbols or passthrough.

---

## 6. Test Suite Matrix (`pytest`)

Run all tests:
```bash
pytest
```

| Test File | Focus Area |
| :--- | :--- |
| `tests/test_caching_and_passthrough.py` | L1 LRU cache, L2 SQLite cache persistence, Circuit breaker 429 trips, Strict priority cascade hierarchy, Thai text validation, Elongated slang collapsing. |
| `tests/test_relay_safety.py` | Anti-loop protection, bot/webhook ignores, non-text channel filtering, command prefix ignores. |
| `tests/test_reply_localization.py` | Quoted snippet translation into the target channel's language. |
| `tests/test_shielding.py` | Mention, emoji, and code block token replacement & restoration. |
| `tests/test_hinglish.py` | Gatekeeper heuristics, LLM prompt normalization, OpenRouter `:free` fallback. |
| `tests/test_database.py` | SQLite schema, WAL mode, dynamic channel adding/removal, sync mappings. |
| `tests/test_chunking.py` | Message splitting under Discord's 2000-character boundary. |
| `tests/test_translator_mock.py` | Provider fallback sequence, Azure success/failover, Google `gtx` JSON parsing & 429 trips. |
