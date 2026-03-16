# FlintTrade — automation

> ML pipeline, cron, Telegram bot, OpenClaw agent, TOTP auto-login, post-market analysis

## Absorbs
- OpenClaw (infra/openclaw/) → AI agent gateway, Telegram/WhatsApp/Discord, heartbeats, skills

## Depends on: core, engine, ai, data

## Rules
- Read root CLAUDE.md for project-wide rules
- Use packages/core/src/openalgo_client.py for ALL OpenAlgo API calls
- Never reference specific brokers
- Write tests in tests/test_automation.py
- Log work in root DEVLOG.md
- Branch: feature/automation-{description}

## TOTP auto-login
- Use pyotp library to generate TOTP codes for daily broker auto-login
- Cron job at 8:30 AM IST: generate TOTP → login to OpenAlgo → verify session
- TOTP secret stored in .env (BROKER_TOTP_SECRET) — NEVER commit
- jugaad-data holidays() to skip weekends and NSE holidays
- pyotp + jugaad-data = invisible daily login
