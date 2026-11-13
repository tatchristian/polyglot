"""Real-world Hinglish benchmark runner using actual Discord chat logs."""

import asyncio
import time
from hinglish_gatekeeper import is_potential_hinglish
from hinglish_normalizer import HinglishNormalizer

SAMPLE_CHAT_LOG = [
    ("THE nun CRACKER", "Bhoot wali 💔"),
    ("DestinyXDamon", "Aap ki pohoch bohot zyada he"),
    ("THE nun CRACKER", "Kyu"),
    ("ժemon", "Tu Bach ke rehna. Tujhe nun na samjh le"),
    ("DestinyXDamon", "Nah nah bhai"),
    ("ժemon", "Prabh bhi aise hi gaya tha. Bechara"),
    ("Prabh", "Kya hua?"),
    ("ժemon", "Dekh dekh Pata tha Yehi ha"),
    ("Prabh", "Abhi aya hu Kya bat chl rhi?"),
    ("THE nun CRACKER", "Iska matlab demon cracker"),
]

async def run_benchmark():
    normalizer = HinglishNormalizer()
    print("=" * 70)
    print("🔥 REAL DISCORD HINGLISH BENCHMARK (Groq Qwen 27B)")
    print("=" * 70)

    for author, raw_msg in SAMPLE_CHAT_LOG:
        is_detected = is_potential_hinglish(raw_msg, source_lang="hi")
        
        t0 = time.time()
        interpreted = await normalizer.normalize_hinglish(raw_msg)
        elapsed_ms = round((time.time() - t0) * 1000, 1)

        print(f"\n👤 [{author}]: \"{raw_msg}\"")
        print(f"   • Gatekeeper Detected: {'✅ YES' if is_detected else '❌ NO'}")
        print(f"   • AI Interpretation:   \"{interpreted}\"")
        print(f"   • Latency:             {elapsed_ms} ms")

    print("\n" + "=" * 70)
    print("Benchmark complete!")

if __name__ == "__main__":
    asyncio.run(run_benchmark())
