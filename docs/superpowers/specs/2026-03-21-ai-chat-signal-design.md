# FlintTrade AI Chat + Signal System — Design Spec

**Date:** 2026-03-21
**Goal:** Wire the existing AI modules (2,280 lines, 57 tests) into a working chat + signal system
**Approach:** Integration work — no new AI modules needed, just wiring and activation

---

## 1. NVIDIA Build Provider (LLMClient addition)

Add `nvidia` to the existing provider enum in `packages/ai/src/llm_client.py`.
- Base URL: `https://integrate.api.nvidia.com/v1`
- Model: `nvidia/nemotron-3-super-120b-a12b` (default)
- Auth: API key from workspace.json `llm.api_key_ref`
- Protocol: OpenAI-compatible (same as existing openai provider logic)
- Free tier: 1,000 credits, 40 req/min

## 2. Chat Memory (conversation history)

### Backend (`packages/core/src/app.py`)
- Change `/api/v1/advisor` to accept `messages: [{role, content}]` array instead of single `message` string
- Keep backward compat: if `message` field present, wrap in array
- Pass full message history to `LLMClient.chat(messages)`
- System prompt prepended automatically

### Frontend (`AIAdvisorWidget.tsx`)
- Store message history in component state (already does this for display)
- On send: POST the full `messages` array (all user + assistant messages)
- Persist to localStorage key `flinttrade:chat-history` (survive refresh)
- "Clear chat" button to reset history

## 3. Streaming Responses (SSE)

### Backend
- New endpoint: `GET /api/v1/advisor/stream` (SSE)
- Accepts same params as `/advisor` but streams tokens via `text/event-stream`
- Uses `LLMClient.chat_stream()` (already exists in llm_client.py)
- Each SSE event: `data: {"token": "..."}\n\n`
- Final event: `data: {"done": true}\n\n`

### Frontend
- When user sends message, use `EventSource` or `fetch` with ReadableStream
- Append tokens to the assistant message bubble as they arrive
- Show typing indicator until first token

## 4. RAG Context Injection

### Initialization
- On first Flask app startup, check if ChromaDB collection `flinttrade_docs` exists
- If not, index: `docs/*.md`, `packages/*/README.md`, `packages/ai/src/*.py` docstrings
- Use `RAGEngine.index_directory()` (already built)

### Query flow
- Before calling LLM, retrieve top-3 relevant chunks from RAG
- Inject as system context: "Relevant documentation:\n{chunks}"
- User doesn't see this — it's behind the scenes

## 5. MCP Tool Calls in Chat

### Backend
- Register MCP handlers in `app.py` for: place_order, get_positions, get_quotes, option_chain
- When user says "Buy NIFTY 2 lots", MCPBridge.parse_order_command() extracts the intent
- Return structured response: `{"type": "tool_call", "tool": "place_order", "params": {...}, "confirmation_required": true}`

### Frontend
- When response has `type: "tool_call"`, show confirmation card in chat:
  - "AI wants to: BUY NIFTY 2 lots at MARKET"
  - [Approve] [Reject] buttons
- On Approve: POST to `/api/v1/placeorder` (via OpenAlgo proxy)
- On Reject: Show "Order cancelled" message

## 6. Signal Pipeline

### New file: `packages/ai/src/pipeline.py`
- `SignalPipeline` class with `run_cycle()` method
- Cycle: fetch bars (OpenAlgo history API) → compute indicators → predict signal → emit

### Scheduler
- In `packages/core/src/app.py`, add APScheduler job
- Market hours (9:15-15:30): run every 5 minutes
- Off-hours: don't run
- Configurable: instruments, interval, indicators, threshold

### Output
- Signal result stored in memory (dict keyed by symbol)
- Exposed via `GET /api/v1/signals` endpoint
- Widget polls this endpoint or receives via WebSocket

## 7. Model Training

### On startup
- Check if model file exists at `~/.flinttrade/models/signal_model.joblib`
- If not, fetch 1 year of NIFTY 5-min bars from OpenAlgo history
- Train LightGBM with features (RSI, MACD, BB, EMA, OI) and labels (future 5-bar return)
- Save model to disk
- Log training metrics

### Overnight retrain
- APScheduler job at 00:00 IST
- Re-fetch latest data, retrain, save updated model

## 8. Settings UI for AI

### In Settings tool (`SettingsTool.tsx`)
- LLM Config section already exists
- Add provider dropdown: LM Studio, Ollama, NVIDIA Build, OpenAI, Anthropic, Groq, DeepSeek, Custom
- For NVIDIA: show API key input, default model `nemotron-3-super-120b-a12b`
- For LM Studio: show host input (default `http://127.0.0.1:1234`)
- Test connection button
- Save to settingsStore → workspace.json

---

## Files Modified/Created

| File | Change |
|------|--------|
| `packages/ai/src/llm_client.py` | Add nvidia provider |
| `packages/core/src/app.py` | Chat memory, SSE stream, RAG init, MCP handlers, signal endpoint |
| `packages/terminal/src/widgets/utility/AIAdvisor/AIAdvisorWidget.tsx` | Memory, streaming, MCP confirmation cards, clear chat |
| `packages/ai/src/pipeline.py` | NEW — signal pipeline scheduler |
| `packages/core/src/app.py` | Signal pipeline job, /api/v1/signals endpoint |
| `packages/terminal/src/tools/Settings/SettingsTool.tsx` | Provider dropdown with test connection |
