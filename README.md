# 🌐 Polyglot Discord Translation Engine (v2.0)

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![discord.py](https://img.shields.io/badge/discord.py-2.3+-green.svg)](https://github.com/Rapptz/discord.py)
[![Tests Passing](https://img.shields.io/badge/tests-61%20passed%20(100%25)-brightgreen.svg)](https://github.com/tatchristian/polyglot)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Cost](https://img.shields.io/badge/Cost-$0.00%2Fmo%20(Free%20Tier)-success.svg)](https://groq.com)

A high-performance, asynchronous Discord translation engine that enables users speaking different languages to chat seamlessly across dedicated language channels in real time.

Polyglot dynamically mirrors messages using **Discord Webhooks**—preserving the original author's display name and avatar—while synchronizing message replies, edits, and deletions via an asynchronous **SQLite WAL** database. It features an integrated **AI Intelligence Gatekeeper for Romanized Hindi (Hinglish)**, **Two-Tier Caching**, **Circuit Breakers**, and an **Anti-Spam Filter**.

---

## 🏗️ Architecture & Message Lifecycle

```
[ User Message in #english / #hindi / #spanish / #japanese ]
                         │
                         ▼
             [ Discord Gateway Listener ]
                         │
                         ▼
             [ on_message Gatekeeper (bot.py) ]
                         ├──> Loop Shield (blocks bot & webhook loops)
                         ├──> Command Shield (ignores prefixes: !, /, $, ., -, ?)
                         ├──> Privacy Opt-Out (ignores messages starting with // or /*)
                         └──> Anti-Spam Gatekeeper (spam_filter.py: drops bursts & smashes)
                         │
                         ▼
             [ WebhookRelayManager (relay.py) ]
                         ├──> Syntax Shielding (preserves <@mentions>, :emojis:, `code`)
                         ├──> Reply Context Linker (quotes & localizes parent reply snippet)
                         │
                         ▼
             [ Hinglish & Slang AI Normalizer ]
                         ├──> Is Romanized Channel OR Hinglish Heuristic Match?
                         │      ├── YES ──> [ AI Normalizer (hinglish_normalizer.py) ]
                         │      │             ├── Groq LPU: qwen/qwen3.8-27b (Primary)
                         │      │             ├── Failover 1: openai/gpt-oss-120b
                         │      │             ├── Failover 2: openai/gpt-oss-20b
                         │      │             └── Free Fallback: OpenRouter :free models
                         │      │             └── Pivot: Converts Hinglish into Canonical English
                         │      │
                         │      └── NO  ──> Direct bypass (pure English messages burn 0 tokens)
                         │
                         ▼
             [ Cascading Translation Pipeline (translator.py) ]
                         ├── Step 1: Passthrough Filter (URLs, gaming slang: lol, gg, ok)
                         ├── Step 2: L1 In-Memory LRU Cache (Instant RAM hit)
                         ├── Step 3: L2 Persistent SQLite Cache (Pre-seeded gaming corpus)
                         ├── Step 4: Round-Robin Traditional Providers
                         │      ├── 1. DeepL Free API (if key configured)
                         │      ├── 2. Azure AI Translator (if key configured)
                         │      ├── 3. MyMemory API (50k words/day free tier)
                         │      └── 4. Google Translate (free scraping fallback)
                         │      └── Circuit Breakers: 60s cooldown on HTTP 429 / rate limits
                         └── Step 5: Multi-Model LLM Fallback (if all traditional providers fail)
                         │
                         ▼
             [ Parallel Webhook Delivery (relay.py) ]
                         ├── Safe Mentions: AllowedMentions.none() (Zero ping storms)
                         ├── Concurrency Throttling: asyncio.Semaphore(5)
                         └── Multi-Chunk Split: Safely splits text > 2,000 characters
                         │
                         ▼
             [ Asynchronous SQLite Persistence (database.py) ]
                         └── WAL Mode: Maps Conversation UUID <-> [Channel_ID, RelayedMsgID]
                         └── Enables 100% synchronized edits and deletions
```

---

## ✨ Key Features

### 1. Universal Webhook Relay
* **Native Look & Feel:** Messages relayed to other channels show the original user's Discord nickname and avatar.
* **Full Edit & Delete Synchronization:** Editing or deleting a message in one channel automatically updates or removes all relayed copies across every other channel.
* **Localized Reply Headers:** When replying to a message, destination channels receive a localized, translated quote header (`┌ 💬 Replying to @User: "Translated context"`).
* **Multi-Chunk Support:** Messages exceeding Discord's 2,000-character limit are automatically chunked and tracked without overwriting sync history.

### 2. Conversational Hinglish Normalizer ($0 Cost)
* Uses Groq LPUs running **Qwen 27B** and **GPT-OSS 120B/20B** to convert informal Romanized Hindi (`"bhai kal tournament kitne baje hai"`) into clean conversational English (`"Bro, what time's the tournament tomorrow?"`), which then fans out to Spanish and Japanese via Google Translate.
* **Pivot Language Hub:** Uses English as the central pivot language to minimize LLM token consumption.
* **Heuristic Gatekeeper:** Pure English messages in `#hindi` automatically bypass Groq, saving 100% of LLM tokens on English chatter.

### 3. Two-Tier Caching System
* **L1 RAM Cache:** Instant bounded LRU cache for zero-latency repeats.
* **L2 SQLite Cache:** Persistent across bot restarts and redeployments. Pre-seeded with **60+ high-frequency gaming, greeting, and Discord chat phrases** across English, Spanish, Japanese, and Hindi.

### 4. Circuit Breakers & Multi-Provider Cascade
* Automatically switches between **DeepL $\to$ Azure $\to$ MyMemory $\to$ Google $\to$ Groq LLM**.
* If a provider returns `HTTP 429 (Too Many Requests)`, its circuit breaker trips into a **60-second cooldown**, automatically routing subsequent traffic to healthy providers with zero downtime.

### 5. Comprehensive Anti-Spam & Meaningless Text Filter
* **Duplicate Burst Protection:** Blocks identical messages sent within 6 seconds by the same user.
* **High-Frequency Throttling:** Caps user bursts to 5 messages per 4 seconds.
* **Gibberish & Smash Detection:** Automatically blocks keyboard smashes (`aaaaaaaaaaaaaa...`), repetitive word loops (`spam spam spam...`), newline bombs (>15 vertical line breaks), and unbroken 120+ character paste bombs from relaying.

### 6. Interactive Discord Utilities
* **Flag Emoji Quick-Translate:** React to any message with a country flag emoji (e.g. 🇪🇸, 🇯🇵, 🇫🇷, 🇩🇪, 🇮🇳, 🇰🇷) to receive an instant on-demand translation embed.
* **Original Message Verification:** Right-click any relayed message $\to$ `Apps` $\to$ `View Original Text` to inspect the author, source channel, and original untranslated text.

---

## 🎮 Slash Commands

| Command | Permission | Description |
| :--- | :--- | :--- |
| `/translate-setup` | `Manage Channels` | **1-Click Setup Wizard:** Automatically creates a `🌍 Polyglot Network` category with linked `#english`, `#spanish`, `#japanese`, and `#hindi` channels. |
| `/translate-add` | `Manage Channels` | Links any existing channel to a language, with optional `is_romanized: True` flag for AI Hinglish normalizer support. |
| `/translate-remove` | `Manage Channels` | Unlinks a channel from the translation network dynamically. |
| `/translate-doctor` | `Manage Channels` | Audits server channels for missing bot permissions, webhook health, and translation engine circuit breaker states. |
| `/translate-status` | Everyone | Displays live bot uptime, gateway ping, active channel mappings, provider metrics, and cache hit rate. |
| `View Original Text` | Everyone | Message Context Menu to view the original text of any relayed message. |

---

## 🛠️ Environment Configuration

Create a `.env` file in the project root (see `.env.example`):

```env
# Required Discord Token
DISCORD_TOKEN=your_discord_bot_token_here

# Groq API Key (Enables ultra-fast $0 Hinglish normalizer & LLM failover)
GROQ_API_KEY=gsk_your_groq_key_here

# Optional Free Providers (Cascading Failover)
OPENROUTER_API_KEY=
DEEPL_API_KEY=
AZURE_TRANSLATOR_KEY=
AZURE_REGION=eastus
MYMEMORY_EMAIL=your_email@example.com
```

### Discord Bot Permissions Required
When generating your bot's OAuth2 invite URL, enable the `bot` and `applications.commands` scopes with the following permissions:
* `Manage Channels`
* `Manage Webhooks`
* `Read Messages/View Channels`
* `Send Messages`
* `Manage Messages` (for delete synchronization)
* `Read Message History`
* `Message Content Intent` (enabled under Discord Developer Portal -> Bot -> Privileged Gateway Intents)

---

## 🚀 Quickstart & Local Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/tatchristian/polyglot.git
   cd polyglot
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Run automated verification tests:**
   ```bash
   pytest -v
   ```

4. **Launch the bot:**
   ```bash
   python -u bot.py
   ```

---

## ☁️ Deployment (Docker / Railway)

### Deploy to Railway
This repository includes native `railway.json` and `Procfile` configs for seamless 24/7 cloud hosting:

1. Push your repository to GitHub.
2. Link your GitHub repo in [Railway.app](https://railway.app).
3. Under Railway Project Settings, add your `DISCORD_TOKEN` and `GROQ_API_KEY` environment variables.
4. Railway will automatically build via Nixpacks and start `python -u bot.py`.

### Deploy via Docker
```bash
docker build -t polyglot-bot .
docker run -d --name polyglot --env-file .env polyglot-bot
```

---

## 🧪 Test Suite

The test suite covers unit tests, async mocks, database WAL isolation, circuit breaker cooldowns, and anti-spam edge cases:

```bash
pytest -v
```

```
tests/test_caching_and_passthrough.py ........ [ 13%]
tests/test_chunking.py ....                   [ 19%]
tests/test_database.py ........               [ 32%]
tests/test_hinglish.py ......                 [ 42%]
tests/test_lru_cache.py ....                  [ 49%]
tests/test_relay_safety.py ..........         [ 65%]
tests/test_reply_localization.py ...          [ 70%]
tests/test_shielding.py .....                 [ 78%]
tests/test_spam_filter.py ........            [ 91%]
tests/test_translator_mock.py .....           [100%]

============================== 61 passed in 9.09s ==============================
```

---

## 📄 License
This project is open-source under the [MIT License](LICENSE).
