import time
from spam_filter import AntiSpamManager

def test_normal_messages_not_blocked():
    manager = AntiSpamManager()
    normal_texts = [
        "Hello everyone, how is it going?",
        "bhai kal tournament kitne baje hai",
        "vamos a jugar una partida rapida",
        "https://example.com/some/long/link/with/parameters?id=123",
        "ggwp",
        "kya scene hai",
        "Bro check out this cool project: ```print('hello world')```",
    ]
    # Each normal user sends their own message
    for i, text in enumerate(normal_texts):
        is_spam, reason = manager.is_spam_or_meaningless(1000 + i, 99999, text)
        assert is_spam is False, f"Flagged valid text as spam ({reason}): {text}"

def test_duplicate_message_burst():
    manager = AntiSpamManager(duplicate_window_sec=2.0)
    user_id = 1001
    channel_id = 2001

    # First send is fine
    is_spam1, _ = manager.is_spam_or_meaningless(user_id, channel_id, "hello world")
    assert is_spam1 is False

    # Immediate duplicate send is flagged
    is_spam2, reason2 = manager.is_spam_or_meaningless(user_id, channel_id, "hello world")
    assert is_spam2 is True
    assert reason2 == "duplicate_spam"

    # Different channel is not flagged
    is_spam3, _ = manager.is_spam_or_meaningless(user_id, 2002, "hello world")
    assert is_spam3 is False

def test_burst_rate_limit():
    manager = AntiSpamManager(burst_window_sec=3.0, max_burst_count=3)
    user_id = 5555
    channel_id = 6666

    assert manager.is_spam_or_meaningless(user_id, channel_id, "msg 1")[0] is False
    assert manager.is_spam_or_meaningless(user_id, channel_id, "msg 2")[0] is False
    assert manager.is_spam_or_meaningless(user_id, channel_id, "msg 3")[0] is False
    # 4th message exceeds max_burst_count (3)
    is_spam4, reason = manager.is_spam_or_meaningless(user_id, channel_id, "msg 4")
    assert is_spam4 is True
    assert reason == "burst_rate_limit"

def test_character_repetition_smash():
    # 15+ consecutive identical characters
    smash = "loooooooooooooooooooooooooool"
    is_spam, reason = AntiSpamManager.is_meaningless_text(smash)
    assert is_spam is True
    assert reason == "character_repetition_smash"

    dots = "Wait................................"
    is_spam2, reason2 = AntiSpamManager.is_meaningless_text(dots)
    assert is_spam2 is True
    assert reason2 == "character_repetition_smash"

def test_repetitive_word_loop():
    repeated_words = "spam " * 15
    is_spam, reason = AntiSpamManager.is_meaningless_text(repeated_words)
    assert is_spam is True
    assert reason == "repetitive_word_loop"

def test_low_entropy_gibberish():
    # Long text with very few unique characters
    gibberish = "ababababababababababababababababababababababababababababababababababababababababababababab"
    is_spam, reason = AntiSpamManager.is_meaningless_text(gibberish)
    assert is_spam is True
    assert reason == "low_entropy_gibberish"

def test_excessive_newline_bomb():
    bomb = "hello\n" + "\n" * 20 + "world"
    is_spam, reason = AntiSpamManager.is_meaningless_text(bomb)
    assert is_spam is True
    assert reason == "excessive_newlines"

def test_unbroken_token_overflow():
    # Single token with > 120 chars without spaces and varied characters
    unbroken = "abcdefghijklmnopqrstuvwxyz0123456789" * 4
    is_spam, reason = AntiSpamManager.is_meaningless_text(unbroken)
    assert is_spam is True
    assert reason == "unbroken_token_overflow"
