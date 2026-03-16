# FlintTrade — ai

> LLM chat, RAG, ML signals, news sentiment, autonomous trading

## Absorbs
- openalgo-mcp → MCP natural language trading (15+ tools)
- openadvisor → CatBoost ML stock recommendations
- finnews-ai → financial news AI sentiment analysis

## Depends on: core, backtest-engine, historical

## Rules
- Read root CLAUDE.md for project-wide rules
- Use packages/core/src/openalgo_client.py for ALL OpenAlgo API calls
- Never reference specific brokers
- Write tests in tests/test_ai.py
- Log work in root DEVLOG.md
- Branch: feature/ai-{description}

## Additional reference
- MiroFish (github.com/666ghj/MiroFish) — swarm intelligence engine with multi-agent simulation, GraphRAG, agent memory (Zep). Reference for market crowd behavior modeling and scenario prediction.
