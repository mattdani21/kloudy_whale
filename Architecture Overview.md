**Architecture Overview**  
**plain**  
  
  
```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   You (Client)  │────▶│  Cloud Orchestrator │◀──│  Notification   │
│  (Start/Check)  │◀────│  (Persistent Worker)  │──▶│  (Email/Slack/  │
└─────────────────┘     └──────────────────┘     │  Push/Webhook)    │
                          │  │  │                └─────────────────┘
                          ▼  ▼  ▼
                    ┌─────────┐ ┌─────────┐
                    │DeepSeek │ │  Kimi   │
                    │  API    │ │  API    │
                    └─────────┘ └─────────┘

```
  
  
**1. Cloud Infrastructure Options**  
**Table**  
  
  
  

| Platform | Best For | Cost | Persistence |
| ------------------------------ | --------------------------------- | ----------- | ----------- |
| Railway/Render | Quick deploy, managed | $5-20/mo | Good |
| AWS Lambda + EventBridge | Serverless, scale to zero | Pay per use | Excellent |
| Google Cloud Run + Cloud Tasks | Container-based, cron | $10-30/mo | Excellent |
| Hetzner/DigitalOcean VPS | Full control, cheapest | $5-10/mo | Perfect |
| Fly.io | Edge-deployed, persistent volumes | $2-5/mo | Good |
  
****Recommendation: Start with Railway or Render for zero-config deployment, then migrate to AWS/GCP if you need enterprise reliability.****  
  
**2. Core Orchestrator (Python)**  
**Here's the engine that runs your agent loops:**  
**Python**  
  
  
```
# orchestrator.py
import os
import
```
```
 json

```
```
import
```
```
 time

```
```
import
```
```
 asyncio

```
```
import
```
```
 hashlib

```
```
from
```
```
 datetime import datetime

```
```
from
```
```
 enum import Enum

```
```
from typing import Optional, Dict, List, Callable
from
```
```
 dataclasses import dataclass, asdict

```
```
import
```
```
 aiohttp

```
```
import
```
```
 redis  # or SQLite for persistence

```
```

class
```
```
 AgentState(Enum):

```
```
    IDLE = "idle"
    RUNNING = "running"
    WAITING_HUMAN = "waiting_human"
    COMPLETED = "completed"
    FAILED 
```
```
= "failed"

```
```

@dataclass
```
```


```
```
class
```
```
 BuildTask:

```
```
    
```
```
id: str

```
```
    prompt: str
    model_preference
```
```
: str  # "deepseek" | "kimi" | "hybrid"

```
```
    state
```
```
: AgentState

```
```
    created_at: str
    updated_at
```
```
: str

```
```
    context: Dict = None
    result
```
```
: Optional[str] = None

```
```
    human_input_request
```
```
: Optional[str] = None

```
```
    
    def __post_init__(self):
        if self.context is None:
            self
```
```
.context = {}

```
```

class
```
```
 AgentOrchestrator:

```
```
    def __init__(self):
        self
```
```
.deepseek_key = os.getenv("DEEPSEEK_API_KEY")

```
```
        self.kimi_key = os.getenv("KIMI_API_KEY")
        self
```
```
.redis_client = redis.Redis(

```
```
            host
```
```
=os.getenv("REDIS_HOST", "localhost"),

```
```
            port
```
```
=int(os.getenv("REDIS_PORT", 6379)),

```
```
            decode_responses=True
        
```
```
)

```
```
        self
```
```
.notification_callbacks: List[Callable] = []

```
```
        
    
```
```
def on_notification(self, callback: Callable):

```
```
        
```
```
"""Register notification handler (Slack, email, push, etc.)"""

```
```
        self
```
```
.notification_callbacks.append(callback)

```
```
    
    async def _notify(self, task: BuildTask, message: str, urgency: str = "normal"):
        
```
```
"""Fire all notification channels"""

```
```
        payload = {
            
```
```
"task_id": task.id,

```
```
            
```
```
"state": task.state.value,

```
```
            
```
```
"message": message,

```
```
            
```
```
"urgency": urgency,

```
```
            
```
```
"timestamp": datetime.utcnow().isoformat(),

```
```
            "human_input_needed": task.state == AgentState.WAITING_HUMAN,
            "result_preview": task.result[:500] if task.result else None
        
```
```
}

```
```
        for cb in self.notification_callbacks:
            try:
                await cb(payload)
            except Exception as e:
                print(f"Notification failed: {e}")
    
    async def _call_deepseek(self, messages: List[Dict], model: str = "deepseek-chat") -> str:
        
```
```
async with aiohttp.ClientSession() as session:

```
```
            
```
```
async with session.post(

```
```
                "https://api.deepseek.com/v1/chat/completions",
                headers
```
```
={"Authorization": f"Bearer {self.deepseek_key}"},

```
```
                json
```
```
={

```
```
                    "model": model,
                    "messages": messages,
                    "temperature": 0.7,
                    "max_tokens": 4000
                
```
```
}

```
```
            ) as resp:
                data 
```
```
= await resp.json()

```
```
                
```
```
return data["choices"][0]["message"]["content"]

```
```
    
    
```
```
async def _call_kimi(self, messages: List[Dict], model: str = "kimi-k3") -> str:

```
```
        
```
```
async with aiohttp.ClientSession() as session:

```
```
            async with session.post(
                
```
```
"https://api.moonshot.cn/v1/chat/completions",

```
```
                headers
```
```
={"Authorization": f"Bearer {self.kimi_key}"},

```
```
                json={
                    "model": model,
                    "messages": messages,
                    
```
```
"temperature": 0.7,

```
```
                    "max_tokens": 4000
                
```
```
}

```
```
            ) as resp:
                data 
```
```
= await resp.json()

```
```
                
```
```
return data["choices"][0]["message"]["content"]

```
```
    
    
```
```
async def _call_llm(self, messages: List[Dict], preference: str) -> str:

```
```
        
```
```
"""Route to preferred API with fallback"""

```
```
        if preference == "kimi" or preference == "hybrid":
            try:
                
```
```
return await self._call_kimi(messages)

```
```
            
```
```
except Exception as e:

```
```
                
```
```
if preference == "kimi":

```
```
                    
```
```
raise e

```
```
                # Fallback to deepseek
        
```
```
return await self._call_deepseek(messages)

```
```
    
    
```
```
async def _save_task(self, task: BuildTask):

```
```
        self
```
```
.redis_client.setex(

```
```
            f"task:{task.id}",
            
```
```
86400 * 7,  # 7 day TTL

```
```
            json
```
```
.dumps(asdict(task), default=str)

```
```
        )
    
    async def _load_task(self, task_id: str) -> Optional[BuildTask]:
        data = self.redis_client.get(f"task:{task_id}")
        if data:
            d = json.loads(data)
            d
```
```
["state"] = AgentState(d["state"])

```
```
            return BuildTask(**d)
        return None
    
    
```
```
async def run_build_loop(self, task: BuildTask):

```
```
        """The core autonomous loop"""
        task
```
```
.state = AgentState.RUNNING

```
```
        
```
```
await self._save_task(task)

```
```
        
        
```
```
try:

```
```
            
```
```
# Phase 1: Planning

```
```
            plan_prompt = [
                
```
```
{"role": "system", "content": "You are a build planner. Break the user's request into executable steps."},

```
```
                
```
```
{"role": "user", "content": f"Create a step-by-step plan for: {task.prompt}"}

```
```
            
```
```
]

```
```
            plan 
```
```
= await self._call_llm(plan_prompt, task.model_preference)

```
```
            task
```
```
.context["plan"] = plan

```
```
            
            
```
```
# Phase 2: Execute steps (simplified - you'd iterate through plan)

```
```
            
```
```
for step_num, step in enumerate(plan.split("\n")[:5]):  # Limit steps

```
```
                
```
```
# Check if human input needed

```
```
                
```
```
if "[HUMAN_INPUT]" in step:

```
```
                    task
```
```
.state = AgentState.WAITING_HUMAN

```
```
                    task
```
```
.human_input_request = step.replace("[HUMAN_INPUT]", "").strip()

```
```
                    
```
```
await self._save_task(task)

```
```
                    await self._notify(
                        task, 
                        
```
```
f"🛑 Build paused. Input needed: {task.human_input_request}",

```
```
                        urgency="high"
                    
```
```
)

```
```
                    
```
```
return  # Loop stops here, resumes when human responds

```
```
                
                # Execute step
                step_prompt = [
                    
```
```
{"role": "system", "content": "You are a build executor. Write code or perform the requested action."},

```
```
                    {"role": "user", "content": f"Execute this step: {step}\n\nContext: {json.dumps(task.context)}"}
                
```
```
]

```
```
                result = await self._call_llm(step_prompt, task.model_preference)
                task
```
```
.context[f"step_{step_num}_result"] = result

```
```
                
                
```
```
# Optional: Self-review with other model (hybrid mode)

```
```
                if task.model_preference == "hybrid":
                    review = await self._call_deepseek([
                        {"role": "system", "content": "Review this output for correctness and completeness."},
                        
```
```
{"role": "user", "content": result}

```
```
                    
```
```
])

```
```
                    task.context[f"step_{step_num}_review"] = review
            
            
```
```
# Phase 3: Final assembly

```
```
            final_prompt 
```
```
= [

```
```
                
```
```
{"role": "system", "content": "Assemble all step outputs into a final deliverable."},

```
```
                
```
```
{"role": "user", "content": f"Context: {json.dumps(task.context)}\nOriginal request: {task.prompt}"}

```
```
            
```
```
]

```
```
            task
```
```
.result = await self._call_llm(final_prompt, task.model_preference)

```
```
            task
```
```
.state = AgentState.COMPLETED

```
```
            
            await self._notify(
                task
```
```
,

```
```
                f"✅ Build complete! Preview:\n{task.result[:300]}...",
                urgency="normal"
            )
            
        except Exception as e:
            task.state = AgentState.FAILED
            task
```
```
.result = str(e)

```
```
            await self._notify(task, f"❌ Build failed: {e}", urgency="high")
        
        finally:
            task
```
```
.updated_at = datetime.utcnow().isoformat()

```
```
            
```
```
await self._save_task(task)

```
```
    
    async def submit_human_input(self, task_id: str, human_response: str):
        """Resume a paused build"""
        task = await self._load_task(task_id)
        if not task or task.state != AgentState.WAITING_HUMAN:
            raise ValueError("Task not found or not waiting for input")
        
        task.context["human_input"] = human_response
        task.state = AgentState.RUNNING
        
```
```
await self._save_task(task)

```
```
        
        # Continue the loop
        asyncio
```
```
.create_task(self.run_build_loop(task))

```
```
        
```
```
return {"status": "resumed", "task_id": task_id}

```
```
    
    async def start_build(self, prompt: str, model_preference: str = "hybrid") -> str:
        
```
```
"""Entry point: kick off a new build"""

```
```
        task_id 
```
```
= hashlib.sha256(f"{prompt}{time.time()}".encode()).hexdigest()[:16]

```
```
        task = BuildTask(
            id=task_id,
            prompt
```
```
=prompt,

```
```
            model_preference
```
```
=model_preference,

```
```
            state=AgentState.IDLE,
            created_at=datetime.utcnow().isoformat(),
            updated_at
```
```
=datetime.utcnow().isoformat()

```
```
        
```
```
)

```
```
        
        await self._save_task(task)
        
```
```
# Fire and forget - runs in background

```
```
        asyncio.create_task(self.run_build_loop(task))
        
        return task_id

```
  
  
**3. Notification Channels**  
**Python**  
  
  
```
# notifications.py
import aiohttp

async
```
```
 def slack_notifier(payload: dict):

```
```
    webhook_url 
```
```
= os.getenv("SLACK_WEBHOOK_URL")

```
```
    emoji 
```
```
= "🛑" if payload["human_input_needed"] else "✅" if payload["state"] == "completed" else "❌"

```
```
    async with aiohttp.ClientSession() as session:
        
```
```
await session.post(webhook_url, json={

```
```
            "text": f"{emoji} *Build Notification*\n"
                    f"Task: `{payload['task_id']}`\n"
                    f"Status: {payload['state']}\n"
                    
```
```
f"{payload['message']}"

```
```
        })

async def email_notifier(payload: dict):
    
```
```
# Use SendGrid/Resend/AWS SES

```
```
    import resend
    resend
```
```
.api_key = os.getenv("RESEND_API_KEY")

```
```
    resend
```
```
.Emails.send({

```
```
        "from": "builds@yourdomain.com",
        "to": "you@email.com",
        "subject": f"Build {payload['task_id']}: {payload['state']}",
        
```
```
"html": f"<pre>{payload['message']}</pre>"

```
```
    
```
```
})

```
```

async
```
```
 def pushover_notifier(payload: dict):

```
```
    
```
```
# Pushover for mobile push

```
```
    
```
```
async with aiohttp.ClientSession() as session:

```
```
        
```
```
await session.post("https://api.pushover.net/1/messages.json", data={

```
```
            
```
```
"token": os.getenv("PUSHOVER_TOKEN"),

```
```
            
```
```
"user": os.getenv("PUSHOVER_USER"),

```
```
            "title": f"Build {payload['state']}",
            
```
```
"message": payload["message"],

```
```
            
```
```
"priority": 2 if payload["human_input_needed"] else 0

```
```
        
```
```
})

```
  
  
**4. REST API (FastAPI for Cloud Deploy)**  
**Python**  
  
  
```
# api.py
from
```
```
 fastapi import FastAPI, BackgroundTasks

```
```
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()
orchestrator = AgentOrchestrator()

# Register notifiers
```
```


```
```
orchestrator.on_notification(slack_notifier)
orchestrator.on_notification(pushover_notifier)

@app.post(
```
```
"/build")

```
```
async def start_build(request: dict, background_tasks: BackgroundTasks):
    task_id 
```
```
= await orchestrator.start_build(

```
```
        prompt
```
```
=request["prompt"],

```
```
        model_preference=request.get("model", "hybrid")
    
```
```
)

```
```
    
```
```
return {

```
```
        
```
```
"task_id": task_id,

```
```
        
```
```
"status": "started",

```
```
        
```
```
"check_url": f"/build/{task_id}/status",

```
```
        
```
```
"web_ui": f"/build/{task_id}"  # If you add a UI

```
```
    
```
```
}

```
```

@app.get("/build/{task_id}/status")
async
```
```
 def get_status(task_id: str):

```
```
    task 
```
```
= await orchestrator._load_task(task_id)

```
```
    
```
```
if not task:

```
```
        return {"error": "Not found"}
    return {
        
```
```
"state": task.state.value,

```
```
        
```
```
"human_input_needed": task.state == AgentState.WAITING_HUMAN,

```
```
        "human_input_question": task.human_input_request,
        
```
```
"result": task.result if task.state == AgentState.COMPLETED else None,

```
```
        "context": task.context
    }

@app.post("/build/{task_id}/respond")
async def human_response(task_id: str, response: dict):
    
```
```
"""Submit human input to resume a paused build"""

```
```
    
```
```
return await orchestrator.submit_human_input(task_id, response["input"])

```
```

@app.get(
```
```
"/builds")

```
```
async
```
```
 def list_builds():

```
```
    keys 
```
```
= orchestrator.redis_client.keys("task:*")

```
```
    tasks = []
    for key in keys:
        data 
```
```
= json.loads(orchestrator.redis_client.get(key))

```
```
        tasks
```
```
.append({

```
```
            
```
```
"id": data["id"],

```
```
            
```
```
"state": data["state"],

```
```
            "prompt": data["prompt"][:50] + "...",
            
```
```
"created_at": data["created_at"]

```
```
        })
    return sorted(tasks, key=lambda x: x["created_at"], reverse=True)

```
  
  
**5. Deployment (Railway - Easiest)**  
**Dockerfile:**  
**dockerfile**  
  
  
```
FROM python:3.11-slim
WORKDIR /app
COPY
```
```
 requirements.txt .

```
```
RUN
```
```
 pip install -r requirements.txt

```
```
COPY
```
```
 . .

```
```
CMD
```
```
 ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8080"]

```
  
**requirements.txt:**  
**plain**  
  
  
```
fastapi
uvicorn
aiohttp
redis
python-dotenv

```
  
**Environment Variables to Set:**  
**plain**  
  
  
```
DEEPSEEK_API_KEY=sk-...
KIMI_API_KEY=sk-...
REDIS_HOST=your-redis-host
SLACK_WEBHOOK_URL=https://hooks.slack.com/...
PUSHOVER_TOKEN=...
PUSHOVER_USER=...

```
  
  
**6. Client Usage (How You Interact)**  
**Start a build (curl):**  
**bash**  
  
  
```
curl -X POST https://your-app.railway.app/build \
  
```
```
-H "Content-Type: application/json" \

```
```
  
```
```
-d '{"prompt": "Build a Python script that scrapes Hacker News and emails me top stories daily", "model": "hybrid"}'

```
```
# Returns: {"task_id": "a3f7b2...", "status": "started"}
```
```


```
```

# Check status:
```
```


```
```
curl
```
```
 https://your-app.railway.app/build/a3f7b2.../status

```
```

# If waiting for human input, respond:
curl
```
```
 -X POST https://your-app.railway.app/build/a3f7b2.../respond \

```
```
  -H "Content-Type: application/json" \
  
```
```
-d '{"input": "Use BeautifulSoup instead of Selenium"}'

```
  
**Or use a simple CLI wrapper:**  
**Python**  
  
  
```
# cli.py
import requests
import
```
```
 time

```
```
import sys

BASE 
```
```
= "https://your-app.railway.app"

```
```

def start_and_wait(prompt: str):
    r 
```
```
= requests.post(f"{BASE}/build", json={"prompt": prompt, "model": "hybrid"})

```
```
    task_id 
```
```
= r.json()["task_id"]

```
```
    
```
```
print(f"🚀 Build started: {task_id}")

```
```
    
    
```
```
while True:

```
```
        status = requests.get(f"{BASE}/build/{task_id}/status").json()
        
        if status["state"] == "waiting_human":
            
```
```
print(f"\n🛑 INPUT NEEDED: {status['human_input_question']}")

```
```
            answer 
```
```
= input("Your response: ")

```
```
            requests
```
```
.post(f"{BASE}/build/{task_id}/respond", json={"input": answer})

```
```
            
```
```
print("▶️ Resuming...")

```
```
            
        elif status["state"] == "completed":
            
```
```
print(f"\n✅ DONE:\n{status['result']}")

```
```
            break
            
        
```
```
elif status["state"] == "failed":

```
```
            print(f"\n❌ FAILED: {status['result']}")
            
```
```
break

```
```
            
        time
```
```
.sleep(5)

```
```

if
```
```
 __name__ == "__main__":

```
```
    start_and_wait(sys.argv[1])

```
  
  
**7. Advanced: Multi-Agent Swarm**  
**If you want multiple agents working in parallel:**  
**Python**  
  
  
```
async def run_swarm(self, master_prompt: str):
    
```
```
# Decompose into sub-tasks

```
```
    decomposition 
```
```
= await self._call_llm([

```
```
        {"role": "system", "content": "Decompose this into 3-5 independent sub-tasks that can run in parallel."},
        {"role": "user", "content": master_prompt}
    
```
```
])

```
```
    
    sub_tasks = [line for line in decomposition.split("\n") if line.strip()]
    
    # Launch all in parallel
    task_ids = await asyncio.gather(*[
        self.start_build(sub, "hybrid") for sub in sub_tasks
    
```
```
])

```
```
    
    # Wait for all, then synthesize
    
```
```
# ... (poll status, merge results)

```
  
  
**8. Cost Optimization**  
**Table**  
  
  
  

| Strategy                                              | Savings          |
| ----------------------------------------------------- | ---------------- |
| Use DeepSeek-V3 for planning, Kimi-K3 for execution   | ~40%             |
| Cache common prompts in Redis                         | ~20%             |
| Limit max_tokens per step (2000-4000)                 | Prevents runaway |
| Add a token budget per build (e.g., 50K tokens max)   | Hard cap         |
| Use DeepSeek-R1 only for reasoning steps, V3 for code | ~60%             |
  
**Quick-Start Checklist**  
1. **Get API keys**: [DeepSeek](https://platform.deepseek.com/) + [Kimi/Moonshot](https://platform.moonshot.cn/)  
2. **Spin up Redis**: Railway has a one-click Redis add-on, or use [Upstash](https://upstash.com/) (free tier)  
3. **Deploy the API**: Push the code above to Railway/Render  
4. **Set notifications**: Configure Slack webhook or Pushover for mobile  
5. **Test**: curl a build, verify you get a push notification when it completes or needs you  
**Want me to generate the full repo structure with all files ready to deploy, or set up a specific notification channel (e.g., Telegram bot instead of Slack)?**  
  
  
  
  
  
**Agent harness for the build? Also any value in swapping python for another language in terms of speed?**  
##   
Edit  
##   
Copy  
##   
Share  
  
  
Choosing Python async or Go for high‑throughput API latency  
  
  
1.   
2.   
  
1.   
    *   
    *   
    *   
    *   
    *   
    *   
    *   
2.   
    *   
    *   
    *   
    *   
    *   
    *   
    *   
    *   
  
## Great questions. Let me address both: a production-grade agent harness, and whether Python is actually the bottleneck here.  
  
**1. Agent Harness (Production-Ready)**  
**Here's a robust harness with state machine, retry logic, circuit breakers, tool-use, and checkpointing:**  
**Python**  
  
  
```
# harness.py
import os
import json
import
```
```
 asyncio

```
```
import
```
```
 logging

```
```
from datetime import datetime, timedelta
from
```
```
 enum import Enum, auto

```
```
from
```
```
 typing import Dict, List, Optional, Callable, Any

```
```
from dataclasses import dataclass, field, asdict
from functools import wraps
import
```
```
 hashlib

```
```
import aiohttp
import redis.asyncio as redis
from
```
```
 tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

```
```

# ─── Configuration ──────────────────────────────────────────────
```
```


```
```
class Config:
    DEEPSEEK_KEY 
```
```
= os.getenv("DEEPSEEK_API_KEY")

```
```
    KIMI_KEY 
```
```
= os.getenv("KIMI_API_KEY")

```
```
    REDIS_URL 
```
```
= os.getenv("REDIS_URL", "redis://localhost:6379")

```
```
    MAX_STEPS = 25
    TOKEN_BUDGET 
```
```
= 50000

```
```
    RETRY_ATTEMPTS 
```
```
= 3

```
```
    CIRCUIT_BREAKER_THRESHOLD 
```
```
= 5

```
```
    CIRCUIT_BREAKER_TIMEOUT 
```
```
= 60  # seconds

```
```

# ─── State Machine ────────────────────────────────────────────────
class State(Enum):
    QUEUED 
```
```
= auto()

```
```
    PLANNING = auto()
    EXECUTING = auto()
    REVIEWING = auto()
    WAITING_HUMAN = auto()
    PAUSED = auto()
    COMPLETED 
```
```
= auto()

```
```
    FAILED = auto()
    CANCELLED 
```
```
= auto()

```
```

class StepType(Enum):
    PLAN = "plan"
    CODE = "code"
    REVIEW 
```
```
= "review"

```
```
    TOOL = "tool"
    HUMAN = "human"
    MERGE 
```
```
= "merge"

```
```

# ─── Data Models ───────────────────────────────────────────────────
@dataclass
```
```


```
```
class
```
```
 Step:

```
```
    id: str
    type: StepType
    prompt: str
    model
```
```
: str  # "deepseek" | "kimi"

```
```
    result
```
```
: Optional[str] = None

```
```
    tokens_used: int = 0
    duration_ms
```
```
: float = 0.0

```
```
    error
```
```
: Optional[str] = None

```
```
    retry_count: int = 0
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    completed_at
```
```
: Optional[str] = None

```
```

@dataclass
class
```
```
 Build:

```
```
    id: str
    prompt: str
    strategy: str  # "deepseek" | "kimi" | "hybrid" | "swarm"
    state: State
    steps
```
```
: List[Step] = field(default_factory=list)

```
```
    context: Dict = field(default_factory=dict)
    token_usage
```
```
: int = 0

```
```
    human_input_queue
```
```
: List[str] = field(default_factory=list)

```
```
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    error_log
```
```
: List[str] = field(default_factory=list)

```
```
    metadata: Dict = field(default_factory=dict)

# ─── Circuit Breaker ───────────────────────────────────────────────
```
```


```
```
class CircuitBreaker:
    
```
```
def __init__(self, name: str, threshold: int = Config.CIRCUIT_BREAKER_THRESHOLD, 

```
```
                 timeout: int = Config.CIRCUIT_BREAKER_TIMEOUT):
        self.name = name
        self.threshold = threshold
        self
```
```
.timeout = timeout

```
```
        self.failures = 0
        self.last_failure = None
        self
```
```
.state = "closed"  # closed, open, half-open

```
```
    
    
```
```
def call(self, func):

```
```
        @wraps(func)
        async def wrapper(*args, **kwargs):
            
```
```
if self.state == "open":

```
```
                
```
```
if self.last_failure and (datetime.now() - self.last_failure).seconds > self.timeout:

```
```
                    self
```
```
.state = "half-open"

```
```
                
```
```
else:

```
```
                    raise Exception(f"Circuit breaker OPEN for {self.name}")
            
            try:
                result 
```
```
= await func(*args, **kwargs)

```
```
                
```
```
if self.state == "half-open":

```
```
                    self
```
```
.state = "closed"

```
```
                    self
```
```
.failures = 0

```
```
                
```
```
return result

```
```
            
```
```
except Exception as e:

```
```
                self
```
```
.failures += 1

```
```
                self.last_failure = datetime.now()
                
```
```
if self.failures >= self.threshold:

```
```
                    self.state = "open"
                
```
```
raise e

```
```
        
```
```
return wrapper

```
```

# ─── Tool Registry ─────────────────────────────────────────────────
class ToolRegistry:
    
```
```
def __init__(self):

```
```
        self
```
```
.tools: Dict[str, Callable] = {}

```
```
    
    def register(self, name: str, func: Callable):
        self.tools[name] = func
    
    async def execute(self, name: str, params: Dict) -> str:
        if name not in self.tools:
            
```
```
return f"Error: Tool '{name}' not found"

```
```
        
```
```
try:

```
```
            result = await self.tools[name](**params) if asyncio.iscoroutinefunction(self.tools[name]) else self.tools[name](**params)
            return str(result)
        except Exception as e:
            return f"Tool error: {str(e)}"

# ─── LLM Router ────────────────────────────────────────────────────
```
```


```
```
class LLMRouter:
    
```
```
def __init__(self):

```
```
        self
```
```
.deepseek_cb = CircuitBreaker("deepseek")

```
```
        self
```
```
.kimi_cb = CircuitBreaker("kimi")

```
```
        self
```
```
.session: Optional[aiohttp.ClientSession] = None

```
```
    
    
```
```
async def __aenter__(self):

```
```
        self.session = aiohttp.ClientSession()
        
```
```
return self

```
```
    
    
```
```
async def __aexit__(self, *args):

```
```
        await self.session.close()
    
    @retry(
        stop
```
```
=stop_after_attempt(Config.RETRY_ATTEMPTS),

```
```
        wait
```
```
=wait_exponential(multiplier=1, min=2, max=10),

```
```
        retry
```
```
=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError))

```
```
    
```
```
)

```
```
    async def _call_deepseek(self, messages: List[Dict], model: str = "deepseek-chat", max_tokens: int = 4000) -> tuple:
        payload 
```
```
= {

```
```
            "model": model,
            
```
```
"messages": messages,

```
```
            
```
```
"temperature": 0.7,

```
```
            
```
```
"max_tokens": max_tokens,

```
```
            
```
```
"stream": False

```
```
        
```
```
}

```
```
        
```
```
async with self.session.post(

```
```
            
```
```
"https://api.deepseek.com/v1/chat/completions",

```
```
            headers={"Authorization": f"Bearer {Config.DEEPSEEK_KEY}", "Content-Type": "application/json"},
            json
```
```
=payload,

```
```
            timeout=aiohttp.ClientTimeout(total=120)
        
```
```
) as resp:

```
```
            resp.raise_for_status()
            data 
```
```
= await resp.json()

```
```
            content = data["choices"][0]["message"]["content"]
            tokens 
```
```
= data.get("usage", {}).get("total_tokens", 0)

```
```
            return content, tokens
    
    @retry(
        stop
```
```
=stop_after_attempt(Config.RETRY_ATTEMPTS),

```
```
        wait
```
```
=wait_exponential(multiplier=1, min=2, max=10),

```
```
        retry
```
```
=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError))

```
```
    )
    
```
```
async def _call_kimi(self, messages: List[Dict], model: str = "kimi-k3", max_tokens: int = 4000) -> tuple:

```
```
        payload 
```
```
= {

```
```
            
```
```
"model": model,

```
```
            "messages": messages,
            
```
```
"temperature": 0.7,

```
```
            "max_tokens": max_tokens,
            
```
```
"stream": False

```
```
        }
        
```
```
async with self.session.post(

```
```
            
```
```
"https://api.moonshot.cn/v1/chat/completions",

```
```
            headers={"Authorization": f"Bearer {Config.KIMI_KEY}", "Content-Type": "application/json"},
            json
```
```
=payload,

```
```
            timeout
```
```
=aiohttp.ClientTimeout(total=120)

```
```
        ) as resp:
            resp
```
```
.raise_for_status()

```
```
            data 
```
```
= await resp.json()

```
```
            content = data["choices"][0]["message"]["content"]
            tokens = data.get("usage", {}).get("total_tokens", 0)
            
```
```
return content, tokens

```
```
    
    async def call(self, messages: List[Dict], preference: str = "hybrid", max_tokens: int = 4000) -> tuple:
        if preference == "kimi":
            wrapped = self.kimi_cb.call(self._call_kimi)
            
```
```
return await wrapped(messages, max_tokens=max_tokens)

```
```
        elif preference == "deepseek":
            wrapped 
```
```
= self.deepseek_cb.call(self._call_deepseek)

```
```
            
```
```
return await wrapped(messages, max_tokens=max_tokens)

```
```
        
```
```
else:  # hybrid - try kimi first, fallback to deepseek

```
```
            
```
```
try:

```
```
                wrapped 
```
```
= self.kimi_cb.call(self._call_kimi)

```
```
                return await wrapped(messages, max_tokens=max_tokens)
            
```
```
except Exception as e:

```
```
                logging
```
```
.warning(f"Kimi failed ({e}), falling back to DeepSeek")

```
```
                wrapped 
```
```
= self.deepseek_cb.call(self._call_deepseek)

```
```
                
```
```
return await wrapped(messages, max_tokens=max_tokens)

```
```

# ─── Agent Harness (The Core) ─────────────────────────────────────
```
```


```
```
class
```
```
 AgentHarness:

```
```
    def __init__(self):
        self.redis = redis.from_url(Config.REDIS_URL, decode_responses=True)
        self
```
```
.router = LLMRouter()

```
```
        self.tools = ToolRegistry()
        self.notifiers: List[Callable] = []
        self._register_default_tools()
    
    def _register_default_tools(self):
        # Register some default tools the agent can use
        self.tools.register("write_file", self._tool_write_file)
        self
```
```
.tools.register("read_file", self._tool_read_file)

```
```
        self
```
```
.tools.register("execute_python", self._tool_execute_python)

```
```
        self.tools.register("web_search", self._tool_web_search)
    
    
```
```
async def _tool_write_file(self, path: str, content: str) -> str:

```
```
        # In real deploy, use S3 or volume
        return f"Wrote {len(content)} chars to {path}"
    
    
```
```
async def _tool_read_file(self, path: str) -> str:

```
```
        return f"Contents of {path}: [placeholder]"
    
    
```
```
async def _tool_execute_python(self, code: str) -> str:

```
```
        # Use restricted exec or Docker
        return f"Executed Python code: {code[:50]}..."
    
    async def _tool_web_search(self, query: str) -> str:
        # Integrate with search API
        
```
```
return f"Search results for: {query}"

```
```
    
    
```
```
def on_notify(self, callback: Callable):

```
```
        self
```
```
.notifiers.append(callback)

```
```
    
    async def _notify(self, build: Build, message: str, urgency: str = "normal"):
        payload 
```
```
= {

```
```
            
```
```
"build_id": build.id,

```
```
            "state": build.state.name,
            "message": message,
            
```
```
"urgency": urgency,

```
```
            "timestamp": datetime.utcnow().isoformat(),
            
```
```
"needs_human": build.state == State.WAITING_HUMAN,

```
```
            
```
```
"token_usage": build.token_usage,

```
```
            "step_count": len(build.steps)
        
```
```
}

```
```
        
```
```
for cb in self.notifiers:

```
```
            
```
```
try:

```
```
                if asyncio.iscoroutinefunction(cb):
                    
```
```
await cb(payload)

```
```
                else:
                    cb
```
```
(payload)

```
```
            except Exception as e:
                logging
```
```
.error(f"Notifier failed: {e}")

```
```
    
    async def _persist(self, build: Build):
        
```
```
await self.redis.setex(

```
```
            f"build:{build.id}",
            timedelta
```
```
(days=7),

```
```
            json
```
```
.dumps(asdict(build), default=lambda x: x.name if isinstance(x, Enum) else str(x))

```
```
        
```
```
)

```
```
    
    
```
```
async def _load(self, build_id: str) -> Optional[Build]:

```
```
        data 
```
```
= await self.redis.get(f"build:{build_id}")

```
```
        if not data:
            
```
```
return None

```
```
        d = json.loads(data)
        d["state"] = State[d["state"]]
        d
```
```
["steps"] = [Step(**s) for s in d.get("steps", [])]

```
```
        return Build(**d)
    
    
```
```
async def _run_step(self, build: Build, step: Step) -> bool:

```
```
        
```
```
"""Execute a single step. Returns True if successful."""

```
```
        start = datetime.now()
        
        
```
```
try:

```
```
            
```
```
if step.type == StepType.TOOL:

```
```
                
```
```
# Parse tool call from prompt

```
```
                tool_call = json.loads(step.prompt)
                step
```
```
.result = await self.tools.execute(tool_call["name"], tool_call.get("params", {}))

```
```
                step
```
```
.tokens_used = 0

```
```
            
```
```
else:

```
```
                messages 
```
```
= [

```
```
                    {"role": "system", "content": self._get_system_prompt(step.type)},
                    
```
```
{"role": "user", "content": step.prompt}

```
```
                ]
                content, tokens = await self.router.call(messages, step.model)
                step
```
```
.result = content

```
```
                step.tokens_used = tokens
                build.token_usage += tokens
                
                # Check for tool invocation in response
                if "<tool>" in content:
                    
```
```
# Extract and queue tool step

```
```
                    tool_json 
```
```
= self._extract_tool_tag(content)

```
```
                    tool_step 
```
```
= Step(

```
```
                        
```
```
id=f"{build.id}_tool_{len(build.steps)}",

```
```
                        type=StepType.TOOL,
                        prompt=json.dumps(tool_json),
                        model
```
```
=step.model

```
```
                    )
                    build.steps.append(tool_step)
                    
```
```
return await self._run_step(build, tool_step)

```
```
            
            step
```
```
.completed_at = datetime.utcnow().isoformat()

```
```
            step.duration_ms = (datetime.now() - start).total_seconds() * 1000
            return True
            
        
```
```
except Exception as e:

```
```
            step
```
```
.error = str(e)

```
```
            step.retry_count += 1
            build.error_log.append(f"[{datetime.utcnow().isoformat()}] Step {step.id}: {e}")
            
```
```
if step.retry_count < 2:

```
```
                
```
```
# Retry this step

```
```
                
```
```
return await self._run_step(build, step)

```
```
            
```
```
return False

```
```
    
    
```
```
def _get_system_prompt(self, step_type: StepType) -> str:

```
```
        prompts = {
            StepType.PLAN: "You are a senior architect. Break down the request into executable steps. Output JSON array of steps.",
            StepType
```
```
.CODE: "You are a senior developer. Write clean, production-ready code. Include error handling.",

```
```
            StepType
```
```
.REVIEW: "You are a code reviewer. Check for bugs, security issues, and improvements. Be concise.",

```
```
            StepType.MERGE: "You are a tech lead. Combine all outputs into a final deliverable with documentation.",
            StepType.HUMAN: "You are asking the user a specific clarifying question. Be direct."
        
```
```
}

```
```
        
```
```
return prompts.get(step_type, "You are a helpful AI assistant.")

```
```
    
    def _extract_tool_tag(self, content: str) -> Dict:
        
```
```
# Parse <tool>{"name": "...", "params": {...}}</tool>

```
```
        import re
        
```
```
match = re.search(r'<tool>(.*?)</tool>', content, re.DOTALL)

```
```
        
```
```
if match:

```
```
            
```
```
return json.loads(match.group(1))

```
```
        
```
```
return {}

```
```
    
    async def _check_budget(self, build: Build) -> bool:
        
```
```
if build.token_usage > Config.TOKEN_BUDGET:

```
```
            build
```
```
.state = State.FAILED

```
```
            build.error_log.append(f"Token budget exceeded: {build.token_usage}/{Config.TOKEN_BUDGET}")
            
```
```
await self._notify(build, "❌ Token budget exhausted", "high")

```
```
            
```
```
return False

```
```
        return True
    
    # ─── Main Execution Loop ─────────────────────────────────────
    
```
```
async def run(self, build: Build):

```
```
        """The core harness loop."""
        build.state = State.PLANNING
        
```
```
await self._persist(build)

```
```
        
        
```
```
async with self.router:

```
```
            
```
```
try:

```
```
                # ── Phase 1: Planning ─────────────────────────────
                plan_step = Step(
                    
```
```
id=f"{build.id}_plan",

```
```
                    
```
```
type=StepType.PLAN,

```
```
                    prompt=f"Create a detailed execution plan for: {build.prompt}\n\n"
                           
```
```
f"Available tools: {list(self.tools.tools.keys())}\n"

```
```
                           f"Output format: JSON array of steps with 'type', 'description', 'model'",
                    model="deepseek" if build.strategy != "kimi" else "kimi"
                
```
```
)

```
```
                
                
```
```
if not await self._run_step(build, plan_step):

```
```
                    build
```
```
.state = State.FAILED

```
```
                    
```
```
return

```
```
                
                
```
```
# Parse plan into steps

```
```
                plan 
```
```
= json.loads(plan_step.result)

```
```
                execution_steps 
```
```
= []

```
```
                for i, p in enumerate(plan[:Config.MAX_STEPS]):
                    model 
```
```
= p.get("model", "deepseek" if build.strategy != "kimi" else "kimi")

```
```
                    
```
```
if build.strategy == "hybrid" and p.get("type") == "review":

```
```
                        model 
```
```
= "deepseek" if model == "kimi" else "kimi"  # Cross-review

```
```
                    
                    execution_steps
```
```
.append(Step(

```
```
                        id=f"{build.id}_exec_{i}",
                        type=StepType[p.get("type", "CODE").upper()],
                        prompt=p.get("description", p.get("prompt", "")),
                        model
```
```
=model

```
```
                    
```
```
))

```
```
                
                
```
```
# ── Phase 2: Execution ───────────────────────────

```
```
                build.state = State.EXECUTING
                
```
```
await self._persist(build)

```
```
                
                for step in execution_steps:
                    if not await self._check_budget(build):
                        
```
```
return

```
```
                    
                    
```
```
# Check for human gate

```
```
                    
```
```
if step.type == StepType.HUMAN:

```
```
                        build
```
```
.state = State.WAITING_HUMAN

```
```
                        build
```
```
.human_input_queue.append(step.prompt)

```
```
                        
```
```
await self._persist(build)

```
```
                        await self._notify(build, f"🛑 Human input needed: {step.prompt}", "high")
                        
```
```
return  # Pause here, resume later

```
```
                    
                    success 
```
```
= await self._run_step(build, step)

```
```
                    
```
```
if not success:

```
```
                        build.state = State.FAILED
                        await self._notify(build, f"❌ Step failed after retries: {step.error}", "high")
                        
```
```
return

```
```
                    
                    await self._persist(build)
                
                
```
```
# ── Phase 3: Review (if hybrid) ──────────────────

```
```
                
```
```
if build.strategy == "hybrid":

```
```
                    build.state = State.REVIEWING
                    review_step 
```
```
= Step(

```
```
                        id=f"{build.id}_review",
                        
```
```
type=StepType.REVIEW,

```
```
                        prompt=f"Review all outputs for correctness:\n\n{json.dumps([s.result for s in build.steps if s.result])}",
                        model
```
```
="kimi"  # Cross-review with other model

```
```
                    
```
```
)

```
```
                    
```
```
await self._run_step(build, review_step)

```
```
                
                
```
```
# ── Phase 4: Merge ───────────────────────────────

```
```
                build.state = State.COMPLETED
                merge_step = Step(
                    
```
```
id=f"{build.id}_merge",

```
```
                    type=StepType.MERGE,
                    prompt
```
```
=f"Combine all outputs into final deliverable. Original request: {build.prompt}",

```
```
                    model=build.strategy if build.strategy != "hybrid" else "deepseek"
                
```
```
)

```
```
                await self._run_step(build, merge_step)
                build.metadata["final_output"] = merge_step.result
                
                await self._notify(build, f"✅ Build complete! Tokens used: {build.token_usage}", "normal")
                
            except Exception as e:
                build.state = State.FAILED
                build.error_log.append(f"Harness error: {str(e)}")
                
```
```
await self._notify(build, f"❌ Harness failure: {e}", "high")

```
```
                logging.exception("Build failed")
            
            
```
```
finally:

```
```
                build.updated_at = datetime.utcnow().isoformat()
                await self._persist(build)
    
    # ─── Public API ──────────────────────────────────────────────
    async def submit(self, prompt: str, strategy: str = "hybrid") -> str:
        build_id = hashlib.sha256(f"{prompt}{datetime.now().isoformat()}".encode()).hexdigest()[:12]
        build 
```
```
= Build(

```
```
            
```
```
id=build_id,

```
```
            prompt
```
```
=prompt,

```
```
            strategy
```
```
=strategy,

```
```
            state
```
```
=State.QUEUED

```
```
        
```
```
)

```
```
        
```
```
await self._persist(build)

```
```
        asyncio
```
```
.create_task(self.run(build))

```
```
        
```
```
return build_id

```
```
    
    async def resume(self, build_id: str, human_input: str) -> Dict:
        build 
```
```
= await self._load(build_id)

```
```
        
```
```
if not build or build.state != State.WAITING_HUMAN:

```
```
            
```
```
return {"error": "Build not found or not waiting for input"}

```
```
        
        build.human_input_queue.append(human_input)
        build
```
```
.context["human_responses"] = build.context.get("human_responses", []) + [human_input]

```
```
        build.state = State.EXECUTING
        await self._persist(build)
        
        asyncio
```
```
.create_task(self.run(build))  # Re-enter loop

```
```
        
```
```
return {"status": "resumed", "build_id": build_id}

```
```
    
    async def status(self, build_id: str) -> Optional[Dict]:
        build = await self._load(build_id)
        
```
```
if not build:

```
```
            
```
```
return None

```
```
        
```
```
return {

```
```
            
```
```
"id": build.id,

```
```
            
```
```
"state": build.state.name,

```
```
            
```
```
"progress": f"{len([s for s in build.steps if s.completed_at])}/{len(build.steps)}",

```
```
            
```
```
"token_usage": build.token_usage,

```
```
            
```
```
"needs_human": build.state == State.WAITING_HUMAN,

```
```
            
```
```
"human_question": build.human_input_queue[-1] if build.human_input_queue else None,

```
```
            
```
```
"final_output": build.metadata.get("final_output"),

```
```
            
```
```
"errors": build.error_log[-5:] if build.error_log else [],

```
```
            
```
```
"steps": [{"id": s.id, "type": s.type.name, "status": "done" if s.completed_at else "pending", 

```
```
                      
```
```
"error": s.error, "tokens": s.tokens_used} for s in build.steps]

```
```
        
```
```
}

```
```
    
    
```
```
async def cancel(self, build_id: str) -> bool:

```
```
        build = await self._load(build_id)
        
```
```
if build and build.state in [State.QUEUED, State.PLANNING, State.EXECUTING, State.WAITING_HUMAN]:

```
```
            build.state = State.CANCELLED
            
```
```
await self._persist(build)

```
```
            
```
```
await self._notify(build, "Build cancelled by user", "normal")

```
```
            
```
```
return True

```
```
        
```
```
return False

```
  
  
**2. Language Speed Analysis**  
**Short answer: For this workload, Python is not your bottleneck. The network is.**  
**Here's the honest breakdown:**  
**Table**  
  
  
  

| Language | Pros for Agent Harness | Cons | Verdict |
| --------------- | ------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------- | ------------------------------------------ |
| Python | Fastest dev speed, massive AI ecosystem, great async (asyncio), every LLM SDK supports it first | GIL limits true CPU parallelism, higher memory per coroutine | Best choice for 95% of cases |
| Go | Goroutines are lighter than Python coroutines, faster JSON parsing, lower memory, single binary deploy | Verbose error handling, no native AI ecosystem, writing agents is slower | Good if you need 1000+ concurrent builds |
| Rust | Zero-cost async, lowest memory, fastest execution, bulletproof reliability | Steep learning curve, slow dev speed, almost no LLM SDKs (you'd write raw HTTP) | Overkill unless you're building a platform |
| TypeScript/Node | Same async model as Python, good for full-stack, easy deploy | Slower than Go/Rust, event loop can block on CPU tasks | Fine if you're already JS-heavy |
| Bun | Faster than Node, similar ergonomics | Still maturing, ecosystem gaps | Interesting but risky |
  
****Where Time Actually Goes in Your Agent Loop****  
**plain**  
  
  
```
Total Build Time: ~2-5 minutes
├─ LLM API Call (DeepSeek/Kimi): 95% (30-90s per call)
├─ Network I/O (Redis, notifications): 3%
├─ JSON parsing/string ops: 1.5%
└─ Python interpreter overhead: 0.5%

```
  
**The API call is 95% of your latency. Python's overhead is negligible.**  
**When to Consider Switching**  
**Table**  
  
  
  

| Scenario | Switch To | Why |
| -------------------------------------------------------- | --------- | ---------------------------------------------------- |
| Running 100+ concurrent builds on a small VPS | Go | Goroutines use ~2KB vs Python's ~10KB+ per coroutine |
| Building a commercial SaaS with thousands of users | Rust/Go | Memory efficiency and reliability at scale |
| Cold starts on serverless (Lambda) matter | Go | 10ms startup vs Python's 100-500ms |
| You need sub-millisecond state transitions between steps | Rust | Python's GIL + garbage collection adds jitter |
| Just you and a team, iterating fast | Python | Developer velocity beats runtime speed |
  
****My Recommendation****  
## Stick with Python. Here's why:  
1. **Your constraint is API latency, not compute.** Swapping to Rust won't make DeepSeek respond faster.  
2. **Developer velocity is king.** You can iterate the harness 3x faster in Python.  
3. **Ecosystem lock-in.** DeepSeek and Kimi SDKs, LangChain, LlamaIndex, etc. are Python-first.  
4. **Asyncio is sufficient.** Python handles thousands of concurrent I/O-bound tasks fine. The GIL only hurts CPU-bound work.  
## If you hit scale later, port just the orchestrator to Go or Rust, keep Python for the agent logic. But honestly, by then you'll probably just horizontally scale (more Python workers) rather than rewrite.  
  
**3. Deploy-Ready Repo Structure**  
**plain**  
  
  
```
agent-harness/
├── harness/
│   ├── __init__.py
│   ├── core.py          # AgentHarness class
│   ├── router.py        # LLMRouter with circuit breakers
│   ├── tools.py         # ToolRegistry + default tools
│   ├── state.py         # Enums and data models
│   └── notifications.py # Slack, email, push handlers
├── api/
│   ├── main.py          # FastAPI app
│   └── routes.py        # Endpoints
├── worker/
│   └── consumer.py      # If using Redis queue + separate workers
├── tests/
├── Dockerfile
├── docker-compose.yml   # Redis + API
├── requirements.txt
└── .env.example

```
  
**Want me to generate the full repo as a downloadable package, or set up a specific piece (e.g., the tool-use system with file execution, or a swarm mode where multiple agents debate each other)?**  
  
  
  
  
  
**Swarm it, cement the decision of existing harness vs bespoke harness and all technical specifications to go from no solution for the use case till full deployment in that specification**  
##   
Edit  
##   
Copy  
##   
Share  
  
  
Designing Agent Disagreement Resolution with Token Budgets and Durable Backends  
  
  
1.   
2.   
3.   
  
  
  
*   
*   
*   
*   
*   
*   
  
*   
*   
*   
*   
*   
*   
  
  
*   
*   
*   
*   
*   
  
  
  
1.   
2.   
3.   
4.   
5.   
6.   
7.   
8.   
9.   
10.   
11.   
12.   
  
  
  
  
*   
*   
  
*   
*   
*   
*   
*   
*   
*   
  
*   
*   
  
*   
*   
  
*   
*   
*   
*   
  
*   
*   
*   
*   
  
*   
*   
*   
  
*   
  
  
  
  
1.   
2.   
3.   
4.   
5.   
6.   
7.   
8.   
9.   
10.   
  
  
*   
*   
*   
*   
  
  
  
  
*   
*   
*   
  
**Technical Specification: Swarm Agent Harness**  
**From Zero to Production Deployment**  
  
**1. Decision Record: Bespoke vs. Existing Frameworks**  
**1.1 Candidate Analysis**  
**Table**  
  
  
  

| Framework | Fit for Background Execution | Human-in-the-Loop | Multi-Model Routing | Token Budgeting | Swarm Logic | Verdict |
| --------------- | ----------------------------------------------- | ------------------ | ------------------- | --------------- | -------------- | ---------------------------------------------------------------------------------- |
| LangChain | Poor. Designed for synchronous request/response | Possible but hacky | Supported | Manual only | Basic | Reject — Abstraction overhead, fights against long-running state |
| CrewAI | Poor. Session-based, not durable | Basic | Supported | No | Good for roles | Reject — No persistence layer, crashes lose state |
| AutoGen | Moderate. Group chat pattern | Complex | Yes | No | Debate-focused | Reject — Microsoft-centric, over-engineered for simple swarm |
| Prefect/Dagster | Excellent. Built for durable execution | Not native | Manual | No | No | Partial — Use as orchestration substrate only |
| Temporal | Excellent. Durable execution | Possible | Manual | No | No | Partial — Use for state machine durability if scaling beyond 100 concurrent builds |
| Bespoke | Excellent. Native async + Redis | First-class | Native | Native | Fully custom | Adopt |
  
****1.2 Rationale****  
## Existing frameworks optimize for the wrong constraint. They assume:  
* LLM calls are fast (< 10s)  
* Agents are stateless or short-lived  
* Human interaction is a pre-prompt, not a mid-loop gate  
* Single-model usage (OpenAI)  
**Your constraint is the inverse:**  
* Builds run for 2–15 minutes in the background  
* Human gates can pause for hours  
* You route across DeepSeek (cheap reasoning) and Kimi (long context)  
* Token budgets must be enforced per-step, not per-request  
## Verdict: Bespoke harness with Redis persistence and FastAPI. Migrate to Temporal only if you exceed 500 concurrent builds.  
**1.3 Language Cemented: Python**  
**Table**  
  
  
  

| Concern | Reality |
| ------------------------ | ---------------------------------------------------------------------------------------------- |
| "Python is slow" | Your 95% latency is LLM API round-trip (30–90s). Python adds <50ms overhead per step. |
| "GIL blocks concurrency" | asyncio handles thousands of I/O-bound agents. CPU work per step is JSON parsing — negligible. |
| "Memory per agent" | ~10MB per build context. A $20 VPS handles 100+ concurrent builds. |
| "Cold starts" | Docker + Python = 1–2s cold start. Acceptable for background workers. |
  
****Alternative analysis: Go would save ~70% memory and start in 10ms. Rust would save 85%. Both require writing raw HTTP clients for DeepSeek/Kimi (no official SDKs). Developer velocity outweighs runtime cost at this stage.****  
  
**2. System Architecture**  
**plain**  
  
  
```
┌─────────────────────────────────────────────────────────────────────┐
│                         CLIENT LAYER                                │
│  (CLI / Web UI / Mobile) → REST API + WebSocket (optional)        │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      API GATEWAY (FastAPI)                            │
│  • Auth (API Key)  • Rate Limiting  • Request Validation              │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     STATE MANAGER (Redis)                             │
│  • Build state machine  • Step queue  • Token budgets  • Locks        │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    SWARM COORDINATOR                                  │
│  • Decomposes work  • Spawns agents  • Collects votes  • Merges      │
└─────────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│   AGENT POOL    │ │   AGENT POOL    │ │   AGENT POOL    │
│  (DeepSeek API) │ │   (Kimi API)    │ │  (Tool Workers) │
│                 │ │                 │ │                 │
│  • Planner      │ │  • Coder        │ │  • File I/O     │
│  • Reasoner     │ │  • Reviewer     │ │  • Code Exec    │
│  • Budget: 30K  │ │  • Budget: 20K  │ │  • Web Search   │
└─────────────────┘ └─────────────────┘ └─────────────────┘
              │               │               │
              └───────────────┼───────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  NOTIFICATION DISPATCHER                            │
│  • Webhooks  • Slack  • Email  • Pushover  • SMS (Twilio)           │
│  • Urgency routing: HIGH = immediate, NORMAL = batch                │
└─────────────────────────────────────────────────────────────────────┘

```
  
  
**3. Component Specifications**  
**3.1 State Machine (Strict)**  
**plain**  
  
  
```
QUEUED ──► PLANNING ──► EXECUTING ──► REVIEWING ──► MERGING ──► COMPLETED
   │           │            │              │            │
   │           │            ▼              │            │
   │           │      WAITING_HUMAN ──────┘            │
   │           │            │ (resume)                 │
   │           ▼            ▼                          ▼
   └──► CANCELLED ◄── FAILED ◄───────────────────────┘

```
  
## Transitions are enforced at the database level. No agent can write a state transition that violates this graph.  
**3.2 Swarm Coordination Protocol**  
**Pattern: Parallel Decomposition with Cross-Review**  
**plain**  
  
  
```
1. DECOMPOSE: Planner agent breaks prompt into N sub-tasks
2. ASSIGN: Swarm coordinator assigns each sub-task to an agent
   - Default: Round-robin across DeepSeek/Kimi
   - Code tasks → Kimi (better at long-context code)
   - Reasoning tasks → DeepSeek (cheaper, good at logic)
3. EXECUTE: All agents run in parallel (asyncio.gather)
4. REVIEW: Each output is reviewed by an agent using the *opposite* model
   - DeepSeek output → Kimi reviews
   - Kimi output → DeepSeek reviews
5. VOTE: If reviewer approves → pass. If rejects → retry (max 2x)
6. MERGE: Senior agent combines all approved outputs
7. FINAL_REVIEW: Third model (whichever has more budget left) sanity-checks merge

```
  
**Conflict Resolution:**  
* If Agent A (Kimi) and Reviewer B (DeepSeek) disagree after 2 retries → **Human gate**  
* If 2 of 3 parallel agents fail → **Abort swarm**, notify user  
  
**4. Data Model**  
**Python**  
  
  
```
# models.py
from enum import Enum
from
```
```
 dataclasses import dataclass, field

```
```
from
```
```
 typing import Dict, List, Optional, Literal

```
```
from
```
```
 datetime import datetime

```
```

class BuildState(Enum):
    QUEUED = "queued"
    PLANNING = "planning"
    EXECUTING = "executing"
    REVIEWING 
```
```
= "reviewing"

```
```
    WAITING_HUMAN = "waiting_human"
    MERGING 
```
```
= "merging"

```
```
    COMPLETED 
```
```
= "completed"

```
```
    FAILED = "failed"
    CANCELLED = "cancelled"

class
```
```
 AgentRole(Enum):

```
```
    PLANNER 
```
```
= "planner"

```
```
    CODER = "coder"
    REVIEWER 
```
```
= "reviewer"

```
```
    TESTER = "tester"
    MERGER 
```
```
= "merger"

```
```
    TOOL = "tool"

class
```
```
 ModelProvider(Enum):

```
```
    DEEPSEEK 
```
```
= "deepseek"

```
```
    KIMI 
```
```
= "kimi"

```
```

@dataclass
```
```


```
```
class AgentConfig:
    role
```
```
: AgentRole

```
```
    provider
```
```
: ModelProvider

```
```
    model
```
```
: str  # e.g., "deepseek-chat", "kimi-k3"

```
```
    temperature: float = 0.7
    max_tokens
```
```
: int = 4000

```
```
    system_prompt
```
```
: str = ""

```
```
    token_budget
```
```
: int = 20000

```
```

@dataclass
class Step:
    
```
```
id: str

```
```
    agent_id
```
```
: str

```
```
    role: AgentRole
    provider
```
```
: ModelProvider

```
```
    prompt: str
    result
```
```
: Optional[str] = None

```
```
    review: Optional[str] = None  # Cross-review output
    approved: bool = False
    tokens_used: int = 0
    duration_ms: float = 0.0
    retry_count
```
```
: int = 0

```
```
    error: Optional[str] = None
    created_at
```
```
: str = field(default_factory=lambda: datetime.utcnow().isoformat())

```
```
    completed_at
```
```
: Optional[str] = None

```
```

@dataclass
class SwarmBuild:
    
```
```
id: str

```
```
    prompt: str
    state: BuildState
    strategy
```
```
: Literal["single", "swarm", "debate"] = "swarm"

```
```
    agents: List[AgentConfig] = field(default_factory=list)
    steps: List[Step] = field(default_factory=list)
    context: Dict = field(default_factory=dict)
    token_usage: int = 0
    token_budget_total: int = 50000
    human_input_queue
```
```
: List[Dict] = field(default_factory=list)

```
```
    created_at
```
```
: str = field(default_factory=lambda: datetime.utcnow().isoformat())

```
```
    updated_at
```
```
: str = field(default_factory=lambda: datetime.utcnow().isoformat())

```
```
    final_output
```
```
: Optional[str] = None

```
```
    error_log
```
```
: List[str] = field(default_factory=list)

```
```
    metadata
```
```
: Dict = field(default_factory=dict)

```
  
  
**5. API Specification**  
**5.1 REST Endpoints**  
**Table**  
  
  
  

| Method | Endpoint               | Description                 | Auth    |
| ------ | ---------------------- | --------------------------- | ------- |
| POST   | /v1/build              | Submit new build/swarm      | API Key |
| GET    | /v1/build/{id}         | Full build status + steps   | API Key |
| GET    | /v1/build/{id}/stream  | WebSocket real-time updates | API Key |
| POST   | /v1/build/{id}/respond | Submit human input          | API Key |
| POST   | /v1/build/{id}/cancel  | Cancel running build        | API Key |
| GET    | /v1/builds             | List builds (paginated)     | API Key |
| GET    | /v1/health             | Service + API key status    | None    |
  
****5.2 Request/Response Examples****  
**Submit Swarm Build:**  
**JSON**  
  
  
```
POST /v1/build
Headers: X-API-Key: sk-...

{
```
```


```
```
  
```
```
"prompt": "Build a Python API that fetches weather data and caches it in Redis",

```
```
  
```
```
"strategy": "swarm",

```
```
  
```
```
"agents": [

```
```
    
```
```
{"role": "planner", "provider": "deepseek", "model": "deepseek-chat"},

```
```
    
```
```
{"role": "coder", "provider": "kimi", "model": "kimi-k3"},

```
```
    
```
```
{"role": "reviewer", "provider": "deepseek", "model": "deepseek-chat"},

```
```
    
```
```
{"role": "merger", "provider": "kimi", "model": "kimi-k3"}

```
```
  
```
```
],

```
```
  
```
```
"token_budget_total": 40000,

```
```
  
```
```
"notification": {

```
```
    
```
```
"webhook": "https://hooks.slack.com/...",

```
```
    "urgency": "high"
  
```
```
}

```
```
}

```
  
**Response:**  
**JSON**  
  
  
```
{
  
```
```
"build_id": "a3f7b2d9e8c1",

```
```
  
```
```
"state": "queued",

```
```
  
```
```
"estimated_duration": "120s",

```
```
  
```
```
"status_url": "https://api.yourdomain.com/v1/build/a3f7b2d9e8c1",

```
```
  
```
```
"websocket_url": "wss://api.yourdomain.com/v1/build/a3f7b2d9e8c1/stream"

```
```
}

```
  
**Human Input Required Response:**  
**JSON**  
  
  
```
{
  "build_id": "a3f7b2d9e8c1",
  
```
```
"state": "waiting_human",

```
```
  "question": "Should I use aiohttp or httpx for the HTTP client?",
  
```
```
"context": "Step 3 (coder) requires library preference...",

```
```
  
```
```
"respond_url": "https://api.yourdomain.com/v1/build/a3f7b2d9e8c1/respond"

```
```
}

```
  
  
**6. Complete Implementation**  
**6.1 Project Structure**  
**plain**  
  
  
```
swarm-harness/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app
│   ├── config.py            # Settings & env vars
│   ├── models.py            # Dataclasses (above)
│   ├── state_machine.py     # State transition validator
│   ├── llm_router.py        # DeepSeek + Kimi client
│   ├── swarm_coordinator.py # Parallel agent spawning
│   ├── agent_pool.py        # Agent execution logic
│   ├── tool_registry.py     # File, exec, search tools
│   ├── notifications.py     # Webhook, Slack, email
│   ├── persistence.py         # Redis wrapper
│   └── api/
│       ├── builds.py        # Routes
│       └── websocket.py     # WS handler
├── worker/
│   └── consumer.py          # Background worker (optional)
├── tests/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── .env.example

```
  
**6.2 Core Implementation**  
**Python**  
  
  
```
# app/config.py
import os
from
```
```
 dataclasses import dataclass

```
```

@dataclass(
```
```
frozen=True)

```
```
class Config:
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379")
    DEEPSEEK_API_KEY
```
```
: str = os.getenv("DEEPSEEK_API_KEY", "")

```
```
    KIMI_API_KEY
```
```
: str = os.getenv("KIMI_API_KEY", "")

```
```
    API_KEY: str = os.getenv("API_KEY", "dev-key-change-me")
    MAX_STEPS
```
```
: int = int(os.getenv("MAX_STEPS", "25"))

```
```
    DEFAULT_TOKEN_BUDGET: int = int(os.getenv("DEFAULT_TOKEN_BUDGET", "50000"))
    NOTIFICATION_WEBHOOK: str = os.getenv("NOTIFICATION_WEBHOOK", "")
    LOG_LEVEL
```
```
: str = os.getenv("LOG_LEVEL", "INFO")

```
```

CONFIG = Config()

```
  
**Python**  
  
  
```
# app/state_machine.py
from
```
```
 enum import Enum

```
```
from
```
```
 typing import Set, Dict

```
```

class
```
```
 BuildState(Enum):

```
```
    QUEUED 
```
```
= "queued"

```
```
    PLANNING = "planning"
    EXECUTING = "executing"
    REVIEWING = "reviewing"
    WAITING_HUMAN = "waiting_human"
    MERGING = "merging"
    COMPLETED 
```
```
= "completed"

```
```
    FAILED 
```
```
= "failed"

```
```
    CANCELLED = "cancelled"

# Valid transitions: current -> {allowed next states}
TRANSITIONS
```
```
: Dict[BuildState, Set[BuildState]] = {

```
```
    BuildState
```
```
.QUEUED: {BuildState.PLANNING, BuildState.CANCELLED},

```
```
    BuildState.PLANNING: {BuildState.EXECUTING, BuildState.FAILED, BuildState.CANCELLED},
    BuildState
```
```
.EXECUTING: {BuildState.REVIEWING, BuildState.WAITING_HUMAN, BuildState.FAILED, BuildState.CANCELLED},

```
```
    BuildState
```
```
.REVIEWING: {BuildState.MERGING, BuildState.EXECUTING, BuildState.FAILED, BuildState.CANCELLED},

```
```
    BuildState.WAITING_HUMAN: {BuildState.EXECUTING, BuildState.CANCELLED},  # Resume or kill
    BuildState.MERGING: {BuildState.COMPLETED, BuildState.FAILED, BuildState.CANCELLED},
    BuildState.COMPLETED: set(),
    BuildState
```
```
.FAILED: set(),

```
```
    BuildState
```
```
.CANCELLED: set(),

```
```
}

def
```
```
 can_transition(current: BuildState, next_state: BuildState) -> bool:

```
```
    
```
```
return next_state in TRANSITIONS.get(current, set())

```
  
**Python**  
  
  
```
# app/llm_router.py
import
```
```
 aiohttp

```
```
import asyncio
from
```
```
 typing import List, Dict, Tuple

```
```
from
```
```
 tenacity import retry, stop_after_attempt, wait_exponential

```
```
from
```
```
 app.config import CONFIG

```
```

class
```
```
 LLMRouter:

```
```
    def __init__(self):
        self.session: aiohttp.ClientSession = None
        self._lock = asyncio.Lock()
    
    
```
```
async def __aenter__(self):

```
```
        timeout = aiohttp.ClientTimeout(total=120, connect=10)
        self
```
```
.session = aiohttp.ClientSession(timeout=timeout)

```
```
        
```
```
return self

```
```
    
    async def __aexit__(self, *args):
        await self.session.close()
    
    
```
```
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))

```
```
    
```
```
async def call_deepseek(self, messages: List[Dict], model: str = "deepseek-chat", max_tokens: int = 4000) -> Tuple[str, int]:

```
```
        payload = {
            
```
```
"model": model,

```
```
            "messages": messages,
            "temperature": 0.7,
            
```
```
"max_tokens": max_tokens,

```
```
            
```
```
"stream": False

```
```
        
```
```
}

```
```
        async with self._lock:
            
```
```
async with self.session.post(

```
```
                
```
```
"https://api.deepseek.com/v1/chat/completions",

```
```
                headers
```
```
={"Authorization": f"Bearer {CONFIG.DEEPSEEK_API_KEY}", "Content-Type": "application/json"},

```
```
                json=payload
            ) as resp:
                resp
```
```
.raise_for_status()

```
```
                data = await resp.json()
                content 
```
```
= data["choices"][0]["message"]["content"]

```
```
                tokens = data.get("usage", {}).get("total_tokens", 0)
                
```
```
return content, tokens

```
```
    
    
```
```
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))

```
```
    
```
```
async def call_kimi(self, messages: List[Dict], model: str = "kimi-k3", max_tokens: int = 4000) -> Tuple[str, int]:

```
```
        payload 
```
```
= {

```
```
            
```
```
"model": model,

```
```
            
```
```
"messages": messages,

```
```
            
```
```
"temperature": 0.7,

```
```
            
```
```
"max_tokens": max_tokens,

```
```
            "stream": False
        }
        
```
```
async with self._lock:

```
```
            
```
```
async with self.session.post(

```
```
                
```
```
"https://api.moonshot.cn/v1/chat/completions",

```
```
                headers
```
```
={"Authorization": f"Bearer {CONFIG.KIMI_API_KEY}", "Content-Type": "application/json"},

```
```
                json=payload
            
```
```
) as resp:

```
```
                resp
```
```
.raise_for_status()

```
```
                data = await resp.json()
                content = data["choices"][0]["message"]["content"]
                tokens = data.get("usage", {}).get("total_tokens", 0)
                
```
```
return content, tokens

```
```
    
    async def route(self, messages: List[Dict], provider: str, model: str, max_tokens: int = 4000) -> Tuple[str, int]:
        
```
```
if provider == "deepseek":

```
```
            
```
```
return await self.call_deepseek(messages, model, max_tokens)

```
```
        
```
```
elif provider == "kimi":

```
```
            
```
```
return await self.call_kimi(messages, model, max_tokens)

```
```
        
```
```
else:

```
```
            raise ValueError(f"Unknown provider: {provider}")

```
  
**Python**  
  
  
```
# app/swarm_coordinator.py
import
```
```
 asyncio

```
```
import
```
```
 json

```
```
import
```
```
 hashlib

```
```
from
```
```
 datetime import datetime

```
```
from typing import List, Dict, Optional
from app.models import SwarmBuild, BuildState, AgentConfig, AgentRole, Step, ModelProvider
from
```
```
 app.llm_router import LLMRouter

```
```
from
```
```
 app.persistence import RedisStore

```
```
from
```
```
 app.notifications import NotificationDispatcher

```
```
from app.state_machine import can_transition

class SwarmCoordinator:
    def __init__(self):
        self.store = RedisStore()
        self.notifier = NotificationDispatcher()
        self.router = LLMRouter()
    
    
```
```
async def submit(self, prompt: str, agents: List[AgentConfig], token_budget: int = 50000) -> str:

```
```
        build_id 
```
```
= hashlib.sha256(f"{prompt}{datetime.utcnow().isoformat()}".encode()).hexdigest()[:12]

```
```
        build 
```
```
= SwarmBuild(

```
```
            id=build_id,
            prompt
```
```
=prompt,

```
```
            state=BuildState.QUEUED,
            agents=agents,
            token_budget_total=token_budget
        
```
```
)

```
```
        await self.store.save(build)
        asyncio.create_task(self._run(build))
        return build_id
    
    
```
```
async def _transition(self, build: SwarmBuild, new_state: BuildState):

```
```
        
```
```
if not can_transition(build.state, new_state):

```
```
            
```
```
raise ValueError(f"Invalid transition: {build.state.value} -> {new_state.value}")

```
```
        build
```
```
.state = new_state

```
```
        build.updated_at = datetime.utcnow().isoformat()
        
```
```
await self.store.save(build)

```
```
    
    async def _run(self, build: SwarmBuild):
        async with self.router:
            
```
```
try:

```
```
                
```
```
await self._transition(build, BuildState.PLANNING)

```
```
                
                
```
```
# Phase 1: Planning (single agent, usually DeepSeek for reasoning)

```
```
                planner 
```
```
= next((a for a in build.agents if a.role == AgentRole.PLANNER), build.agents[0])

```
```
                plan_messages = [
                    
```
```
{"role": "system", "content": planner.system_prompt or "You are a technical planner. Break requests into executable sub-tasks."},

```
```
                    {"role": "user", "content": f"Plan this build: {build.prompt}\n\nOutput JSON array of sub-tasks with 'description', 'role' (coder/reviewer/tester)"}
                
```
```
]

```
```
                plan_text, plan_tokens = await self.router.route(plan_messages, planner.provider.value, planner.model)
                build.token_usage += plan_tokens
                
                
```
```
# Parse plan

```
```
                try:
                    plan 
```
```
= json.loads(plan_text)

```
```
                except json.JSONDecodeError:
                    
```
```
# Fallback: extract JSON from markdown

```
```
                    
```
```
import re

```
```
                    json_match 
```
```
= re.search(r'\[.*\]', plan_text, re.DOTALL)

```
```
                    plan 
```
```
= json.loads(json_match.group()) if json_match else [{"description": build.prompt, "role": "coder"}]

```
```
                
                
```
```
await self._transition(build, BuildState.EXECUTING)

```
```
                
                
```
```
# Phase 2: Parallel Execution

```
```
                step_futures 
```
```
= []

```
```
                
```
```
for i, task in enumerate(plan[:5]):  # Max 5 parallel tasks

```
```
                    agent 
```
```
= next((a for a in build.agents if a.role.value == task.get("role", "coder")), build.agents[0])

```
```
                    step 
```
```
= Step(

```
```
                        id=f"{build.id}_step_{i}",
                        agent_id
```
```
=f"{agent.role.value}_{agent.provider.value}",

```
```
                        role=agent.role,
                        provider
```
```
=agent.provider,

```
```
                        prompt=task["description"]
                    
```
```
)

```
```
                    build.steps.append(step)
                    step_futures
```
```
.append(self._execute_step(build, step, agent))

```
```
                
                results 
```
```
= await asyncio.gather(*step_futures, return_exceptions=True)

```
```
                
                # Check for failures
                failures 
```
```
= [r for r in results if isinstance(r, Exception)]

```
```
                if len(failures) > len(plan) / 2:
                    build.error_log.append(f"Majority of swarm failed: {failures}")
                    await self._transition(build, BuildState.FAILED)
                    await self.notifier.notify(build, "❌ Swarm failed: majority of agents failed", "high")
                    
```
```
return

```
```
                
                await self._transition(build, BuildState.REVIEWING)
                
                
```
```
# Phase 3: Cross-Review (parallel)

```
```
                review_futures 
```
```
= []

```
```
                
```
```
for step in build.steps:

```
```
                    
```
```
if step.result and not step.error:

```
```
                        reviewer = next((a for a in build.agents if a.role == AgentRole.REVIEWER), None)
                        
```
```
if reviewer:

```
```
                            review_step = Step(
                                
```
```
id=f"{step.id}_review",

```
```
                                agent_id
```
```
=f"{reviewer.role.value}_{reviewer.provider.value}",

```
```
                                role=AgentRole.REVIEWER,
                                provider
```
```
=reviewer.provider,

```
```
                                prompt
```
```
=f"Review this output for correctness and completeness. Approve or reject with reason:\n\n{step.result}"

```
```
                            )
                            build.steps.append(review_step)
                            review_futures
```
```
.append(self._execute_step(build, review_step, reviewer))

```
```
                
                await asyncio.gather(*review_futures)
                
                
```
```
# Check approvals

```
```
                for step in build.steps:
                    if step.role == AgentRole.REVIEWER and step.result:
                        step
```
```
.approved = "approve" in step.result.lower() or "correct" in step.result.lower()

```
```
                
                unapproved 
```
```
= [s for s in build.steps if s.role != AgentRole.REVIEWER and not any(

```
```
                    r
```
```
.approved for r in build.steps if r.id == f"{s.id}_review"

```
```
                
```
```
)]

```
```
                
                
```
```
if unapproved and build.token_usage < build.token_budget_total * 0.8:

```
```
                    
```
```
# Retry unapproved steps once

```
```
                    retry_futures = []
                    
```
```
for step in unapproved:

```
```
                        step.retry_count += 1
                        agent = next((a for a in build.agents if a.role == step.role), build.agents[0])
                        retry_futures.append(self._execute_step(build, step, agent))
                    await asyncio.gather(*retry_futures)
                
                
```
```
# Phase 4: Merge

```
```
                
```
```
await self._transition(build, BuildState.MERGING)

```
```
                merger = next((a for a in build.agents if a.role == AgentRole.MERGER), build.agents[0])
                merge_context = "\n\n".join([
                    
```
```
f"--- {s.role.value} ---\n{s.result}" 

```
```
                    for s in build.steps 
                    if s.result and s.role != AgentRole.REVIEWER
                
```
```
])

```
```
                merge_messages 
```
```
= [

```
```
                    {"role": "system", "content": merger.system_prompt or "You are a tech lead. Combine outputs into a final deliverable."},
                    
```
```
{"role": "user", "content": f"Original request: {build.prompt}\n\nAgent outputs:\n{merge_context}"}

```
```
                
```
```
]

```
```
                final_output
```
```
, merge_tokens = await self.router.route(merge_messages, merger.provider.value, merger.model)

```
```
                build.token_usage += merge_tokens
                build.final_output = final_output
                
                
```
```
await self._transition(build, BuildState.COMPLETED)

```
```
                
```
```
await self.notifier.notify(build, f"✅ Swarm complete! Tokens: {build.token_usage}", "normal")

```
```
                
            except Exception as e:
                build.error_log.append(str(e))
                
```
```
await self._transition(build, BuildState.FAILED)

```
```
                await self.notifier.notify(build, f"❌ Swarm failed: {e}", "high")
    
    
```
```
async def _execute_step(self, build: SwarmBuild, step: Step, agent: AgentConfig):

```
```
        
```
```
if build.token_usage >= build.token_budget_total:

```
```
            raise Exception("Token budget exhausted")
        
        messages 
```
```
= [

```
```
            {"role": "system", "content": agent.system_prompt},
            {"role": "user", "content": step.prompt}
        
```
```
]

```
```
        start 
```
```
= datetime.utcnow()

```
```
        
```
```
try:

```
```
            result
```
```
, tokens = await self.router.route(messages, agent.provider.value, agent.model, agent.max_tokens)

```
```
            step
```
```
.result = result

```
```
            step
```
```
.tokens_used = tokens

```
```
            build.token_usage += tokens
            step
```
```
.completed_at = datetime.utcnow().isoformat()

```
```
            step
```
```
.duration_ms = (datetime.utcnow() - start).total_seconds() * 1000

```
```
            await self.store.save(build)
        except Exception as e:
            step
```
```
.error = str(e)

```
```
            step
```
```
.completed_at = datetime.utcnow().isoformat()

```
```
            await self.store.save(build)
            
```
```
raise

```
```
    
    async def human_input(self, build_id: str, response: str) -> Dict:
        build = await self.store.load(build_id)
        if not build or build.state != BuildState.WAITING_HUMAN:
            return {"error": "Build not found or not waiting for input"}
        
        build.context["human_input"] = response
        
```
```
await self._transition(build, BuildState.EXECUTING)

```
```
        asyncio.create_task(self._run(build))  # Resume from checkpoint
        
```
```
return {"status": "resumed", "build_id": build_id}

```
  
**Python**  
  
  
```
# app/persistence.py
import json
import
```
```
 redis.asyncio as redis

```
```
from
```
```
 app.models import SwarmBuild, BuildState

```
```
from app.config import CONFIG

class
```
```
 RedisStore:

```
```
    
```
```
def __init__(self):

```
```
        self
```
```
.client = redis.from_url(CONFIG.REDIS_URL, decode_responses=True)

```
```
    
    
```
```
async def save(self, build: SwarmBuild):

```
```
        data = {
            
```
```
"id": build.id,

```
```
            
```
```
"prompt": build.prompt,

```
```
            "state": build.state.value,
            
```
```
"strategy": build.strategy,

```
```
            
```
```
"agents": [self._agent_to_dict(a) for a in build.agents],

```
```
            
```
```
"steps": [self._step_to_dict(s) for s in build.steps],

```
```
            
```
```
"context": build.context,

```
```
            
```
```
"token_usage": build.token_usage,

```
```
            
```
```
"token_budget_total": build.token_budget_total,

```
```
            "human_input_queue": build.human_input_queue,
            
```
```
"created_at": build.created_at,

```
```
            "updated_at": build.updated_at,
            
```
```
"final_output": build.final_output,

```
```
            "error_log": build.error_log,
            "metadata": build.metadata
        }
        
```
```
await self.client.setex(f"swarm:build:{build.id}", 604800, json.dumps(data))  # 7 days

```
```
    
    async def load(self, build_id: str) -> Optional[SwarmBuild]:
        data 
```
```
= await self.client.get(f"swarm:build:{build_id}")

```
```
        
```
```
if not data:

```
```
            
```
```
return None

```
```
        d 
```
```
= json.loads(data)

```
```
        
```
```
return SwarmBuild(

```
```
            id=d["id"],
            prompt=d["prompt"],
            state=BuildState(d["state"]),
            strategy
```
```
=d.get("strategy", "swarm"),

```
```
            agents=[self._dict_to_agent(a) for a in d.get("agents", [])],
            steps
```
```
=[self._dict_to_step(s) for s in d.get("steps", [])],

```
```
            context
```
```
=d.get("context", {}),

```
```
            token_usage
```
```
=d.get("token_usage", 0),

```
```
            token_budget_total
```
```
=d.get("token_budget_total", 50000),

```
```
            human_input_queue=d.get("human_input_queue", []),
            created_at
```
```
=d["created_at"],

```
```
            updated_at
```
```
=d["updated_at"],

```
```
            final_output=d.get("final_output"),
            error_log
```
```
=d.get("error_log", []),

```
```
            metadata=d.get("metadata", {})
        )
    
    def _agent_to_dict(self, a):
        from app.models import AgentConfig, AgentRole, ModelProvider
        return {"role": a.role.value, "provider": a.provider.value, "model": a.model, "temperature": a.temperature, "max_tokens": a.max_tokens, "system_prompt": a.system_prompt, "token_budget": a.token_budget}
    
    def _dict_to_agent(self, d):
        from app.models import AgentConfig, AgentRole, ModelProvider
        
```
```
return AgentConfig(role=AgentRole(d["role"]), provider=ModelProvider(d["provider"]), model=d["model"], temperature=d.get("temperature", 0.7), max_tokens=d.get("max_tokens", 4000), system_prompt=d.get("system_prompt", ""), token_budget=d.get("token_budget", 20000))

```
```
    
    def _step_to_dict(self, s):
        
```
```
from app.models import AgentRole, ModelProvider

```
```
        return {"id": s.id, "agent_id": s.agent_id, "role": s.role.value, "provider": s.provider.value, "prompt": s.prompt, "result": s.result, "review": s.review, "approved": s.approved, "tokens_used": s.tokens_used, "duration_ms": s.duration_ms, "retry_count": s.retry_count, "error": s.error, "created_at": s.created_at, "completed_at": s.completed_at}
    
    
```
```
def _dict_to_step(self, d):

```
```
        
```
```
from app.models import AgentRole, ModelProvider, Step

```
```
        
```
```
return Step(id=d["id"], agent_id=d["agent_id"], role=AgentRole(d["role"]), provider=ModelProvider(d["provider"]), prompt=d["prompt"], result=d.get("result"), review=d.get("review"), approved=d.get("approved", False), tokens_used=d.get("tokens_used", 0), duration_ms=d.get("duration_ms", 0.0), retry_count=d.get("retry_count", 0), error=d.get("error"), created_at=d["created_at"], completed_at=d.get("completed_at"))

```
  
**Python**  
  
  
```
# app/notifications.py
import
```
```
 aiohttp

```
```
from
```
```
 typing import Dict

```
```
from
```
```
 app.models import SwarmBuild

```
```
from
```
```
 app.config import CONFIG

```
```

class
```
```
 NotificationDispatcher:

```
```
    
```
```
async def notify(self, build: SwarmBuild, message: str, urgency: str = "normal"):

```
```
        payload 
```
```
= {

```
```
            "build_id": build.id,
            
```
```
"state": build.state.value,

```
```
            "message": message,
            "urgency": urgency,
            
```
```
"needs_human": build.state.value == "waiting_human",

```
```
            
```
```
"token_usage": build.token_usage,

```
```
            
```
```
"budget_remaining": build.token_budget_total - build.token_usage,

```
```
            
```
```
"final_output": build.final_output[:500] if build.final_output else None

```
```
        
```
```
}

```
```
        
        # Webhook
        
```
```
if CONFIG.NOTIFICATION_WEBHOOK:

```
```
            
```
```
await self._webhook(payload)

```
```
        
        # Slack
        slack_url 
```
```
= build.metadata.get("slack_webhook")

```
```
        
```
```
if slack_url:

```
```
            await self._slack(slack_url, payload)
    
    async def _webhook(self, payload: Dict):
        
```
```
try:

```
```
            async with aiohttp.ClientSession() as session:
                
```
```
await session.post(CONFIG.NOTIFICATION_WEBHOOK, json=payload, timeout=aiohttp.ClientTimeout(total=10))

```
```
        
```
```
except Exception as e:

```
```
            
```
```
print(f"Webhook failed: {e}")

```
```
    
    async def _slack(self, url: str, payload: Dict):
        emoji 
```
```
= "🛑" if payload["needs_human"] else "✅" if payload["state"] == "completed" else "❌"

```
```
        try:
            
```
```
async with aiohttp.ClientSession() as session:

```
```
                
```
```
await session.post(url, json={

```
```
                    
```
```
"text": f"{emoji} *Swarm Build {payload['build_id']}*\n"

```
```
                            f"Status: `{payload['state']}`\n"
                            
```
```
f"Tokens: {payload['token_usage']}/{payload['token_usage'] + payload['budget_remaining']}\n"

```
```
                            f"{payload['message']}"
                
```
```
}, timeout=aiohttp.ClientTimeout(total=10))

```
```
        
```
```
except Exception as e:

```
```
            
```
```
print(f"Slack failed: {e}")

```
  
**Python**  
  
  
```
# app/main.py
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from
```
```
 typing import List, Optional

```
```
from
```
```
 app.models import SwarmBuild, AgentConfig, BuildState

```
```
from
```
```
 app.swarm_coordinator import SwarmCoordinator

```
```
from app.persistence import RedisStore
from app.config import CONFIG

app 
```
```
= FastAPI(title="Swarm Agent Harness", version="1.0.0")

```
```

app.add_middleware(
    CORSMiddleware,
    allow_origins
```
```
=["*"],

```
```
    allow_methods=["*"],
    allow_headers
```
```
=["*"],

```
```
)

coordinator 
```
```
= SwarmCoordinator()

```
```
store 
```
```
= RedisStore()

```
```

async
```
```
 def verify_api_key(x_api_key: str = Header(...)):

```
```
    
```
```
if x_api_key != CONFIG.API_KEY:

```
```
        raise HTTPException(status_code=401, detail="Invalid API key")
    
```
```
return x_api_key

```
```

@app.post("/v1/build")
async
```
```
 def create_build(

```
```
    prompt: str,
    agents
```
```
: List[AgentConfig],

```
```
    strategy
```
```
: str = "swarm",

```
```
    token_budget: int = 50000,
    slack_webhook
```
```
: Optional[str] = None,

```
```
    auth
```
```
: str = Depends(verify_api_key)

```
```
):
    build_id = await coordinator.submit(prompt, agents, token_budget)
    
```
```
if slack_webhook:

```
```
        build = await store.load(build_id)
        build
```
```
.metadata["slack_webhook"] = slack_webhook

```
```
        await store.save(build)
    return {
        "build_id": build_id,
        
```
```
"state": "queued",

```
```
        
```
```
"status_url": f"/v1/build/{build_id}",

```
```
        
```
```
"estimated_duration": "120s"

```
```
    }

@app.get("/v1/build/{build_id}")
async
```
```
 def get_build(build_id: str, auth: str = Depends(verify_api_key)):

```
```
    build = await store.load(build_id)
    if not build:
        raise HTTPException(status_code=404, detail="Build not found")
    
```
```
return {

```
```
        
```
```
"id": build.id,

```
```
        "state": build.state.value,
        
```
```
"token_usage": build.token_usage,

```
```
        
```
```
"budget_total": build.token_budget_total,

```
```
        
```
```
"needs_human": build.state == BuildState.WAITING_HUMAN,

```
```
        "human_question": build.human_input_queue[-1] if build.human_input_queue else None,
        "final_output": build.final_output,
        
```
```
"steps": [{"id": s.id, "role": s.role.value, "provider": s.provider.value, "status": "done" if s.completed_at else "pending", "tokens": s.tokens_used, "error": s.error} for s in build.steps],

```
```
        "errors": build.error_log
    
```
```
}

```
```

@app.post(
```
```
"/v1/build/{build_id}/respond")

```
```
async
```
```
 def respond(build_id: str, response: str, auth: str = Depends(verify_api_key)):

```
```
    result 
```
```
= await coordinator.human_input(build_id, response)

```
```
    
```
```
if "error" in result:

```
```
        
```
```
raise HTTPException(status_code=400, detail=result["error"])

```
```
    return result

@app.post(
```
```
"/v1/build/{build_id}/cancel")

```
```
async def cancel(build_id: str, auth: str = Depends(verify_api_key)):
    build = await store.load(build_id)
    
```
```
if not build:

```
```
        raise HTTPException(status_code=404, detail="Build not found")
    if build.state in [BuildState.COMPLETED, BuildState.FAILED, BuildState.CANCELLED]:
        raise HTTPException(status_code=400, detail="Build already terminal")
    build.state = BuildState.CANCELLED
    
```
```
await store.save(build)

```
```
    return {"status": "cancelled", "build_id": build_id}

@app.get(
```
```
"/v1/health")

```
```
async def health():
    return {"status": "ok", "version": "1.0.0"}

```
  
  
**7. Deployment Specification**  
**7.1 Docker Compose (Development)**  
**yaml**  
  
  
```
# docker-compose.yml
version
```
```
: '3.8'

```
```

services:
  
```
```
redis:

```
```
    image: redis:7-alpine
    ports:
      - "6379:6379"
    
```
```
volumes:

```
```
      
```
```
- redis_data:/data

```
```
    
```
```
command: redis-server --appendonly yes

```
```

  api:
    
```
```
build: .

```
```
    
```
```
ports:

```
```
      
```
```
- "8000:8000"

```
```
    
```
```
environment:

```
```
      
```
```
- REDIS_URL=redis://redis:6379

```
```
      
```
```
- DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}

```
```
      
```
```
- KIMI_API_KEY=${KIMI_API_KEY}

```
```
      
```
```
- API_KEY=${API_KEY:-dev-key-change-me}

```
```
      
```
```
- NOTIFICATION_WEBHOOK=${NOTIFICATION_WEBHOOK}

```
```
    
```
```
depends_on:

```
```
      
```
```
- redis

```
```
    
```
```
restart: unless-stopped

```
```

volumes
```
```
:

```
```
  redis_data:

```
  
**7.2 Dockerfile**  
**dockerfile**  
  
  
```
FROM python:3.11-slim

WORKDIR /app

RUN
```
```
 apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

```
```

COPY
```
```
 requirements.txt .

```
```
RUN
```
```
 pip install --no-cache-dir -r requirements.txt

```
```

COPY
```
```
 app/ ./app/

```
```

CMD
```
```
 ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]

```
  
**7.3 Requirements**  
**plain**  
  
  
```
fastapi==0.109.0
uvicorn[standard]==0.27.0
aiohttp==3.9.3
redis==5.0.1
python-dotenv==1.0.0
tenacity==8.2.3
pydantic==2.6.0

```
  
**7.4 Production: Railway (One-Click Deploy)**  
1. Push repo to GitHub  
2. Connect Railway project  
3. Add Redis plugin (one click)  
4. Set environment variables in Railway dashboard  
5. Deploy  
## Scaling: Railway auto-scales containers. Set workers in uvicorn to CPU cores * 2 + 1.  
**7.5 Production: Kubernetes (Scale)**  
**yaml**  
  
  
```
# k8s-deployment.yaml
apiVersion
```
```
: apps/v1

```
```
kind: Deployment
metadata
```
```
:

```
```
  
```
```
name: swarm-api

```
```
spec
```
```
:

```
```
  
```
```
replicas: 3

```
```
  
```
```
selector:

```
```
    matchLabels:
      
```
```
app: swarm-api

```
```
  
```
```
template:

```
```
    
```
```
metadata:

```
```
      
```
```
labels:

```
```
        
```
```
app: swarm-api

```
```
    
```
```
spec:

```
```
      containers:
      - name: api
        image: your-registry/swarm-harness:latest
        
```
```
ports:

```
```
        
```
```
- containerPort: 8000

```
```
        
```
```
env:

```
```
        
```
```
- name: REDIS_URL

```
```
          
```
```
valueFrom:

```
```
            
```
```
secretKeyRef:

```
```
              
```
```
name: app-secrets

```
```
              key: redis-url
        
```
```
- name: DEEPSEEK_API_KEY

```
```
          
```
```
valueFrom:

```
```
            secretKeyRef:
              name: app-secrets
              
```
```
key: deepseek-key

```
```
        
```
```
- name: KIMI_API_KEY

```
```
          
```
```
valueFrom:

```
```
            secretKeyRef:
              
```
```
name: app-secrets

```
```
              
```
```
key: kimi-key

```
```
        resources:
          
```
```
requests:

```
```
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            
```
```
cpu: "500m"

```
```
---
apiVersion: v1
kind
```
```
: Service

```
```
metadata
```
```
:

```
```
  
```
```
name: swarm-api-service

```
```
spec:
  
```
```
selector:

```
```
    app: swarm-api
  ports:
  
```
```
- port: 80

```
```
    targetPort: 8000
  type: LoadBalancer

```
  
  
**8. Cost & Token Management**  
**Table**  
  
  
  

| Guard | Implementation | Trigger |
| ------------------ | --------------------------------------------------------------- | -------------------------------- |
| Per-step budget | agent.token_budget | Hard limit per agent |
| Per-build budget | build.token_budget_total | Hard limit per swarm |
| Rate limit | Redis counter per API key | 10 builds/minute |
| Model swap on cost | If DeepSeek fails 3x, fallback to Kimi | Circuit breaker |
| Auto-downgrade | Use deepseek-chat instead of deepseek-reasoner for simple steps | Heuristic based on prompt length |
  
****Estimated cost per build:****  
* Simple build (3 agents, 15K tokens): ~$0.08 (DeepSeek) + $0.15 (Kimi) = **$0.23**  
* Complex swarm (5 agents, 40K tokens): ~$0.25 (DeepSeek) + $0.40 (Kimi) = **$0.65**  
  
**9. Operations & Monitoring**  
**9.1 Health Checks**  
**bash**  
  
  
```
curl https://api.yourdomain.com/v1/health
# {"status": "ok", "version": "1.0.0"}
```
```


```
  
**9.2 Redis Inspection**  
**bash**  
  
  
```
# List active builds
redis-cli KEYS 
```
```
"swarm:build:*"

```
```

# Check build state
redis-cli GET 
```
```
"swarm:build:a3f7b2d9e8c1" | jq '.state'

```
  
**9.3 Log Aggregation**  
**Use structured JSON logging:**  
**Python**  
  
  
```
import logging
import
```
```
 json

```
```

def
```
```
 log_build_event(build_id: str, event: str, data: dict):

```
```
    logging.info(json.dumps({
        
```
```
"build_id": build_id,

```
```
        
```
```
"event": event,

```
```
        
```
```
"timestamp": datetime.utcnow().isoformat(),

```
```
        
```
```
**data

```
```
    
```
```
}))

```
  
  
**10. Implementation Roadmap**  
**Table**  
  
  
  

| Phase  | Duration   | Deliverable                                           |
| ------ | ---------- | ----------------------------------------------------- |
| Week 1 | Days 1–3   | Core harness + LLM router + Redis persistence         |
| Week 1 | Days 4–5   | FastAPI + state machine + basic notifications         |
| Week 2 | Days 6–8   | Swarm coordinator + parallel execution + cross-review |
| Week 2 | Days 9–10  | Human-in-the-loop gates + resume logic                |
| Week 3 | Days 11–12 | Token budgets + circuit breakers + cost guards        |
| Week 3 | Days 13–14 | Docker Compose + Railway deploy + K8s manifests       |
| Week 4 | Days 15–17 | WebSocket streaming + web UI (optional)               |
| Week 4 | Days 18–21 | Load testing + monitoring + docs                      |
  
**11. Security Checklist**  
* [ ] API keys via headers, rotated monthly  
* [ ] Redis password + TLS in production  
* [ ] LLM API keys stored as K8s secrets / Railway secrets  
* [ ] No user prompt injection into system prompts (sanitize)  
* [ ] Code execution sandboxed (Docker / gVisor) if using execute_python tool  
* [ ] Rate limiting per API key (Redis counter)  
* [ ] Build data encrypted at rest (Redis AOF)  
* [ ] CORS restricted to known domains in production  
  
**12. CLI Client (For Your Use)**  
**Python**  
  
  
```
#!/usr/bin/env python3
# swarm-cli.py
import
```
```
 sys

```
```
import requests
import
```
```
 time

```
```

BASE 
```
```
= "https://your-api.railway.app"

```
```
API_KEY 
```
```
= "your-api-key"

```
```

def
```
```
 submit(prompt: str):

```
```
    r = requests.post(
        
```
```
f"{BASE}/v1/build",

```
```
        headers={"X-API-Key": API_KEY},
        json={
            
```
```
"prompt": prompt,

```
```
            
```
```
"agents": [

```
```
                
```
```
{"role": "planner", "provider": "deepseek", "model": "deepseek-chat"},

```
```
                {"role": "coder", "provider": "kimi", "model": "kimi-k3"},
                
```
```
{"role": "reviewer", "provider": "deepseek", "model": "deepseek-chat"},

```
```
                
```
```
{"role": "merger", "provider": "kimi", "model": "kimi-k3"}

```
```
            
```
```
],

```
```
            
```
```
"token_budget": 40000,

```
```
            "slack_webhook": "https://hooks.slack.com/..."
        }
    
```
```
)

```
```
    data 
```
```
= r.json()

```
```
    
```
```
print(f"🚀 Build {data['build_id']} started")

```
```
    
    while True:
        status = requests.get(f"{BASE}/v1/build/{data['build_id']}", headers={"X-API-Key": API_KEY}).json()
        
        
```
```
if status["needs_human"]:

```
```
            print(f"\n🛑 {status['human_question']}")
            resp = input("> ")
            requests
```
```
.post(

```
```
                
```
```
f"{BASE}/v1/build/{data['build_id']}/respond",

```
```
                headers
```
```
={"X-API-Key": API_KEY},

```
```
                json={"response": resp}
            )
            
```
```
print("▶️ Resuming...")

```
```
        elif status["state"] == "completed":
            
```
```
print(f"\n✅ DONE\n{status['final_output']}")

```
```
            break
        
```
```
elif status["state"] == "failed":

```
```
            print(f"\n❌ FAILED\n{status['errors']}")
            
```
```
break

```
```
        
        time.sleep(3)

if
```
```
 __name__ == "__main__":

```
```
    submit(sys.argv[1])

```
  
