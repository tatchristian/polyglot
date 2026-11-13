import pytest
from translator import shield_syntax, restore_syntax

def test_custom_emoji_shielding():
    original = "Hello <:pepe_smile:123456789012345678> and animated <a:party_blob:987654321098765432>!"
    shielded, tokens = shield_syntax(original)

    assert "<:pepe_smile:123456789012345678>" not in shielded
    assert "<a:party_blob:987654321098765432>" not in shielded
    assert len(tokens) == 2

    # Simulate translation preserving token
    restored = restore_syntax(shielded, tokens)
    assert restored == original

def test_code_block_shielding():
    original = "Run this code:\n```python\nimport discord\nprint('Hello world!')\n```\nEnjoy!"
    shielded, tokens = shield_syntax(original)

    assert "import discord" not in shielded
    assert len(tokens) == 1

    restored = restore_syntax(shielded, tokens)
    assert restored == original

def test_inline_code_shielding():
    original = "Use `git pull origin main` to update."
    shielded, tokens = shield_syntax(original)

    assert "`git pull origin main`" not in shielded
    assert len(tokens) == 1

    restored = restore_syntax(shielded, tokens)
    assert restored == original

def test_combined_syntax_shielding():
    original = "Look at <:sparkles:111222> and run `npm start` with:\n```bash\necho done\n```"
    shielded, tokens = shield_syntax(original)

    assert len(tokens) == 3
    restored = restore_syntax(shielded, tokens)
    assert restored == original
