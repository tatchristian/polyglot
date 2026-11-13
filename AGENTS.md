# AGENTS.md — Agent Working Guidelines

Welcome, AI Agent. Before performing any code edits or searches, read [MAP.md](file:///c:/Users/tatch/polyglot%20bot/MAP.md) for the complete architecture map, database schemas, and message flows.

## Core Rules for Agents Working on This Repository
1. **Never edit blind:** Check [MAP.md](file:///c:/Users/tatch/polyglot%20bot/MAP.md) to identify which file owns a capability before grepping.
2. **Never commit `.env`:** Keep credentials and tokens out of version control.
3. **Strict Zero-Cost Rule:** All OpenRouter models must use `:free` identifiers.
4. **Discord Mentions Guardrail:** Always pass `allowed_mentions=discord.AllowedMentions.none()` to webhook deliveries.
5. **Verification Requirement:** Run `pytest` before reporting completion. All 46 tests must remain green.
