import pytest
from translator import chunk_message

def test_short_message_no_chunking():
    text = "This is a normal message that fits comfortably within limits."
    chunks = chunk_message(text, max_length=2000)
    assert len(chunks) == 1
    assert chunks[0] == text

def test_exact_limit_message():
    text = "a" * 2000
    chunks = chunk_message(text, max_length=2000)
    assert len(chunks) == 1
    assert chunks[0] == text

def test_multiline_splitting():
    line1 = "Line 1: " + "A" * 1500
    line2 = "Line 2: " + "B" * 1000
    text = f"{line1}\n{line2}"

    chunks = chunk_message(text, max_length=2000)
    assert len(chunks) == 2
    assert len(chunks[0]) <= 2000
    assert len(chunks[1]) <= 2000
    assert chunks[0] == line1
    assert chunks[1] == line2

def test_word_boundary_splitting():
    words = ["word" + str(i) for i in range(500)]
    text = " ".join(words)
    chunks = chunk_message(text, max_length=200)

    for chunk in chunks:
        assert len(chunk) <= 200
    # Combined words should match original words
    reassembled = " ".join(chunks)
    assert reassembled.split() == words
