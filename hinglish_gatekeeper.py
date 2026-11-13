"""Heuristic gatekeeper for romanized Hindi (Hinglish) detection."""

import re
from typing import Set

# High-frequency phonetic romanized Hindi tokens
HINGLISH_KEYWORDS: Set[str] = {
    "bhai", "bhaiya", "yaar", "dost", "kya", "nahi", "nahin", "na",
    "haan", "karo", "karna", "kar", "karte", "aaj", "kal", "parso",
    "accha", "achha", "theek", "thik", "sahi", "kab", "kaha", "kahan",
    "kaise", "kaisa", "baje", "chal", "chalo", "chalega", "dekh", "dekho",
    "ruk", "ruko", "samjha", "samjhe", "bolo", "bol", "kuch", "kuchh",
    "matlab", "kyun", "kyu", "shuru", "khatam", "kitna", "kitne", "kitni",
    "apna", "apne", "mera", "meri", "tere", "teri", "karenge", "hoga",
    "hogi", "honge", "raha", "rahe", "rahi", "kr", "krdo", "kro",
    "bolte", "scene", "pata", "lag", "rha", "rhe", "wali", "wale", "kisko",
}

# Pre-compiled word boundary pattern for fast O(1) matching
KEYWORD_PATTERN = re.compile(
    rf"\b({'|'.join(re.escape(word) for word in HINGLISH_KEYWORDS)})\b",
    re.IGNORECASE
)

def is_potential_hinglish(text: str, source_lang: str = "en") -> bool:
    """
    Determines if a message has high likelihood of being romanized Hindi (Hinglish).
    Only runs if text contains Latin characters.
    """
    cleaned = text.strip()
    if not cleaned:
        return False

    # Must contain Latin alphabetic characters
    if not re.search(r"[a-zA-Z]", cleaned):
        return False

    matches = KEYWORD_PATTERN.findall(cleaned)
    # Distinctive marker match (e.g. 'bhai kal tournament kitne baje hai' -> 3 matches)
    if len(matches) >= 1:
        return True

    return False
