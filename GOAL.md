# Goal

Deploy publicly and reach 1m paying customers

## Roadmap

### M1 — Deploy publicly
- [x] Railway deploy via the existing railway.json + root Dockerfile; verify /v1/health on the public URL
- [ ] Production env: APP_API_KEY (not dev-key-change-me), REDIS_URL, DEEPSEEK_API_KEY, KIMI_API_KEY, NOTIFICATION_WEBHOOK
- [ ] Restrict CORS from all origins (README "Current limitations")
- [ ] End-to-end smoke: one prompt → planned → coded → reviewed → merged build from the deployed instance
*Definition of done:* a public URL serves /v1/health and a real build completes against the deployed instance.

### M2 — Billing and quotas
- [ ] Enforce per-user quotas via DEFAULT_TOKEN_BUDGET, DAILY_TOKEN_BUDGET, MAX_CONCURRENT_BUILDS (app/config.py)
- [ ] Usage metering: token spend per build and per user exposed for billing
- [ ] Payment integration (Stripe) with plan tiers; hard spend cap / kill switch
*Definition of done:* free-tier users are blocked at quota with a clear upgrade path; spend is metered and invoiced.

### M3 — Landing page and signup
- [ ] Product landing page (positioning, pricing, examples/)
- [ ] Signup + API key management
- [ ] Onboarding: first build from the web UI (swarm-harness/app/static)
- [ ] Quickstart + API reference docs
*Definition of done:* a new user signs up and runs a first build unattended.

### M4 — Production hardening and stability
- [ ] Durable out-of-process queue — worker/consumer.py only rescues builds still in `queued`; in-flight builds die with the API process (README "Current limitations")
- [ ] Real sandboxed execute_python and web_search backends — tools are repo-bound today (app/tool_registry.py registers only read_file/list_files/write_file/commit)
- [ ] Per-provider rate limiting / throughput management (single-lock serialization in app/llm_router.py)
- [ ] Monitoring, error tracking and alerts; explicit build-expiry policy (7-day Redis TTL today)
*Definition of done:* an API crash does not lose in-flight builds; an SLO is defined and monitored.

### M5 — Growth to 1m paying customers
- [ ] Pricing tiers + usage-based billing live (from M2)
- [ ] Integrations: CI pipeline step, Slack/chat, webhooks
- [ ] Referral/affiliate program + content marketing
- [ ] Retention: notifications, human-gate UX polish, examples gallery
*Definition of done:* paying customer count and funnel metrics are tracked and growing month over month.
