import json
import time

import requests

PROMPT = 'Reply with JSON only: {"tool":"finish","answer":"ok"}'

for m in ["openai", "mistral", "llama", "openai-fast"]:
    try:
        r = requests.post(
            "https://text.pollinations.ai/openai",
            timeout=60,
            json={"model": m, "messages": [{"role": "user", "content": PROMPT}], "max_tokens": 100},
        )
        try:
            d = r.json()
        except Exception:
            print(m, r.status_code, "NON-JSON:", r.text[:120].replace("\n", " "))
            time.sleep(46)
            continue
        msg = (d.get("choices") or [{}])[0].get("message") or {}
        print(m, r.status_code, "keys=", list(msg.keys()), "| content=", str(msg.get("content"))[:70])
    except Exception as e:
        print(m, "ERR", type(e).__name__, str(e)[:100])
    time.sleep(46)
