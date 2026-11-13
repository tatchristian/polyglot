import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from hinglish_gatekeeper import is_potential_hinglish
from hinglish_normalizer import HinglishNormalizer

def test_hinglish_gatekeeper_detection():
    # Common Hinglish phrases
    assert is_potential_hinglish("bhai kal tournament kitne baje hai") is True
    assert is_potential_hinglish("kya chal raha hai aaj") is True
    assert is_potential_hinglish("ha start karo tournament") is True
    assert is_potential_hinglish("mujhe nahi pata yaar") is True
    assert is_potential_hinglish("accha theek hai") is True

    # Standard English phrases should not trigger
    assert is_potential_hinglish("Hello everyone, how are you doing today?") is False
    assert is_potential_hinglish("The tournament schedule will be announced tomorrow.") is False
    assert is_potential_hinglish("Good game well played") is False

    # Numbers and emojis should not trigger
    assert is_potential_hinglish("123456") is False
    assert is_potential_hinglish("🥀🚀🎉") is False

@pytest.mark.asyncio
async def test_hinglish_normalizer_success():
    normalizer = HinglishNormalizer(api_key="mock_key")

    mock_chat = AsyncMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "Brother, what time is the tournament tomorrow?"
    mock_response = MagicMock(choices=[mock_choice])
    mock_chat.completions.create.return_value = mock_response

    normalizer.client.chat = mock_chat

    result = await normalizer.normalize_hinglish("bhai kal tournament kitne baje hai")
    assert result == "Brother, what time is the tournament tomorrow?"
    assert normalizer.stats["groq_normalizations"] == 1
    assert normalizer.stats["groq_failures"] == 0

@pytest.mark.asyncio
async def test_hinglish_normalizer_fallback_on_error():
    normalizer = HinglishNormalizer(api_key="mock_key")

    mock_chat = AsyncMock()
    mock_chat.completions.create.side_effect = Exception("API rate limited")
    normalizer.client.chat = mock_chat

    result = await normalizer.normalize_hinglish("bhai fail ho gaya")
    assert result is None
    assert normalizer.stats["groq_failures"] == 1

@pytest.mark.asyncio
async def test_to_romanized_hindi_success():
    normalizer = HinglishNormalizer(api_key="mock_key")

    mock_chat = AsyncMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "Kal tournament kitne baje hai?"
    mock_response = MagicMock(choices=[mock_choice])
    mock_chat.completions.create.return_value = mock_response

    normalizer.client.chat = mock_chat

    result = await normalizer.to_romanized_hindi("What time is the tournament tomorrow?")
    assert result == "Kal tournament kitne baje hai?"
    assert normalizer.stats["groq_to_romanized"] == 1

@pytest.mark.asyncio
async def test_multi_model_failover_success():
    normalizer = HinglishNormalizer(api_key="mock_key", groq_models=["model_1", "model_2"])

    mock_chat = AsyncMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "Success from model 2"
    mock_response = MagicMock(choices=[mock_choice])

    # First call (model_1) fails with RateLimit; second call (model_2) succeeds
    mock_chat.completions.create.side_effect = [
        Exception("Rate limit 429 on model_1"),
        mock_response
    ]
    normalizer.client.chat = mock_chat

    result = await normalizer.normalize_hinglish("bhai failover test")
    assert result == "Success from model 2"
    assert normalizer.stats["model_failovers"] == 1
    assert normalizer.stats["groq_normalizations"] == 1
