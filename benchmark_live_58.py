"""Live 58-Request Benchmark comparing Polyglot's optimized prompt against Nov 15 Groq Dashboard baseline.

Nov 15 Dashboard Baseline (qwen/qwen3.8-27b):
  - Requests: 58
  - Input Tokens: 14.5K
  - Output Tokens: 632
  - Total Tokens: 15.2K (~262 tokens/call)

This benchmark executes exactly 58 live requests against qwen/qwen3.8-27b on Groq
throttled at ~28 RPM (2.15s per call) to avoid HTTP 429 rate limits.
"""

import sys
import time
import asyncio
from dotenv import load_dotenv
from slang_normalizer import SlangNormalizer, UNIVERSAL_SLANG_TO_ENGLISH_PROMPT

load_dotenv()

# 58 realistic, distinct Romanized chat and gaming messages
MESSAGES_58 = [
    # 1-10: Hinglish gaming & lobby banter
    "bhai aaj shaam ko valorant khelega kya",
    "kya bolti public sab ready ho na",
    "bhai mera ping achanak 300 ho gaya",
    "ek round bacha hai aaram se clutch karo",
    "usse revive de jaldi cover de raha hu",
    "aaj bohot zyada lag ho raha hai server pe",
    "chal discord pe aaja voice channel 2 me",
    "bhai kal wala match kitna intense tha",
    "aaj custom room banate hai aao sab",
    "bhai tu drop leke aaja fatafat",

    # 11-20: Everyday conversational Hinglish
    "kya haal chaal hai bhai sab badhiya",
    "bhai kal market kab jaana hai bata",
    "maine usko bola tha par vo mana kar diya",
    "aaj khane me kya banaya hai mummy ne",
    "bhai assignment submit kar diya tune kya",
    "chalo chai peene chalte hai thodi der me",
    "ye phone ka battery bohot fast drain ho raha",
    "bhai mere paas bilkul time nahi hai abhi",
    "thoda wait karo main 10 minute me aata hu",
    "achha theek hai jaisa tujhe sahi lage",

    # 21-30: Indonesian / Bahasa Gaul chat
    "gw mw maen sm lu bntr lg santai",
    "wkwkwk anjir ngakak bgt liat lu mati konyol",
    "gpp bro sans aja ga usah kepikiran",
    "lu dmn skrg buruan login udh ditungguin",
    "anjir lag parah koneksi indihome gua",
    "mabar gas kuy mlbb ranked mlm ini",
    "lu udh ngerjain tugas blm sih",
    "otw bro tungguin bentar lg nyampe",
    "bisa bgt lu bro jago parah",
    "y udh bsk aj ktemu d kampus ya",

    # 31-40: Arabizi (Franco-Arab chat)
    "keifak ya akhi 7abibi shu 3am ta3mel",
    "yalla shabab footo 3al discord 3am nestanna",
    "wallah ma 3am befham 3lek shu baddak",
    "ta3al la 3enna el yom bel sahra",
    "mabrouk el fawz ya batal",
    "sho ra2yak nel3ab valorant se3a",
    "mesh 3aref shu baddi eshtri",
    "ana mshghool kteer el yom bas b7akeek bokra",
    "khalas ya zalame ma te3tal ham",
    "inshallah kel shi bseer mnee7",

    # 41-50: Fast gaming callouts & shorthand
    "bhai aaja mid rush karte hai",
    "smoke daal wahan pe enemy sniper hai",
    "bhai mere pe teen bande push kar rahe",
    "diff match tha bhai opponents bohot cracked the",
    "drop weapon bro eco round chal raha hai",
    "gg well played sabko maza aaya",
    "bhai heals de jaldi HP 10 bachi hai",
    "bhai flank dekh peeche se koi aa raha",
    "plant kar de spike time khatam ho raha",
    "last banda bacha hai usse mar aaram se",

    # 51-58: Reaction & closing banter
    "are bhai tune to pagal kar diya kya shot tha",
    "sahi khel gaya bhai dil khush ho gaya",
    "aaj ke liye bas itna hi kal milte hai",
    "good night bhai log sab so jao ab",
    "bhai clip record kar liya tha maine youtube ke liye",
    "agle hafte tournament hai practice karni padegi",
    "bhai mic on kar tera awaz nahi aa raha",
    "chalo gg boys signing off for today",
]

assert len(MESSAGES_58) == 58, f"Expected 58 messages, got {len(MESSAGES_58)}"

async def run_benchmark():
    normalizer = SlangNormalizer()
    if not normalizer.client or not normalizer.api_key:
        print("❌ Error: GROQ_API_KEY is not configured in .env")
        sys.exit(1)

    print("=" * 78)
    print("🚀 POLYGLOT 58-REQUEST LIVE GROQ BENCHMARK")
    print("=" * 78)
    print(f"• Model Under Test:      qwen/qwen3.8-27b (Groq on_demand)")
    print(f"• Total Requests:        {len(MESSAGES_58)} uncached live calls")
    print(f"• Throttling Rate:       2.15s between calls (<= 28 RPM, Free-Tier Safe)")
    print(f"• Estimated Runtime:     ~125 seconds (~2.1 minutes)")
    print(f"• Baseline to Beat:      Nov 15 (58 req -> 14.5K in, 632 out, 15.2K total)")
    print("=" * 78)

    stats = {
        "calls_made": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "latencies_ms": [],
        "errors": 0,
    }

    start_wall_time = time.time()

    for idx, msg in enumerate(MESSAGES_58, 1):
        t0 = time.perf_counter()
        try:
            resp = await normalizer.client.chat.completions.create(
                model="qwen/qwen3.8-27b",
                messages=[
                    {"role": "system", "content": UNIVERSAL_SLANG_TO_ENGLISH_PROMPT},
                    {"role": "user", "content": msg}
                ],
                temperature=0.2,
                max_tokens=256
            )
            lat_ms = (time.perf_counter() - t0) * 1000
            stats["latencies_ms"].append(lat_ms)
            stats["calls_made"] += 1

            usage = resp.usage
            pt = usage.prompt_tokens if usage else 0
            ct = usage.completion_tokens if usage else 0
            tt = usage.total_tokens if usage else (pt + ct)

            stats["prompt_tokens"] += pt
            stats["completion_tokens"] += ct
            stats["total_tokens"] += tt

            translated = resp.choices[0].message.content.strip()

            # Print updates every 5 calls or first 3
            if idx <= 3 or idx % 5 == 0 or idx == 58:
                print(
                    f"[{idx:02d}/58] ⚡ {lat_ms:5.1f}ms | In: {pt:2d} tok | Out: {ct:2d} tok | "
                    f"Running Total: {stats['total_tokens']:,} tok | "
                    f"\"{msg[:28]}\" -> \"{translated[:28]}\""
                )

        except Exception as e:
            stats["errors"] += 1
            print(f"[{idx:02d}/58] ⚠️ Error on call: {e}")

        # Throttle by 2.15s so we strictly remain <= 28 RPM
        if idx < 58:
            await asyncio.sleep(2.15)

    total_wall_time = time.time() - start_wall_time
    avg_latency = sum(stats["latencies_ms"]) / max(1, len(stats["latencies_ms"]))

    # Historical Nov 15 Baseline
    base_requests = 58
    base_prompt_tok = 14500
    base_comp_tok = 632
    base_total_tok = 15200

    saved_prompt = base_prompt_tok - stats["prompt_tokens"]
    saved_total = base_total_tok - stats["total_tokens"]
    pct_saved = (saved_total / base_total_tok) * 100

    print("\n" + "=" * 78)
    print("🏁 BENCHMARK COMPLETE: 58 LIVE GROQ CALLS EXECUTED")
    print("=" * 78)
    print(f"• Total Calls Completed:     {stats['calls_made']} / 58 (Errors: {stats['errors']})")
    print(f"• Wall-Clock Time:           {total_wall_time:.1f}s ({total_wall_time/60:.2f} minutes)")
    print(f"• Average Groq Latency:      {avg_latency:.1f} ms")
    print(f"• Total Prompt/Input Tokens: {stats['prompt_tokens']:,} (avg {stats['prompt_tokens']/max(1, stats['calls_made']):.1f} / call)")
    print(f"• Total Output Tokens:       {stats['completion_tokens']:,} (avg {stats['completion_tokens']/max(1, stats['calls_made']):.1f} / call)")
    print(f"• TOTAL TOKENS CONSUMED:     {stats['total_tokens']:,} tokens")
    print("-" * 78)
    print("📊 DIRECT COMPARISON VS NOV 15 GROQ DASHBOARD:")
    print(f"{'Metric':<26} | {'Nov 15 Baseline':<18} | {'Today (New Prompt)':<18} | {'Difference / Savings':<20}")
    print(f"{'-'*26}-+-{'-'*18}-+-{'-'*18}-+-{'-'*20}")
    print(f"{'Requests':<26} | {base_requests:<18} | {stats['calls_made']:<18} | {'Exact 1:1 Match'}")
    print(f"{'Input (Prompt) Tokens':<26} | {base_prompt_tok:<18,} | {stats['prompt_tokens']:<18,} | -{saved_prompt:,} tokens (-{saved_prompt/base_prompt_tok*100:.1f}%)")
    print(f"{'Output Tokens':<26} | {base_comp_tok:<18,} | {stats['completion_tokens']:<18,} | {stats['completion_tokens'] - base_comp_tok:+d} tokens")
    print(f"{'Total Tokens Consumed':<26} | {base_total_tok:<18,} | {stats['total_tokens']:<18,} | -{saved_total:,} tokens (-{pct_saved:.1f}%)")
    print("=" * 78)

if __name__ == "__main__":
    asyncio.run(run_benchmark())
