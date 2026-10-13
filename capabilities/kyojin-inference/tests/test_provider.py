import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from provider import InferenceRequest, infer


def request(**overrides):
    values = dict(
        decision_id="dec-1", permit_id="permit-1", effect_id="effect-1",
        attempt_id="attempt-1", model="Qwen3.8-Flash-Next",
        prompt="Reply with OK", base_url="http://127.0.0.1:8000/v1",
    )
    values.update(overrides)
    return InferenceRequest(**values)


def successful_transport(url, body, headers, timeout):
    assert url == "http://127.0.0.1:8000/v1/chat/completions"
    assert json.loads(body)["model"] == "Qwen3.8-Flash-Next"
    assert headers["Content-Type"] == "application/json"
    return 200, json.dumps({
        "choices": [{"message": {"content": "OK"}}],
        "usage": {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5},
    }).encode()


class ProviderTests(unittest.TestCase):
    def test_valid_response_is_observed_and_hashed(self):
        receipt = infer(request(), transport=successful_transport)
        self.assertEqual(receipt.state, "OBSERVED")
        self.assertTrue(receipt.dispatched)
        self.assertEqual(receipt.output, "OK")
        self.assertEqual(len(receipt.output_sha256), 64)
        self.assertEqual(receipt.usage["total_tokens"], 5)
        self.assertEqual(receipt.attempt_id, "attempt-1")

    def test_missing_lineage_is_blocked_before_dispatch(self):
        called = []
        receipt = infer(request(permit_id=" "), transport=lambda *a: called.append(a))
        self.assertEqual(receipt.state, "BLOCKED")
        self.assertFalse(receipt.dispatched)
        self.assertEqual(called, [])

    def test_transport_failure_is_unknown_and_not_retried(self):
        calls = []
        def failing(*args):
            calls.append(args)
            raise ConnectionError("timeout")
        receipt = infer(request(), transport=failing)
        self.assertEqual(receipt.state, "UNKNOWN")
        self.assertTrue(receipt.dispatched)
        self.assertEqual(receipt.error_code, "TRANSPORT_UNKNOWN")
        self.assertEqual(len(calls), 1)

    def test_http_error_is_unknown_not_pass(self):
        receipt = infer(request(), transport=lambda *a: (503, b"unavailable"))
        self.assertEqual(receipt.state, "UNKNOWN")
        self.assertEqual(receipt.http_status, 503)
        self.assertIsNone(receipt.output)

    def test_malformed_success_response_is_unknown(self):
        receipt = infer(request(), transport=lambda *a: (200, b'{"choices":[]}'))
        self.assertEqual(receipt.state, "UNKNOWN")
        self.assertEqual(receipt.error_code, "INVALID_PROVIDER_RESPONSE")

    def test_unsafe_url_is_blocked(self):
        called = []
        receipt = infer(request(base_url="https://user:pass@example.test/v1"),
                        transport=lambda *a: called.append(a))
        self.assertEqual(receipt.state, "BLOCKED")
        self.assertEqual(called, [])

    def test_api_key_is_only_sent_as_bearer_header(self):
        seen = {}
        def transport(url, body, headers, timeout):
            seen.update(headers)
            return 200, b'{"choices":[{"message":{"content":"OK"}}]}'
        infer(request(), api_key="test-secret", transport=transport)
        self.assertEqual(seen["Authorization"], "Bearer test-secret")


    def test_non_finite_timeout_is_blocked_before_dispatch(self):
        called = []
        receipt = infer(request(timeout_seconds=float("nan")),
                        transport=lambda *a: called.append(a))
        self.assertEqual(receipt.state, "BLOCKED")
        self.assertFalse(receipt.dispatched)
        self.assertEqual(called, [])

    def test_non_finite_temperature_is_blocked_before_dispatch(self):
        called = []
        receipt = infer(request(temperature=float("inf")),
                        transport=lambda *a: called.append(a))
        self.assertEqual(receipt.state, "BLOCKED")
        self.assertFalse(receipt.dispatched)
        self.assertEqual(called, [])


if __name__ == "__main__":
    unittest.main()
