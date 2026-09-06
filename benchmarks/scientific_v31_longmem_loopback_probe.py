from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import httpx
from openai import AsyncOpenAI


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wavemind.evidence import attach_artifact_integrity


BASE_URL = "http://127.0.0.1:11435/v1"
MODEL = "mistral:7b"
MODEL_DIGEST = "f974a74358d62a017b37c6f424fcdf2744ca02926c4f952513ddf474b2fa5091"
OUTPUT = ROOT / "benchmarks" / "scientific_v31_longmem_loopback_probe_results.json"


def _request(client: httpx.Client, content: str, max_tokens: int) -> dict[str, object]:
    started = time.perf_counter()
    response = client.post(
        f"{BASE_URL}/chat/completions",
        json={
            "model": MODEL,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": max_tokens,
            "temperature": 0,
        },
    )
    return {
        "status": response.status_code,
        "elapsed_seconds": round(time.perf_counter() - started, 6),
        "response_bytes": len(response.content),
    }


async def _one_synthetic_request(index: int, repeats: int) -> dict[str, object]:
    client = AsyncOpenAI(
        base_url=BASE_URL,
        api_key="synthetic-loopback-probe",
        timeout=600.0,
        max_retries=0,
    )
    content = ("synthetic evidence token " * repeats) + "\nReply with exactly OK."
    started = time.perf_counter()
    try:
        response = await client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": content}],
            max_tokens=512,
            temperature=0,
        )
        return {
            "index": index,
            "synthetic_input_chars": len(content),
            "status": 200,
            "elapsed_seconds": round(time.perf_counter() - started, 6),
            "completion_tokens": response.usage.completion_tokens if response.usage else None,
            "response_chars": len(response.choices[0].message.content or ""),
        }
    except Exception as error:  # pragma: no cover - retained as diagnostic evidence
        return {
            "index": index,
            "synthetic_input_chars": len(content),
            "status": getattr(error, "status_code", None),
            "elapsed_seconds": round(time.perf_counter() - started, 6),
            "error_type": type(error).__name__,
        }
    finally:
        await client.close()


async def _concurrent_probe() -> list[dict[str, object]]:
    return await asyncio.gather(
        *(
            _one_synthetic_request(index, repeats)
            for index, repeats in enumerate((2600, 2800, 3000, 3200))
        )
    )


def main() -> int:
    tiny = "Reply exactly OK."
    with httpx.Client(trust_env=True, timeout=120.0) as client:
        inherited_transport = _request(client, tiny, 16)
    with httpx.Client(trust_env=False, timeout=120.0) as client:
        direct_transport = _request(client, tiny, 16)
        tags = client.get("http://127.0.0.1:11435/api/tags").json()

    os.environ["NO_PROXY"] = "127.0.0.1,localhost"
    os.environ["no_proxy"] = "127.0.0.1,localhost"
    started = time.perf_counter()
    concurrent = asyncio.run(_concurrent_probe())
    concurrent_elapsed = round(time.perf_counter() - started, 6)
    digest = next(model["digest"] for model in tags["models"] if model["name"] == MODEL)

    if inherited_transport["status"] != 503:
        raise RuntimeError(f"expected intercepted inherited transport 503, got {inherited_transport}")
    if direct_transport["status"] != 200:
        raise RuntimeError(f"direct loopback transport failed: {direct_transport}")
    if digest != MODEL_DIGEST:
        raise RuntimeError(f"unexpected model digest: {digest}")
    if [row["status"] for row in concurrent] != [200, 200, 200, 200]:
        raise RuntimeError(f"NO_PROXY concurrent loopback probe failed: {concurrent}")

    payload = attach_artifact_integrity(
        {
            "schema": "wavemind.scientific_v31_longmem_loopback_probe.v1",
            "status": "passed_synthetic_loopback_transport_probe",
            "probe_scope": "infrastructure_only_synthetic_text",
            "model": MODEL,
            "model_digest": digest,
            "observed_transport_contrast": {
                "inherited_httpx_trust_env_true": inherited_transport,
                "explicit_httpx_trust_env_false": direct_transport,
                "diagnosis": (
                    "On this Windows host, inherited httpx transport reached a system proxy "
                    "and returned an empty HTTP 503 for loopback, while trust_env=False "
                    "reached the local Ollama endpoint and returned HTTP 200."
                ),
            },
            "no_proxy_concurrent_openai_sdk": {
                "no_proxy": "127.0.0.1,localhost",
                "request_count": len(concurrent),
                "total_elapsed_seconds": concurrent_elapsed,
                "results": concurrent,
                "all_status_200": True,
            },
            "scientific_boundary": {
                "benchmark_prompt_read": False,
                "benchmark_answer_read": False,
                "gold_read": False,
                "score_read": False,
                "synthetic_model_calls_only": True,
                "model_or_digest_changed": False,
                "threshold_changed": False,
            },
            "claim_boundary": (
                "This synthetic transport probe is not a benchmark outcome and authorizes "
                "no pass, 100%-pass, SOTA, or revolutionary claim."
            ),
        }
    )
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
