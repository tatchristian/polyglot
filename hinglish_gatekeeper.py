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

# Common English structure words for zero-token bypass
COMMON_ENGLISH_WORDS: Set[str] = {
    "the", "be", "to", "of", "and", "a", "in", "that", "have", "i",
    "it", "for", "not", "on", "with", "he", "as", "you", "do", "at",
    "this", "but", "his", "by", "from", "they", "we", "say", "her",
    "she", "or", "an", "will", "my", "one", "all", "would", "there",
    "their", "what", "so", "up", "out", "if", "about", "who", "get",
    "which", "go", "when", "make", "can", "like", "time", "no",
    "just", "him", "know", "take", "people", "into", "year", "your",
    "good", "some", "could", "them", "see", "other", "than", "then",
    "now", "look", "only", "come", "its", "over", "think", "also",
    "back", "after", "use", "two", "how", "our", "work", "first",
    "well", "way", "even", "new", "want", "because", "any", "these",
    "give", "day", "most", "are", "is", "was", "were", "been", "playing",
    "game", "play", "night", "morning", "server", "bot", "ping", "help"
}

def is_already_english(text: str) -> bool:
    """
    Checks if a message in a romanized channel is already standard English.
    Returns True ONLY if:
    1. Contains zero Devanagari Hindi characters (\u0900-\u097F).
    2. Contains zero Hinglish keywords (is_potential_hinglish is False).
    3. Contains common English structural words.
    """
    cleaned = text.strip()
    if not cleaned:
        return True

    # 1. Any Devanagari character means it's Hindi, NOT English
    if re.search(r"[\u0900-\u097F]", cleaned):
        return False

    # 2. Any Hinglish keyword means it should be processed by AI
    if is_potential_hinglish(cleaned):
        return False

    # 3. Check for English word presence
    words = re.findall(r"\b[a-zA-Z]+\b", cleaned.lower())
    if not words:
        return False

    # Count how many words are recognized common English words
    english_matches = sum(1 for w in words if w in COMMON_ENGLISH_WORDS)

    # If the message has multiple words and at least 40% are recognized English words, it's English
    if len(words) >= 2 and (english_matches / len(words)) >= 0.4:
        return True

    return False
