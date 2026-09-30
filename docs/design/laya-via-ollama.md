# Laya through the managed Ollama runtime

Ollama can serve both advisory chat models and decision models. FlintTrade should use the existing managed Ollama runtime for the Laya decision role, instead of a separate Laya sidecar, once a gate benchmark passes. Until then the sidecar stays the default and keeps working.

The switch is `FLINTTRADE_LAYA_BACKEND`. Unset, blank, and `sidecar` use the sidecar. `ollama` uses the route in this note. Any other value is an error: the process logs it once and pauses new orders. It does not fall back to the sidecar. A typo must not keep admitting.

This spike does not change the managed Ollama pin. That pin is v0.32.0. Decision-model calls need Ollama v0.35 or later, so a `systemone` entry stays fail-closed on the current pin.

## 1. What calls the model, and the seam

A new order reaches `Laya.admit` before SafetySystem and before `gate_order`. The deterministic floor still owns symbol, exchange, side, quantity, order type, product, price, and trigger. Example orders are refused there. Connected (read) does not place. Practice and Live continue only when this gate allows them.

When the floor has passed and a note is present, `evaluate_free_text` in `laya_decision.py` calls `client.decide(state, questions)`. That is the only model call. Today the client is `SystemOneClient`, and its POST goes to the sidecar at `/v1/systemone` with a 3.0 second timeout. `Laya.admit` maps `DecisionCallError` onto a refusal or Down.

The Ollama backend replaces that client only. `decide` still receives the same state and the same three questions. The sidecar client is not edited. Advisory chat (`LLMClient`, `/v1/chat/completions`, and any other advisory path) is not this client and must never be passed in.

## 2. Fail-closed rules that stay

Any of the following refuses the new order. None of them admit. Closing a position is a server-proven reduce-only exit (`admit_reduce_only`). That path does not call the model, and Down does not block it.

The operator sentence stays: "Laya is Down. New orders are paused until it's Ready. You can still close positions."

| Condition | Result |
|---|---|
| Model missing | Down, download state. No place. |
| Digest missing, unparseable, or not on the allowlist | Down. Chip: Can't verify the model. |
| Digest present and not the pinned digest | Down. Chip: Wrong model version. |
| Runtime stopped, not owned, or changing state | Down. |
| Call exceeds 3.0 seconds | Down. Chip: Unreachable. |
| Malformed or non-schema output | Down. |
| Note longer than 4,000 characters | Same as today: that order is refused with "The note is too long to admit." The model is not called. The gate is not flipped to Down by the note length alone. |
| Prompt over 8,192 tokens | Same refusal as the 4,000-character note. The model is not called. |
| `systemone` route while the managed server is older than v0.35 | Down. Chip: Can't verify the model. |
| Any other error | Down. No admit. |

The 3.0 second timeout is the existing `SystemOneClient` default. It is also the p95 latency the Ollama route has to meet. The benchmark measures that; this spike does not relax the timeout.

## 3. Model identity

An allowlist entry is a tag, a pinned SHA-256 digest, and a route. The tag is not the proof. There is no shipped entry in this spike. Nothing is added without a confirmed licence.

`tev1:4b` and `tev1:0.8b` are trial only, licence unconfirmed. They are not on the allowlist. `nimble:9b` is a `systemone` candidate and is not on the allowlist either; its licence is not reviewed here. `qwen3:8b` is the advisory default and the `chat` candidate. It is not on the allowlist until a digest is reviewed and pinned. Its weights licence is Apache-2.0; that does not by itself admit it.

On every admission the gate opens one `ManagedOllamaAdmission` and holds it for the whole inference. The digest Ollama reports for that call is compared with the pinned digest for the tag. A tag pulled again onto new weights fails the comparison. The chip shows Wrong model version. The response body is not allowed to vouch for itself.

Docs and any new explanation use this sentence. The chip label and the existing tooltip stay as they are ("Wrong model version", and "Laya is running a different model than FlintTrade expects."):

> FlintTrade checks the digest Ollama reports for the exact model tag on every admission. The tag is not the proof. If that digest does not match the pinned digest, the gate shows Wrong model version and new orders stay paused. You can still close positions.

The gate model tag is `FLINTTRADE_LAYA_OLLAMA_MODEL`. It is not the advisory model in Settings. If the tag is unset or not on the allowlist, the gate stays unverified and does not call the model.

## 4. Determinism, and what the model is asked

The model answers only the three free-text questions already in `questions_for_note`:

1. Does the note state a concrete reason?
2. Does the note show tilt, revenge, or chasing losses?
3. Does the stated plan contradict the order side?

Expiry, quantity, price, and symbol stay on the floor. The route is chosen per allowlist entry, not for the whole process.

`chat` is `POST /api/chat` on the admitted loopback endpoint. It is for plain models such as `qwen3:8b`, which are asked for JSON. Options are temperature 0, seed 0, `num_ctx` 8192, and a small `num_predict`. `format` is a strict schema: three answers, each with option probabilities for A and B. There is no confidence field in the schema.

`systemone` is `POST /v1/systemone` on that same admitted endpoint. It is for decision models (`nimble:9b`, and the tev1 tags above once a licence and a digest exist). The request sends the same three choice questions. The response is mapped onto the thresholds already in `laya_policy.toml`: `deny_at` 0.80 and `abstain_at` 0.55, per question, on the deny option.

- A `choice` answer uses `probabilities` for A and B. The `choice` label is not the gate.
- A `noul` answer uses `noul` as the probability that the deny condition holds, and that number is compared with the same two thresholds.
- `confidence` is not a probability that the answer is right. It is ignored. A policy or a payload that asks the gate to threshold `confidence` is rejected.

Vendor accuracy and latency figures are unverified. They are not an argument for turning the flag on.

Nothing returned by an advisory model, including a `systemone` body produced for chat, is an admission. The gate reads only the response from its own call inside the admission.

## 5. Chip copy

The locked sentences do not change. The Ollama snapshot fills the same reason codes the desk already renders.

| Chip | Ollama source |
|---|---|
| Checking Laya… | Managed server `state` is `starting`, or the desk has not confirmed a start or stop. New orders stay paused. The desk already shows this from the unconfirmed window. |
| Downloading the model · X of Y GB | A model pull's completed and total bytes, or the runtime archive download while the server itself is downloading. A missing model uses this state; totals stay 0 until Ollama reports them. |
| Can't download the model | The pull or the runtime download failed. |
| Wrong model version | The reported digest is not the pinned digest, the pull is waiting for digest acceptance because the weights changed, or the model store records digest drift for that tag. |
| Can't verify the model | No digest, a digest that is not 64 hex characters, an integrity failure, an allowlist miss, or `systemone` on a server older than v0.35. |
| Ready | The owned server is ready, the tag is accepted, and the digest matches. Practice can admit, subject to the floor and the three questions. Live stays unqualified in this spike. |
| Down | Stopped, not installed, not owned, conflict, timeout, malformed output, or any other error. |

Degraded remains a sidecar state. This route does not invent a Degraded reason.

## 6. What happens to the sidecar

This spike removes nothing. The sidecar keeps its start token, its port, its key file, and its process supervision. `record_belongs_to_running_sidecar` and `reconcile_watched_state` still apply when the flag is `sidecar`.

When the flag is `ollama`, admission and the desk heartbeat read the managed Ollama snapshot instead of the sidecar. The sidecar process is left alone.

Migration: the flag stays off until the benchmark in section 7 meets the owner's bar. Rollback is setting the flag back to `sidecar` or unsetting it. No data migration is required.

Later, after that bar is met and the default flips, the sidecar's start token, private port, and supervised process can be removed. Not in this change.

## 7. Benchmark precondition

The Ollama route must not become the default until an offline benchmark counts wrong admits and wrong denies separately and shows zero wrong admits. Abstains are a third count. They are not admits. Vendor numbers are unverified and do not satisfy this bar.

The harness calls the same seam as the gate (`evaluate_free_text` and the decision client), not SafetySystem and not `gate_order`. It does not need a live broker.

```bash
python -m flinttrade_engine.laya_benchmark --cases PATH --repeats N
```

`PATH` is JSONL. One JSON object per line:

- `id`, `pair_id`
- `split`: `dev` or `test`
- `question`: `rationale`, `tilt`, or `side`
- `note`
- `order`: action, symbol, exchange, quantity, mode
- `label`: `admit`, `deny`, or `clamp`

The report prints, per question and overall: `n`, `n` for each label, wrong admits, wrong denies, abstains, separate Down counts, p50 and p95 latency in milliseconds, and how many cases kept the same effect across `N` repeats. With zero wrong admits, `n` deny-labelled cases bound the true wrong-admit rate at about `3/n` at 95%. The report prints that `n` and that bound. The Researcher supplies the real labelled set. This repo ships only a tiny synthetic fixture so the harness can run with a stubbed Ollama. Those rows are examples. They are not the benchmark.

A wrong admit is a full allow when the label is `deny` or `clamp`. A wrong deny is a deny when the label is `admit`. A clamp is an abstain. Whether a deny of a `clamp` label should also count as a wrong deny is open; this harness counts it as a wrong deny so over-refusal is visible, and it never counts it as a wrong admit.

## 8. Risks and open questions

One Ollama process serves advisory chat and this gate. A chat turn can occupy the single inference slot, evict the gate model, or change keep-alive. A person can delete or swap the tag from Settings. The gate then fails closed on the next admission. It must not follow the advisory model name.

The runtime is local HTTP. The gate may call only the admitted loopback origin held by `ManagedOllamaAdmission`, with the proxy ignored, the same way the managed runtime already does. A response from any other host is not an admission.

The managed pin is v0.32.0, with pinned archive hashes. Moving it to v0.35 or later is a separate review of those hashes and of the install size. Until that lands, `systemone` cannot be Ready.

Open:

- No reviewed digest is pinned yet. The shipped allowlist is empty, so `ollama` pauses new orders until an entry is added.
- `tev1` licence is unconfirmed (trial only). `nimble` licence is not reviewed here.
- Live qualification is still the sidecar's revision, weight digest, and policy version. An Ollama digest does not qualify Live in this spike.
- The 8,192-token check estimates tokens as UTF-8 bytes divided by 4. It is not the model's own tokenizer. The two can disagree near the cap. Over the estimate, the order is refused.
- Decision-model probabilities can differ between CPU and GPU. That is a vendor note and is unverified here.
- The owner's bar is zero wrong admits. The size of the deny-labelled set, and whether Practice and Live share one bar, is the Researcher's call.

The Tester should cover: flag off leaves every current place and chip path unchanged; each fail-closed drill above ends in Down or a refusal; a digest mismatch shows Wrong model version; a missing model shows the download line; a timeout and malformed JSON refuse; a note over 4,000 characters and a prompt over 8,192 tokens refuse without a model call; closing a position still admits; `confidence` cannot flip a verdict; an advisory completion cannot reach `decide`; `chat` and `systemone` are selected by the allowlist entry; an unknown flag value pauses new orders; the harness prints separate wrong-admit, wrong-deny, and abstain counts on the example fixture with a stub.
