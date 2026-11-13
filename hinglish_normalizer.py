"""AI Normalizer for Romanized Hindi (Hinglish) using Groq Llama 3.3 70B."""

import os
import asyncio
from typing import Optional, Tuple
from groq import AsyncGroq
from config import GROQ_API_KEY

MODEL_NAME = "qwen/qwen3.8-27b"

SYSTEM_PROMPT = """You are a precision linguist specializing in Hinglish (Hindi written in Roman/Latin script) and multilingual community chat.
When given a Hinglish message, your job is to output ONLY the faithful English interpretation of the message.
- Preserve proper nouns, game terms, emojis, usernames, and tone.
- Do NOT add explanations, notes, or quotes.
- Output ONLY the translated English sentence.
"""

class HinglishNormalizer:
    """Normalizes informal Hinglish into canonical English using ultra-fast Groq Llama 3.3 70B."""

    def __init__(self, api_key: Optional[str] = GROQ_API_KEY):
        self.api_key = api_key
        self.client = AsyncGroq(api_key=api_key) if api_key else None
        self.stats = {
            "hinglish_detections": 0,
            "groq_normalizations": 0,
            "groq_failures": 0,
        }

    async def normalize_hinglish(
        self,
        text: str,
        parent_context: Optional[str] = None
    ) -> Optional[str]:
        """
        Interprets Hinglish text using Groq with parent message context.
        Returns normalized English text, or None if skipped/failed.
        """
        if not self.client or not self.api_key:
            return None

        user_content = text
        if parent_context and parent_context.strip():
            user_content = f"Context (in reply to): '{parent_context.strip()}'\nMessage to interpret: '{text}'"

        try:
            # 2.5 second timeout to keep Discord relay real-time
            response = await asyncio.wait_for(
                self.client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_content}
                    ],
                    temperature=0.2,
                    max_tokens=256,
                ),
                timeout=2.5
            )
            result = response.choices[0].message.content.strip()
            # Strip enclosing quotes if model returned them
            if result.startswith('"') and result.endswith('"'):
                result = result[1:-1].strip()

            self.stats["groq_normalizations"] += 1
            return result
        except Exception as e:
            print(f"Hinglish normalization failed/timed out: {e}")
            self.stats["groq_failures"] += 1
            return None
