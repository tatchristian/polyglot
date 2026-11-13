"""AI Normalizer and Romanizer for Hinglish using Groq Qwen 27B."""

import os
import asyncio
from typing import Optional
from groq import AsyncGroq
from config import GROQ_API_KEY

MODEL_NAME = "qwen/qwen3.8-27b"

HINGLISH_TO_ENGLISH_PROMPT = """You are an elite bilingual translator specializing in Indian Discord chat, gaming banter, and Hinglish slang.
Your objective is to translate Hinglish (Hindi written in Roman/Latin script) into NATURAL, IDIOMATIC, and CASUAL English as spoken in Discord communities.

CRITICAL RULES:
1. IDIOMS & SLANG: Do NOT translate literally word-for-word. Translate the true intended meaning and vibe!
   - "Aap ki pohoch bohot zyada he" -> "Your reach is insane" / "You've got crazy connections"
   - "Kya scene hai?" -> "What's the plan?" / "What's the vibe?"
   - "Tu bach ke rehna" -> "You better watch your back" / "Stay alert"
   - "Bhai ka alag hi swag hai" -> "Bro is on another level"
   - "Banda tagda hai" -> "That guy is cracked / really good"
   - "Pata tha, yehi hoga" -> "Called it, knew this would happen"
   - "Bhai kya bat chl rhi?" -> "Bro what's everyone talking about?"
2. GAMING & BANTER: Preserve gaming terms (e.g. clutch, diff, throw, bot, feed, gg, scrims, cracked) and playful sarcasm.
3. TONE PRESERVATION: Keep the exact energy, casualness, or humor of the speaker.
4. Output ONLY the translated English sentence without explanations or quotes.
"""

ENGLISH_TO_HINGLISH_PROMPT = """You are an expert translator specializing in casual, natural Romanized Hindi (Hinglish written strictly using the Latin/English alphabet).
Translate the given English text into natural, conversational Hinglish as used in Discord and WhatsApp gaming chats.
- STRICT RULE: Do NOT use Devanagari script (हिंदी). Use ONLY the English/Latin alphabet (e.g. 'Kal tournament kitne baje hai?').
- Keep gaming terms, proper nouns, emojis, and usernames unchanged.
- Output ONLY the translated Romanized Hindi sentence without quotes or explanations.
"""

class HinglishNormalizer:
    """Normalizes informal Hinglish into canonical English and generates Romanized Hindi output."""

    def __init__(self, api_key: Optional[str] = GROQ_API_KEY):
        self.api_key = api_key
        self.client = AsyncGroq(api_key=api_key) if api_key else None
        self.stats = {
            "hinglish_detections": 0,
            "groq_normalizations": 0,
            "groq_to_romanized": 0,
            "groq_failures": 0,
        }

    async def normalize_hinglish(
        self,
        text: str,
        parent_context: Optional[str] = None
    ) -> Optional[str]:
        """Interprets Hinglish text into clean English using parent context."""
        if not self.client or not self.api_key:
            return None

        user_content = text
        if parent_context and parent_context.strip():
            user_content = f"Context (in reply to): '{parent_context.strip()}'\nMessage to interpret: '{text}'"

        try:
            response = await asyncio.wait_for(
                self.client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=[
                        {"role": "system", "content": HINGLISH_TO_ENGLISH_PROMPT},
                        {"role": "user", "content": user_content}
                    ],
                    temperature=0.2,
                    max_tokens=256,
                ),
                timeout=2.5
            )
            result = response.choices[0].message.content.strip()
            if result.startswith('"') and result.endswith('"'):
                result = result[1:-1].strip()

            self.stats["groq_normalizations"] += 1
            return result
        except Exception as e:
            print(f"Hinglish normalization failed/timed out: {e}")
            self.stats["groq_failures"] += 1
            return None

    async def to_romanized_hindi(self, text: str) -> Optional[str]:
        """Translates text into natural Romanized Hindi (Hinglish in English alphabet)."""
        if not self.client or not self.api_key:
            return None

        try:
            response = await asyncio.wait_for(
                self.client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=[
                        {"role": "system", "content": ENGLISH_TO_HINGLISH_PROMPT},
                        {"role": "user", "content": text}
                    ],
                    temperature=0.3,
                    max_tokens=256,
                ),
                timeout=2.5
            )
            result = response.choices[0].message.content.strip()
            if result.startswith('"') and result.endswith('"'):
                result = result[1:-1].strip()

            self.stats["groq_to_romanized"] += 1
            return result
        except Exception as e:
            print(f"Romanized Hindi generation failed/timed out: {e}")
            self.stats["groq_failures"] += 1
            return None
