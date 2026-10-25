"""Repeatable JSON benchmark harness for an OpenAI-compatible inference server.

This measures request latency and provider-reported usage; it does not claim
semantic correctness. Each call gets unique lineage IDs and is never retried.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import statistics
import sys
import time
import uuid

from provider import InferenceRequest, infer


def percentile(values: list[int], percentile_value: float) -> float | None:
    """Nearest-rank percentile, with deterministic behavior for small samples."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, int((percentile_value * len(ordered) + 99) // 100))
    return float(ordered[min(rank, len(ordered)) - 1])


def summarize(receipts: list[dict]) -> dict:
    states = [r.get("state") for r in receipts]
    elapsed = [r["elapsed_ms"] for r in receipts
               if isinstance(r.get("elapsed_ms"), int)]
    total_tokens = [
        r["usage"]["total_tokens"] for r in receipts
        if isinstance(r.get("usage"), dict)
        and isinstance(r["usage"].get("total_tokens"), int)
    ]
    if "BLOCKED" in states:
        state = "BLOCKED"
    elif any(s != "OBSERVED" for s in states):
        state = "UNKNOWN"
    else:
        state = "OBSERVED"
    return {
        "state": state,
        "runs": len(receipts),
        "observed_runs": sum(s == "OBSERVED" for s in states),
        "unknown_runs": sum(s == "UNKNOWN" for s in states),
        "blocked_runs": sum(s == "BLOCKED" for s in states),
        "latency_ms": {
            "min": min(elapsed) if elapsed else None,
            "median": statistics.median(elapsed) if elapsed else None,
            "p95": percentile(elapsed, 95),
            "max": max(elapsed) if elapsed else None,
        },
        "provider_total_tokens": sum(total_tokens) if total_tokens else None,
    }


def run_benchmark(args: argparse.Namespace) -> dict:
    run_id = uuid.uuid4().hex
    api_key = os.environ.get(args.api_key_env) if args.api_key_env else None
    warmup_receipts = []
    measured_receipts = []

    for index in range(args.warmup + args.runs):
        phase = "warmup" if index < args.warmup else "measured"
        sequence = index if phase == "warmup" else index - args.warmup
        request = InferenceRequest(
            decision_id=f"benchmark:{run_id}",
            permit_id=args.permit_id,
            effect_id=f"benchmark:{run_id}:{phase}:{sequence}",
            attempt_id=f"attempt:{run_id}:{phase}:{sequence}",
            model=args.model,
            prompt=args.prompt,
            base_url=args.base_url,
            timeout_seconds=args.timeout,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
        )
        receipt = infer(request, api_key=api_key).to_dict()
        receipt["phase"] = phase
        (warmup_receipts if phase == "warmup" else measured_receipts).append(receipt)

    return {
        "schema_version": "1.0",
        "benchmark_id": run_id,
        "provider": "kyojin-openai-compatible",
        "endpoint": args.base_url.rstrip("/"),
        "model": args.model,
        "configuration": {
            "runs": args.runs,
            "warmup": args.warmup,
            "timeout_seconds": args.timeout,
            "max_tokens": args.max_tokens,
            "temperature": args.temperature,
        },
        "warmup": {
            "runs": len(warmup_receipts),
            "receipts": warmup_receipts,
        },
        "measurement": {
            **summarize(measured_receipts),
            "receipts": measured_receipts,
        },
        "interpretation": (
            "OBSERVED means valid provider responses were received; it does not "
            "prove semantic correctness or hardware performance outside this run."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--model", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--permit-id", required=True,
                        help="Permit identifier supplied by the governing caller")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--max-tokens", type=int, default=128)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--api-key-env", default="KYOJIN_API_KEY",
                        help="Environment variable holding API key; pass empty to disable")
    parser.add_argument("--output", type=Path, default=Path("kyojin-benchmark.json"))
    args = parser.parse_args(argv)
    if args.runs < 1 or args.warmup < 0:
        parser.error("--runs must be >= 1 and --warmup must be >= 0")
    if args.timeout <= 0 or args.max_tokens < 1:
        parser.error("--timeout must be > 0 and --max-tokens must be >= 1")
    report = run_benchmark(args)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
    print(json.dumps({
        "state": report["measurement"]["state"],
        "runs": report["measurement"]["runs"],
        "observed_runs": report["measurement"]["observed_runs"],
        "unknown_runs": report["measurement"]["unknown_runs"],
        "blocked_runs": report["measurement"]["blocked_runs"],
        "output": str(args.output),
    }, ensure_ascii=False))
    return 0 if report["measurement"]["state"] == "OBSERVED" else 2


if __name__ == "__main__":
    sys.exit(main())
