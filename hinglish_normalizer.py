"""AI Normalizer and Romanizer for Hinglish using Groq Qwen 27B."""

import os
import asyncio
from typing import Optional
from groq import AsyncGroq
from config import GROQ_API_KEY

MODEL_NAME = "qwen/qwen3.8-27b"

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
                timeout=4.0
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
                timeout=4.0
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
