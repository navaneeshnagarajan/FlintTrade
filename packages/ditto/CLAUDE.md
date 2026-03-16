# FlintTrade — ditto

> Multi-broker, multi-account trade orchestration, position mirroring, margin-aware allocation

## Absorbs
- algomirror → Multi-account handler (301 commits), trailing SL, Supertrend exits, margin calculator, trade quality grading, ThreadPoolExecutor parallel execution, risk manager

## Depends on: core, engine

## Rules
- Read root CLAUDE.md for project-wide rules
- Use packages/core/src/openalgo_client.py for ALL OpenAlgo API calls
- Never reference specific brokers
- Write tests in tests/test_ditto.py
- Log work in root DEVLOG.md
- Branch: feature/ditto-{description}
