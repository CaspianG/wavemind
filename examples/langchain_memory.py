from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind.integrations.langchain import WaveMindMemory


def main() -> int:
    # Drop-in shape for LangChain chains:
    # memory = WaveMindMemory(db_path="agent_memory.sqlite3")
    memory = WaveMindMemory()

    memory.save_context(
        {"input": "my name is Andrey and I am a trader"},
        {"output": "Got it. I will remember that."},
    )

    recalled = memory.load_memory_variables({"input": "what is my name?"})
    print("WaveMindMemory history:")
    print(recalled["history"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
