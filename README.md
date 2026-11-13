# 🌐 Polyglot Discord Translation Engine (UMCE v2.0)

A high-performance, asynchronous conversation synchronization engine that enables people speaking different languages to chat seamlessly across language-specific channels in real time. It uses Discord webhooks to preserve the original author's display name and avatar while synchronizing replies, edits, and deletions via an asynchronous SQLite database, with an integrated **AI Intelligence Gatekeeper for Romanized Hindi (Hinglish)** and **Dynamic Slash Channel Management**.

---

## 🏗️ Architecture & Component Flow

```
[ User Message in #english / #hindi ]
                 │
                 ▼
          [ Discord Gateway ]
                 │
                 ▼
          [ on_message (bot.py) ]
                 │
                 ├──> Loop Shield (author.bot, webhook_id)
                 ├──> Command Shield (!, /, $, ., -)
                 │
                 ▼
          [ WebhookRelayManager (relay.py) ]
                 │
                 ├──> Cross-Channel Reply Linker (_build_reply_header)
                 │
                 ▼
       [ Hinglish Gatekeeper & Romanized Channel Flag ]
                 │
                 ├──> Is Romanized Channel OR Keyword Match?
                 │      │
                 │      ├── YES ──> [ AI Normalizer (hinglish_normalizer.py) ]
                 │      │             └── Groq Qwen 27B (0.3s ultra-fast normalization)
                 │      │             └── Normalizes slang into canonical English/Hindi
                 │      │
                 │      └── NO  ──> Proceed with standard text
                 │
                 ▼
       [ Cascading Translation Pipeline (translator.py) ]
                 │
                 ├── 1. DeepL Free API (if key configured)
                 ├── 2. Azure AI Translator (if key configured)
                 ├── 3. MyMemory API (50,000 words/day free tier)
                 └── 4. Google Translate (fallback scraper)
                 │
                 ▼
       [ Discord Webhook Execution (wait=True) ]
                 │
                 ▼
       [ SQLite Persistence (database.py) ]
                 └── WAL mode: Maps Conversation UUID <-> [Channel_ID, WebhookMsgID]
```

---

## 🚀 Key Commands

* `/translate-add <channel> <language> [is_romanized: True/False]` — Links a channel dynamically to a language. If `is_romanized: True`, all text typed in the channel is treated as Romanized slang and routed through the Groq AI normalizer!
* `/translate-remove <channel>` — Unlinks a channel dynamically without restarting the bot.
* `/translate-status` — Displays live latency, active channels (with `[AI Romanized]` indicators), and translation metrics.

---

## 🧪 Automated Test Suite

Run all unit tests in verbose mode:
```bash
pytest -v
```
**Test Results:** `30 passed in 3.98s` (100% Green).
