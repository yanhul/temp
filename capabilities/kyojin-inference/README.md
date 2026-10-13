# Kyojin OpenAI-Compatible Inference Adapter

Status: **ADAPT prototype; not yet absorbed into AIOS core**.

This small standard-library adapter targets Kyojin's OpenAI-compatible chat
completions endpoint (default local base URL: `http://127.0.0.1:8000/v1`).
It is deliberately provider-neutral at the contract boundary so another
OpenAI-compatible server can be substituted.

## Contract

The caller supplies the existing governance identifiers:
`decision_id`, `permit_id`, `effect_id`, and `attempt_id`. The adapter
does not mint authority, decide whether a permit is valid, persist memory, or
declare model output correct. Those remain AIOS control-plane responsibilities.

Each call returns a receipt with:
- `BLOCKED`: request rejected before dispatch (for example missing lineage).
- `OBSERVED`: a successful HTTP response with the expected response shape was
  received. This is transport/protocol evidence, **not semantic verification**.
- `UNKNOWN`: timeout/transport failure, HTTP error, or malformed provider
  response. A request may have completed remotely despite a local timeout.

The adapter never retries automatically. A retry must be a new, separately
authorized attempt with a new `attempt_id`, and must reconcile the prior
attempt before the control plane decides what to do. Do not translate UNKNOWN
to FAIL or PASS.

Successful output includes a SHA-256 digest and any integer token-usage fields
returned by the provider. The digest binds the receipt to the exact output but
does not establish truth or quality.

## Usage

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

For a remote deployment, use HTTPS and provide the API key through a secret
manager/environment boundary; do not commit secrets or include them in receipts.
The default local URL is suitable only for a local Kyojin server.

## Verification

Run the CPU-only contract tests:

```sh
python -m unittest discover -s capabilities/kyojin-inference/tests -v
```

Tests use a fake transport; they do not require ROCm, a GPU, Kyojin, or model
weights. They prove adapter behavior only. End-to-end model performance and
semantic correctness are not claimed.

## Absorb gate

Do not merge this into AIOS core until:
1. AIOS binds the request to a verified DECISION and authorized permit.
2. The adapter is invoked only after authority validation.
3. Receipt persistence uses the existing durable state/CONTINUE_CONTRACT path.
4. Restart recovery and duplicate-attempt reconciliation are tested.
5. A live Kyojin smoke test and repeatable benchmark receipt are recorded.
6. Output verification is separate from provider transport observation.
