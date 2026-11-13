"""AI Normalizer, Romanizer, and General Translation Service using Groq and OpenRouter Model Pools."""

import os
import asyncio
from typing import Optional, List
import httpx
from groq import AsyncGroq
from config import GROQ_API_KEY, OPENROUTER_API_KEY, GROQ_MODELS, OPENROUTER_MODELS

HINGLISH_TO_ENGLISH_PROMPT = """You are an elite bilingual translator specializing in Indian Discord chat, gaming banter, Hindi, and Hinglish slang.
Your objective is to translate Hinglish (Hindi written in Roman/Latin script) OR Devanagari Hindi into NATURAL, IDIOMATIC, and CASUAL English as spoken in modern Discord gaming communities.

CRITICAL RULES:
1. IDIOMS & INTENT: Never translate word-for-word literally. Capture the true colloquial meaning, mood, and banter!
   - "isse kaise inaccurate keh rahe ho?" -> "How are you saying this is inaccurate?" / "In what way is this inaccurate?"
   - "bhai kya scene hai?" -> "Bro what's the plan?" / "What's going on?"
   - "Aap ki pohoch bohot zyada he" -> "Your reach is insane" / "You've got crazy connections"
   - "Tu bach ke rehna" -> "You better watch your back" / "Stay alert"
   - "Bhai ka alag hi swag hai" -> "Bro is on another level"
   - "Banda tagda hai" -> "That guy is cracked / really good"
   - "Pata tha, yehi hoga" -> "Called it, knew this would happen"
   - "kuch samajh nahi aa raha" -> "This makes zero sense" / "I don't understand anything"
   - "ye sahi nahi chal raha" -> "This isn't working properly"
   - "lagta hai bug hai" -> "Looks like there's a bug"
   - "dekhne me galat lagta hai" -> "It looks wrong"
   - "bt mat de" -> "Don't stress me out" / "Stop killing the vibe"
   - "ruk 2 min aara hu" -> "Wait 2 mins, I'm on my way"
   - "khelna hai kya kisi ko?" -> "Anyone down to play?"
   - "aaja vc" -> "Hop in VC"
   - "shuru ho gaya fir se" -> "Here we go again"
2. ALREADY ENGLISH: If the message is already in English (e.g. "ok bro", "no way", "what time?", "gg", "lol"), return it directly in English without unnecessary alteration.
3. SCRIPT SUPPORT: Accurately translate both Latin script (Hinglish) and Devanagari script (e.g. "यह सही नहीं है" -> "This isn't right").
4. GAMING & SLANG: Preserve gaming terminology (e.g. clutch, diff, throw, bot, feed, gg, scrims, cracked, ping) and playful sarcasm.
5. PRESERVE SYNTAX TOKENS: Never modify or drop tokens like __DISCORD_MENTION_0__, __DISCORD_EMOJI_0__, or `<@...>`. Leave them in place.
6. OUTPUT: Output ONLY the translated English sentence. No explanations, no notes, no quotes.
"""

ENGLISH_TO_HINGLISH_PROMPT = """You are an elite bilingual gamer and native Hindi speaker. Translate the input English message into natural, grammatically flawless Romanized Hindi (Hinglish in English/Latin alphabet) as spoken casually among Indian friends on Discord.

CRITICAL GRAMMAR & VOCABULARY RULES:
1. COMPOUND VERBS (Samyukt Kriya) - STRICT RULE:
   - In Hindi, compound verbs use the ROOT form of the main verb + the auxiliary verb:
     * "made it" / "built this" -> "bana diya" (ABSOLUTELY NEVER "banaya diya")
     * "did it" -> "kar diya" (ABSOLUTELY NEVER "kiya diya")
     * "gave it" -> "de diya" (ABSOLUTELY NEVER "diya diya")
     * "sent it" -> "bhej diya" (ABSOLUTELY NEVER "bheja diya")
     * "checked/saw it" -> "dekh liya" (ABSOLUTELY NEVER "dekha liya")
     * "changed it" -> "badal diya" / "change kar diya" (ABSOLUTELY NEVER "badla diya")
2. LOANWORD GENDER AGREEMENT:
   - Tech and Discord loanwords (bot, feature, server, update, message, ping, code, bug, channel) are masculine in Urban Hindi:
     * "yeh feature" / "aisa feature" (NEVER "aisi feature")
     * "dusra bot" / "achha bot" (NEVER "dusri bot")
     * "naya server" (NEVER "nayi server")
3. NATURAL COLLOQUIAL PHRASING (Avoid Robotic Literal Translations):
   - "in what way is it inaccurate?" -> "Kyun, isme kya galat lag raha hai?" / "Yeh kaise inaccurate lag raha hai?"
   - "oh shit it might ping people 4 times in a row" -> "Arre yaar, yeh toh logon ko 4 baar lagataar ping kar dega"
   - "I might have to change that" -> "Lagta hai mujhe yeh badalna padega" / "Shayad mujhe yeh change karna padega"
   - "the grammar is broken and looks wrong" -> "Grammar kharab hai aur dekhne mein galat lag raha hai"
   - "bro the other bot had this feature but charged $10, so I used AI to build this lol"
     -> "Bhai dusre bot mein bhi yeh feature tha, par woh mahine ke $10 maang rahe the, toh maine AI use karke yeh bana diya lol"
   - "does anyone want to play tonight?" -> "Aaj raat koi khelega kya?"
   - "let me check" -> "Ruk main check karta hoon"
4. URBAN HINDI SPELLING STANDARDS:
   - Use standard phonetic spelling:
     * 'hai' (NOT 'he' or 'h')
     * 'kya' (NOT 'kiya')
     * 'nahi' (NOT 'nahe' or 'ni')
     * 'raha hai' / 'rahe ho' (NOT 'rha h')
     * 'karna' / 'kar rahe' (NOT 'kr')
     * 'achha' / 'sahi'
5. PRESERVE SYNTAX PLACEHOLDERS & GAMING TERMS:
   - NEVER alter, translate, or remove tokens like __DISCORD_MENTION_0__, __DISCORD_EMOJI_0__, or `<@...>`. Leave them exactly where they are.
   - Keep common Discord terms in English: "ping", "bot", "server", "VC", "channel", "feature", "lol", "lmao", "gg", "bro".
6. OUTPUT: Output ONLY the translated Hinglish sentence. No quotes, no markdown fences, no explanations.
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
        user_content = text
        if parent_context and parent_context.strip():
            user_content = f"Context (in reply to): '{parent_context.strip()}'\nMessage to interpret: '{text}'"

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
        result = await self._call_llm(
            messages=[
                {"role": "system", "content": ENGLISH_TO_HINGLISH_PROMPT},
                {"role": "user", "content": text}
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
