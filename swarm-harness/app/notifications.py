# app/notifications.py
import aiohttp
from typing import Dict
from app.models import SwarmBuild
from app.config import CONFIG

class NotificationDispatcher:
    async def notify(self, build: SwarmBuild, message: str, urgency: str = "normal"):
        payload = {
            "build_id": build.id,
            "state": build.state.value,
            "message": message,
            "urgency": urgency,
            "needs_human": build.state.value == "waiting_human",
            "token_usage": build.token_usage,
            "budget_remaining": build.token_budget_total - build.token_usage,
            "final_output": build.final_output[:500] if build.final_output else None
        }

        # Webhook
        if CONFIG.NOTIFICATION_WEBHOOK:
            await self._webhook(payload)

        # Slack
        slack_url = build.metadata.get("slack_webhook")
        if slack_url:
            await self._slack(slack_url, payload)

    async def _webhook(self, payload: Dict):
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(CONFIG.NOTIFICATION_WEBHOOK, json=payload, timeout=aiohttp.ClientTimeout(total=10))
        except Exception as e:
            print(f"Webhook failed: {e}")

    async def _slack(self, url: str, payload: Dict):
        emoji = "🛑" if payload["needs_human"] else "✅" if payload["state"] == "completed" else "❌"
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(url, json={
                    "text": f"{emoji} *Swarm Build {payload['build_id']}*\n"
                            f"Status: `{payload['state']}`\n"
                            f"Tokens: {payload['token_usage']}/{payload['token_usage'] + payload['budget_remaining']}\n"
                            f"{payload['message']}"
                }, timeout=aiohttp.ClientTimeout(total=10))
        except Exception as e:
            print(f"Slack failed: {e}")
