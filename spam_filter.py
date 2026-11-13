"""Anti-spam and meaningless message detection for Discord chat relay."""

import re
import time
from collections import defaultdict, deque
from typing import Tuple, Dict, Deque

class AntiSpamManager:
    """Detects rapid message bursts, duplicate spam, keyboard smashes, and meaningless long messages."""

    def __init__(
        self,
        duplicate_window_sec: float = 6.0,
        burst_window_sec: float = 4.0,
        max_burst_count: int = 5
    ):
        self.duplicate_window = duplicate_window_sec
        self.burst_window = burst_window_sec
        self.max_burst_count = max_burst_count

        # author_id -> deque of timestamps
        self._user_timestamps: Dict[int, Deque[float]] = defaultdict(deque)
        # (author_id, channel_id) -> (last_cleaned_text, last_timestamp)
        self._last_user_message: Dict[Tuple[int, int], Tuple[str, float]] = {}

    def is_spam_or_meaningless(
        self,
        author_id: int,
        channel_id: int,
        text: str
    ) -> Tuple[bool, str]:
        """
        Evaluates a message against heuristics for:
        1. Duplicate spam in short window
        2. High-frequency message bursts
        3. Extreme character repetition (keyboard smash)
        4. Monotonous low-entropy text
        5. Extreme word repetition
        6. Excessive vertical whitespace spam (newline bombs)
        7. Unbroken super-long words (paste-bombs)

        Returns: (is_spam: bool, reason: str)
        """
        cleaned = text.strip()
        if not cleaned:
            return False, "ok"

        now = time.time()

        # 1. Duplicate message spam detection (same user, same channel, identical text within window)
        last_entry = self._last_user_message.get((author_id, channel_id))
        if last_entry:
            last_text, last_time = last_entry
            if (now - last_time) <= self.duplicate_window and cleaned.lower() == last_text.lower():
                return True, "duplicate_spam"

        # Record this message for future duplicate checks
        self._last_user_message[(author_id, channel_id)] = (cleaned, now)

        # 2. Burst rate limiter (max X messages in Y seconds)
        ts_queue = self._user_timestamps[author_id]
        # Evict timestamps older than burst window
        while ts_queue and (now - ts_queue[0]) > self.burst_window:
            ts_queue.popleft()
        ts_queue.append(now)

        if len(ts_queue) > self.max_burst_count:
            return True, "burst_rate_limit"

        # 3. Content heuristics (check for meaningless / garbage text)
        is_meaningless, reason = self.is_meaningless_text(cleaned)
        if is_meaningless:
            return True, reason

        return False, "ok"

    @staticmethod
    def is_meaningless_text(text: str) -> Tuple[bool, str]:
        """
        Inspects text structure for spam patterns without user state.
        """
        cleaned = text.strip()
        length = len(cleaned)

        # Don't penalize normal short chat (e.g. "k", "lol", "ok", "gg")
        if length < 25:
            return False, "ok"

        # A. Excessive Newline Bomb (e.g. 15+ blank newlines to stretch chat)
        newline_count = cleaned.count("\n")
        if newline_count >= 15 and (length / max(1, newline_count)) < 10:
            return True, "excessive_newlines"

        # B. Single character repeated 15+ times consecutively (e.g. "aaaaaaaaaaaaaaa...", "...........")
        if re.search(r"(.)\1{14,}", cleaned):
            return True, "character_repetition_smash"

        # C. Extremely long unbroken single word with no spaces or punctuation (keyboard smash / URL spam)
        # Note: Valid URLs are handled by is_passthrough_text, but a 120-char non-URL token is garbage
        if not cleaned.startswith("http://") and not cleaned.startswith("https://"):
            words = cleaned.split()
            for w in words:
                if len(w) > 120:
                    return True, "unbroken_token_overflow"

        # D. Low entropy / repetitive characters over long length
        # e.g., length > 80 chars, but fewer than 5 unique characters
        if length > 80:
            alphanumeric_chars = set(c.lower() for c in cleaned if c.isalnum())
            if len(alphanumeric_chars) <= 4:
                return True, "low_entropy_gibberish"

        # E. Repetitive word loops (e.g. "spam spam spam spam spam spam spam" x 15)
        tokens = [t.lower() for t in re.findall(r"\b[a-zA-Z0-9_]+\b", cleaned)]
        if len(tokens) >= 12:
            unique_tokens = set(tokens)
            # If 12+ words but only 1 or 2 distinct words
            if len(unique_tokens) <= 2:
                return True, "repetitive_word_loop"

        return False, "ok"

    def prune_old_state(self, max_age_sec: float = 60.0):
        """Housekeeping to evict old timestamps and memory entries."""
        now = time.time()
        # Clean user timestamps
        for uid in list(self._user_timestamps.keys()):
            q = self._user_timestamps[uid]
            while q and (now - q[0]) > max_age_sec:
                q.popleft()
            if not q:
                del self._user_timestamps[uid]

        # Clean duplicate cache
        for key in list(self._last_user_message.keys()):
            _, ts = self._last_user_message[key]
            if (now - ts) > max_age_sec:
                del self._last_user_message[key]
