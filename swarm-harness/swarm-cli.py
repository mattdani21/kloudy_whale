#!/usr/bin/env python3
# swarm-cli.py
import os
import sys
import time
import requests

BASE = os.getenv("SWARM_API_URL", "http://localhost:8000")
API_KEY = os.getenv("API_KEY", "dev-key-change-me")

def submit(prompt: str):
    r = requests.post(
        f"{BASE}/v1/build",
        headers={"X-API-Key": API_KEY},
        json={
            "prompt": prompt,
            "agents": [
                {"role": "planner", "provider": "deepseek", "model": "deepseek-v4-flash"},
                {"role": "coder", "provider": "kimi", "model": "kimi-k3"},
                {"role": "reviewer", "provider": "deepseek", "model": "deepseek-v4-flash"},
                {"role": "merger", "provider": "kimi", "model": "kimi-k3"}
            ],
            "token_budget": 4000000,
        }
    )
    r.raise_for_status()
    data = r.json()
    print(f"🚀 Build {data['build_id']} started")

    while True:
        status = requests.get(f"{BASE}/v1/build/{data['build_id']}", headers={"X-API-Key": API_KEY}).json()

        if status["needs_human"]:
            print(f"\n🛑 {status['human_question']}")
            resp = input("> ")
            requests.post(
                f"{BASE}/v1/build/{data['build_id']}/respond",
                headers={"X-API-Key": API_KEY},
                json={"response": resp}
            )
            print("▶️ Resuming...")
        elif status["state"] == "completed":
            print(f"\n✅ DONE\n{status['final_output']}")
            break
        elif status["state"] in ("failed", "cancelled"):
            print(f"\n❌ {status['state'].upper()}\n{status['errors']}")
            break

        time.sleep(3)

if __name__ == "__main__":
    submit(sys.argv[1])
