"""AI Normalizer, Romanizer, and General Translation Service using Groq and OpenRouter Model Pools."""

import os
import re
import asyncio
from typing import Optional, List
import httpx
from groq import AsyncGroq
from config import GROQ_API_KEY, OPENROUTER_API_KEY, GROQ_MODELS, OPENROUTER_MODELS

HINGLISH_TO_ENGLISH_PROMPT = """Translate Hinglish (Roman/Devanagari Hindi) into casual, idiomatic Discord gaming English.
Rules:
1. Capture conversational banter/intent, never literal word-for-word:
   - "isse kaise inaccurate keh rahe ho?" -> "In what way is this inaccurate?"
   - "lagta hai change karna padega" -> "Looks like I'll have to change it"
   - "khelna hai kya" -> "Anyone down to play?"
   - "bhai kya scene hai" -> "Bro what's the plan?"
2. If already English, return as-is. Preserve gaming slang (clutch, diff, ping, gg).
3. NEVER modify syntax tokens like __DISCORD_MENTION_0__ or `<@...>`.
4. Output ONLY the translated English sentence without quotes or explanations.
"""

ENGLISH_TO_HINGLISH_PROMPT = """Translate English to natural Romanized Hindi (Hinglish in Latin script) for Discord gaming chat.
Rules:
1. Compound Verbs: Root verb + auxiliary (e.g. "bana diya" NEVER "banaya diya", "kar diya", "bhej diya").
2. Tech Loanword Agreement: Masculine gender ("yeh feature", "achha bot", "naya server").
3. Natural Phrasing:
   - "In what way is this inaccurate?" -> "isse kaise inaccurate keh rahe ho?"
   - "I might have to change that" -> "lagta hai change karna padega"
   - "Anyone down to play?" -> "khelna hai kya"
4. Standard phonetic spelling: 'hai' (not 'he'), 'nahi' (not 'ni'), 'kya' (not 'kiya').
5. NEVER modify syntax tokens like __DISCORD_MENTION_0__ or `<@...>`.
6. Output ONLY the translated Hinglish sentence without quotes or explanations.
"""

class HinglishNormalizer:
    """Normalizes informal Hinglish into canonical English, generates Romanized Hindi, and provides multi-model translation."""

    def __init__(
        self,
        api_key: Optional[str] = GROQ_API_KEY,
        openrouter_api_key: Optional[str] = OPENROUTER_API_KEY,
        groq_models: Optional[List[str]] = None,
        openrouter_models: Optional[List[str]] = None,
    ):
        self.api_key = api_key
        self.openrouter_api_key = openrouter_api_key
        self.client = AsyncGroq(api_key=api_key) if api_key else None
        self.groq_models = groq_models or list(GROQ_MODELS)
        self.openrouter_models = openrouter_models or list(OPENROUTER_MODELS)
        self.stats = {
            "hinglish_detections": 0,
            "groq_normalizations": 0,
            "groq_to_romanized": 0,
            "llm_general_translations": 0,
            "groq_failures": 0,
            "model_failovers": 0,
        }

    async def _call_llm(
        self,
        messages: list,
        temperature: float = 0.2,
        max_tokens: int = 256
    ) -> Optional[str]:
        """Executes LLM completion across the Groq model pool, cascading to OpenRouter on quota/rate limits."""
        # 1. Try Groq Model Pool
        if self.client and self.api_key:
            for model in self.groq_models:
                try:
                    response = await asyncio.wait_for(
                        self.client.chat.completions.create(
                            model=model,
                            messages=messages,
                            temperature=temperature,
                            max_tokens=max_tokens,
                        ),
                        timeout=4.0
                    )
                    result = response.choices[0].message.content.strip()
                    if result.startswith('"') and result.endswith('"'):
                        result = result[1:-1].strip()
                    return result
                except Exception as e:
                    self.stats["model_failovers"] += 1
                    print(f"Groq model '{model}' failed ({e}). Cascading to next model in pool...")
                    continue

        # 2. Try OpenRouter Free Pool if configured
        if self.openrouter_api_key:
            for model in self.openrouter_models:
                # Absolute zero-cost guarantee: only invoke explicitly free models
                if not model.endswith(":free"):
                    print(f"Safety guard: Skipping non-free OpenRouter model '{model}' to guarantee $0 cost.")
                    continue

                try:
                    async with httpx.AsyncClient(timeout=5.0) as http_client:
                        res = await http_client.post(
                            "https://openrouter.ai/api/v1/chat/completions",
                            headers={
                                "Authorization": f"Bearer {self.openrouter_api_key}",
                                "HTTP-Referer": "https://github.com/tatchristian/polyglot",
                                "X-Title": "Polyglot Discord Translator"
                            },
                            json={
                                "model": model,
                                "messages": messages,
                                "temperature": temperature,
                                "max_tokens": max_tokens,
                            }
                        )
                        if res.status_code == 200:
                            data = res.json()
                            result = data["choices"][0]["message"]["content"].strip()
                            if result.startswith('"') and result.endswith('"'):
                                result = result[1:-1].strip()
                            return result
                        else:
                            print(f"OpenRouter '{model}' returned status {res.status_code}. Cascading...")
                except Exception as e:
                    print(f"OpenRouter model '{model}' failed ({e}). Cascading...")
                    continue

        self.stats["groq_failures"] += 1
        return None

    async def normalize_hinglish(
        self,
        text: str,
        parent_context: Optional[str] = None
    ) -> Optional[str]:
        """Interprets Hinglish text into clean English using parent context and cascading models."""
        cleaned_text = re.sub(r'[ \t]+', ' ', text.strip())
        cleaned_text = re.sub(r'\n{3,}', '\n\n', cleaned_text)
        user_content = cleaned_text
        if parent_context and parent_context.strip():
            clean_parent = re.sub(r'[ \t]+', ' ', parent_context.strip())
            user_content = f"Context (in reply to): '{clean_parent}'\nMessage to interpret: '{cleaned_text}'"

        result = await self._call_llm(
            messages=[
                {"role": "system", "content": HINGLISH_TO_ENGLISH_PROMPT},
                {"role": "user", "content": user_content}
            ],
            temperature=0.2,
            max_tokens=256
        )
        if result:
            self.stats["groq_normalizations"] += 1
        return result

    async def to_romanized_hindi(self, text: str) -> Optional[str]:
        """Translates text into natural Romanized Hindi (Hinglish in English alphabet)."""
        cleaned_text = re.sub(r'[ \t]+', ' ', text.strip())
        cleaned_text = re.sub(r'\n{3,}', '\n\n', cleaned_text)
        result = await self._call_llm(
            messages=[
                {"role": "system", "content": ENGLISH_TO_HINGLISH_PROMPT},
                {"role": "user", "content": cleaned_text}
            ],
            temperature=0.3,
            max_tokens=256
        )
        if result:
            self.stats["groq_to_romanized"] += 1
        return result

    async def translate_general(
        self,
        text: str,
        source_lang: str,
        target_lang: str
    ) -> Optional[str]:
        """Translates general messages between any language pair using the LLM pool."""
        system_prompt = (
            f"You are a professional Discord chat translator. "
            f"Translate the following text accurately and conversationally from language '{source_lang}' to '{target_lang}'. "
            f"Preserve all Discord emojis, mentions (e.g. <@...>), channel tags, markdown, and gaming slang. "
            f"Output ONLY the translated text without quotes or explanations."
        )
        result = await self._call_llm(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ],
            temperature=0.2,
            max_tokens=512
        )
        if result:
            self.stats["llm_general_translations"] += 1
        return result
