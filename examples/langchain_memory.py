from __future__ import annotations

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
