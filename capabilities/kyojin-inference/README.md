# Kyojin OpenAI-Compatible Inference Adapter

Status: **ADAPT prototype; not yet absorbed into AIOS core**.

This standard-library adapter targets Kyojin's OpenAI-compatible chat completions
endpoint (default local base URL: `http://127.0.0.1:8000/v1`). It is deliberately
provider-neutral at the contract boundary so another compatible server can be substituted.

## Contract

The caller supplies the governance identifiers `decision_id`, `permit_id`,
`effect_id`, and `attempt_id`. The adapter does not mint authority, validate a
permit, persist memory, or declare model output correct. Those remain AIOS control-plane
responsibilities.

- `BLOCKED`: request rejected before dispatch (for example, missing lineage).
- `OBSERVED`: a successful HTTP response with the expected response shape was received.
  This is transport/protocol evidence, **not semantic verification**.
- `UNKNOWN`: timeout/transport failure, HTTP error, or malformed provider response.
  A request may have completed remotely despite a local timeout.

The adapter never retries automatically. A retry must be a new, separately authorized
attempt with a new `attempt_id`, after the control plane reconciles the previous attempt.
Do not translate UNKNOWN to FAIL or PASS.

Successful output includes a SHA-256 digest and integer token-usage fields returned by
the provider. The digest binds the receipt to the exact output but does not establish truth.

## Direct usage

```python
from provider import InferenceRequest, infer

request = InferenceRequest(
    decision_id="decision-from-aios",
    permit_id="permit-from-aios",
    effect_id="inference-effect-123",
    attempt_id="attempt-1",
    model="Qwen3.8-Flash-Next",
    prompt="Summarize this text.",
    base_url="http://127.0.0.1:8000/v1",
)
receipt = infer(request, api_key=None)
print(receipt.to_dict())
```

For remote deployment, use HTTPS and pass API keys through a secret manager/environment
boundary; never commit secrets or include them in receipts.

## Repeatable benchmark receipt

With a Kyojin server running locally:

```sh
python capabilities/kyojin-inference/benchmark.py \
  --model Qwen3.8-Flash-Next \
  --prompt "Reply with exactly: OK" \
  --permit-id <permit-issued-by-governance> \
  --warmup 1 --runs 5 \
  --output kyojin-benchmark.json
```

Set `KYOJIN_API_KEY` only if the server requires it. The JSON report records the
configuration, individual per-attempt receipts, output hashes, provider usage, and
min/median/p95/max latency. Each request has distinct effect and attempt identifiers.
The benchmark exits nonzero unless every measured call is OBSERVED. That state means
valid responses were received; it does not establish semantic correctness or generalize
performance beyond the recorded run. The script never retries a call.

## Verification

Run CPU-only contract tests:

```sh
python -m py_compile capabilities/kyojin-inference/provider.py \
  capabilities/kyojin-inference/benchmark.py
python -m unittest discover -s capabilities/kyojin-inference/tests -v
```

Tests use fake transports and summary fixtures; they need no ROCm, GPU, Kyojin process,
or model weights. They prove adapter and receipt behavior only.

## Absorb gate

Do not merge this into AIOS core until:
1. AIOS binds requests to a verified DECISION and authorized permit.
2. Invocation is possible only after authority validation.
3. Receipts are persisted through the existing durable state/CONTINUE_CONTRACT path.
4. Restart recovery and duplicate-attempt reconciliation are tested.
5. A live Kyojin smoke test and repeatable benchmark receipt are recorded on supported hardware.
6. Output verification remains separate from provider transport observation.
