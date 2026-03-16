# FlintTrade — automation

> Cron scheduler, Telegram bot, OpenClaw agent bridge, post-market analysis

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

## Broker authentication
- Broker login (TOTP, OAuth, PIN) is handled by OpenAlgo, NOT FlintTrade
- FlintTrade connects to OpenAlgo via API key only
- If the OpenAlgo session expires, the dashboard notifies the user to
  re-authenticate at the OpenAlgo web interface
