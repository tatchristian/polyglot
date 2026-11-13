"""AI Normalizer and Romanizer for Hinglish using Groq Qwen 27B."""

import os
import asyncio
from typing import Optional
from groq import AsyncGroq
from config import GROQ_API_KEY

MODEL_NAME = "qwen/qwen3.8-27b"

HINGLISH_TO_ENGLISH_PROMPT = """You are a precision linguist specializing in Hinglish (Hindi written in Roman/Latin script) and multilingual community chat.
When given a Hinglish message, output ONLY the faithful English interpretation.
- Preserve proper nouns, game terms, emojis, usernames, and tone.
- Do NOT add explanations, notes, or quotes.
- Output ONLY the translated English sentence.
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
