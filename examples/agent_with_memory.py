from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind import WaveMind


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "qwen/qwen3-next-80b-a3b-instruct:free"
NAMESPACE = "openrouter-agent-demo"


def build_memory(db_path: str | Path = "agent_memory.sqlite3") -> WaveMind:
    return WaveMind(db_path=Path(db_path))


def observe_user_message(memory: WaveMind, message: str) -> None:
    lower = message.lower()
    if "меня зовут" in lower or "я трейдер" in lower:
        memory.remember(
            message,
            namespace=NAMESPACE,
            tags=["user-profile"],
            metadata={"kind": "user_profile"},
            priority=2.0,
        )


def recall_memory(memory: WaveMind, query: str) -> str:
    hits = memory.query(query, namespace=NAMESPACE, tags=["user-profile"], top_k=3)
    return "\n".join(hit.text for hit in hits)


def openrouter_chat(
    messages: list[dict[str, str]],
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
) -> str:
    api_key = api_key or os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Set OPENROUTER_API_KEY or OPENAI_API_KEY before running this example.")

    payload = json.dumps({"model": model, "messages": messages, "temperature": 0.1}).encode("utf-8")
    request = urllib.request.Request(
        OPENROUTER_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/CaspianG/wavemind",
            "X-Title": "WaveMind memory demo",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"].strip()


def answer_with_memory(memory: WaveMind, user_message: str, history: list[dict[str, str]]) -> str:
    memory_context = recall_memory(memory, user_message) or "No stored user profile yet."
    messages = [
        {
            "role": "system",
            "content": (
                "You are a concise Russian assistant. Use WaveMind memory when it is relevant.\n"
                f"WaveMind memory:\n{memory_context}"
            ),
        },
        *history[-10:],
        {"role": "user", "content": user_message},
    ]
    return openrouter_chat(messages)


def run_demo(db_path: str | Path = "agent_memory.sqlite3") -> str:
    memory = build_memory(db_path)
    history: list[dict[str, str]] = []

    first_message = "меня зовут Андрей, я трейдер"
    observe_user_message(memory, first_message)
    history.append({"role": "user", "content": first_message})
    history.append({"role": "assistant", "content": "Запомнил."})

    for i in range(10):
        history.append({"role": "user", "content": f"промежуточное сообщение {i}"})
        history.append({"role": "assistant", "content": "Понял."})

    final_question = "как меня зовут?"
    try:
        answer = answer_with_memory(memory, final_question, history)
        print(answer)
        return answer
    finally:
        memory.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="agent_memory.sqlite3")
    args = parser.parse_args()
    run_demo(args.db)
