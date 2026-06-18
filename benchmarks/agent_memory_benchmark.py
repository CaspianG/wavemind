from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind import WaveMind
from wavemind.encoders import HashingTextEncoder, create_text_encoder


@dataclass(frozen=True)
class AgentFact:
    id: str
    text: str
    tags: tuple[str, ...] = ("profile",)


@dataclass(frozen=True)
class AgentQuery:
    id: str
    text: str
    expected_id: str


@dataclass(frozen=True)
class AgentScenario:
    facts: list[AgentFact]
    queries: list[AgentQuery]


@dataclass(frozen=True)
class EngineMetrics:
    engine: str
    precision_at_1: float
    precision_at_3: float
    avg_latency_ms: float
    p95_latency_ms: float
    queries: int


TARGET_FACTS_AND_QUERIES: tuple[tuple[str, str, str], ...] = (
    ("fact_name", "Пользователя зовут Андрей.", "как зовут пользователя?"),
    ("fact_role", "Андрей работает трейдером и каждый день следит за рынком.", "кем работает Андрей?"),
    ("fact_budget", "Рабочий бюджет Андрея на инструменты составляет 2000 долларов.", "что знаем про бюджет?"),
    ("fact_answer_style", "Андрей любит краткие практичные ответы без лишней воды.", "какие ответы любит пользователь?"),
    ("fact_language", "В рабочих обсуждениях Андрей предпочитает русский язык.", "на каком языке лучше отвечать?"),
    ("fact_market", "Андрей чаще всего торгует криптовалюты и американские акции.", "какие рынки торгует Андрей?"),
    ("fact_timezone", "Часовой пояс Андрея для созвонов — Europe/Moscow.", "какой часовой пояс у пользователя?"),
    ("fact_risk", "Андрей ограничивает риск одной сделки одним процентом капитала.", "какой риск на сделку?"),
    ("fact_broker", "Для торговли Андрей использует брокера Interactive Brokers.", "какого брокера использует пользователь?"),
    ("fact_exchange", "Основная криптобиржа Андрея — Binance.", "какая основная криптобиржа?"),
    ("fact_terminal", "Главный торговый терминал Андрея — TradingView.", "какой торговый терминал основной?"),
    ("fact_strategy", "Любимая стратегия Андрея — пробой уровня с подтверждением объема.", "какая любимая стратегия?"),
    ("fact_horizon", "Андрей чаще принимает решения на горизонте от одного до трех дней.", "какой торговый горизонт?"),
    ("fact_stop_loss", "Андрей всегда ставит стоп-лосс перед входом в позицию.", "что он делает со стоп-лоссом?"),
    ("fact_take_profit", "Андрей фиксирует прибыль частями, а не всей позицией сразу.", "как пользователь фиксирует прибыль?"),
    ("fact_news", "Перед сделкой Андрей проверяет экономический календарь и важные новости.", "что он проверяет перед сделкой?"),
    ("fact_devices", "Основной рабочий компьютер Андрея — ноутбук на Windows.", "какой основной рабочий компьютер?"),
    ("fact_phone", "Телефон Андрея — iPhone 15 Pro.", "какой телефон у пользователя?"),
    ("fact_editor", "Для кода Андрей предпочитает VS Code.", "какой редактор кода предпочитает Андрей?"),
    ("fact_python", "Андрей пишет торговые прототипы на Python.", "на чем он пишет торговые прототипы?"),
    ("fact_database", "Для локальных прототипов Андрей выбирает SQLite.", "какую базу он выбирает для локальных прототипов?"),
    ("fact_agents", "Андрей строит AI-агентов с внешней долговременной памятью.", "что Андрей строит из AI-агентов?"),
    ("fact_memory", "Главная цель WaveMind для Андрея — память агента между диалогами.", "зачем Андрею WaveMind?"),
    ("fact_openrouter", "Для дешевых LLM-запросов Андрей использует OpenRouter.", "какой провайдер нужен для дешевых LLM запросов?"),
    ("fact_github", "GitHub-аккаунт Андрея называется CaspianG.", "как называется GitHub аккаунт?"),
    ("fact_pypi", "Пакет WaveMind опубликован на PyPI под именем wavemind.", "как называется пакет на PyPI?"),
    ("fact_repo", "Репозиторий WaveMind находится по адресу github.com/CaspianG/wavemind.", "где лежит репозиторий WaveMind?"),
    ("fact_license", "Для открытого ядра WaveMind выбрана лицензия MIT.", "какая лицензия у открытого ядра?"),
    ("fact_cli", "Андрею важен CLI, чтобы память можно было проверять из терминала.", "почему важен CLI?"),
    ("fact_api", "HTTP-интерфейс WaveMind должен работать через FastAPI.", "через что должен работать HTTP интерфейс?"),
    ("fact_tags", "Андрей хочет разделять воспоминания тегами и namespace.", "как разделять воспоминания?"),
    ("fact_ttl", "Старые воспоминания должны устаревать через TTL.", "как должны устаревать воспоминания?"),
    ("fact_threshold", "Для возврата памяти нужен минимальный score threshold.", "какой порог нужен для возврата памяти?"),
    ("fact_batch", "Документы надо импортировать пачкой из txt, pdf и json.", "из каких форматов импортировать документы?"),
    ("fact_benchmark", "Для доверия разработчиков нужен benchmark против Chroma.", "какой benchmark нужен для доверия?"),
    ("fact_latency_target", "Целевая задержка поиска для Андрея — меньше пяти миллисекунд.", "какая целевая задержка поиска?"),
    ("fact_capacity_target", "Практическая цель емкости — не меньше пяти тысяч воспоминаний.", "какая цель по емкости памяти?"),
    ("fact_backup", "SQLite-базу WaveMind нужно регулярно бэкапить.", "что нужно регулярно бэкапить?"),
    ("fact_docker", "Для daemon mode Андрею нужен Docker-контейнер.", "что нужно для daemon mode?"),
    ("fact_logs", "В production Андрею нужны понятные логи сервера.", "что нужно в production кроме сервера?"),
    ("fact_webhook", "При recall агент должен уметь отправлять webhook.", "что агент должен отправлять при recall?"),
    ("fact_saas", "Первый коммерческий продукт — SaaS-память для AI-агентов.", "какой первый коммерческий продукт?"),
    ("fact_price_start", "Стартовый SaaS-тариф Андрей планирует около 29 долларов в месяц.", "какой стартовый тариф SaaS?"),
    ("fact_team_price", "Командный SaaS-тариф Андрей планирует около 199 долларов в месяц.", "какой командный тариф SaaS?"),
    ("fact_enterprise", "Enterprise-цена для WaveMind начинается примерно от 1000 долларов в месяц.", "какая enterprise цена?"),
    ("fact_quant", "Дорогой рынок для WaveMind — прогнозирование рыночных паттернов.", "какой дорогой рынок для WaveMind?"),
    ("fact_backtest", "Трейдерам нужен воспроизводимый бэктест без подгонки.", "что нужно трейдерам для доверия?"),
    ("fact_commission", "В рыночном бэктесте обязательно учитывать комиссии.", "что обязательно учитывать в бэктесте?"),
    ("fact_priority", "Отличие WaveMind — динамический приоритет горячей памяти.", "в чем отличие WaveMind?"),
    ("fact_competitors", "Pinecone, Weaviate и Chroma обычно хранят векторы без физики памяти.", "что делают конкуренты с памятью?"),
)


DISTRACTOR_TOPICS: tuple[tuple[str, str], ...] = (
    ("workspace", "Рабочее пространство Андрея включает отдельный монитор для графиков."),
    ("coffee", "Утром Андрей пьет черный кофе без сахара."),
    ("exercise", "После обеда Андрей делает короткую прогулку для перезагрузки."),
    ("notebook", "Идеи для стратегий Андрей записывает в отдельный блокнот."),
    ("alerts", "Ценовые алерты Андрей группирует по рынкам и таймфреймам."),
    ("review", "В конце недели Андрей пересматривает журнал сделок."),
    ("security", "Для важных аккаунтов Андрей включает двухфакторную защиту."),
    ("calendar", "Созвоны Андрей предпочитает ставить после 14:00 по Москве."),
    ("email", "Письма по продукту Андрей сортирует в отдельную папку."),
    ("learning", "Новые идеи Андрей проверяет на маленьких экспериментах."),
)


def build_agent_memory_scenario(
    fact_count: int = 200,
    query_count: int = 50,
) -> AgentScenario:
    if fact_count < 1:
        raise ValueError("fact_count must be positive")
    if query_count < 1:
        raise ValueError("query_count must be positive")

    facts = [
        AgentFact(id=id, text=text, tags=("profile", "target"))
        for id, text, _ in TARGET_FACTS_AND_QUERIES
    ]
    for index in range(1, max(0, fact_count - len(facts)) + 1):
        topic, text = DISTRACTOR_TOPICS[(index - 1) % len(DISTRACTOR_TOPICS)]
        facts.append(
            AgentFact(
                id=f"fact_distractor_{index:03d}",
                text=f"{text} Дополнительная заметка профиля номер {index}.",
                tags=("profile", "distractor", topic),
            )
        )

    facts = facts[:fact_count]
    available_ids = {fact.id for fact in facts}
    queries = [
        AgentQuery(id=f"query_{index:02d}", text=query, expected_id=id)
        for index, (id, _, query) in enumerate(TARGET_FACTS_AND_QUERIES, start=1)
        if id in available_ids
    ][:query_count]
    if len(queries) < query_count:
        raise ValueError("query_count requires enough target facts in the selected fact_count")
    return AgentScenario(facts=facts, queries=queries)


def compute_metrics(
    queries: Iterable[AgentQuery],
    rankings: dict[str, list[str]],
    latencies_ms: list[float],
    engine: str = "benchmark",
) -> EngineMetrics:
    query_list = list(queries)
    if not query_list:
        return EngineMetrics(engine, 0.0, 0.0, 0.0, 0.0, 0)

    hit1 = 0
    hit3 = 0
    for query in query_list:
        ranked_ids = rankings.get(query.id, [])
        if ranked_ids[:1] == [query.expected_id]:
            hit1 += 1
        if query.expected_id in ranked_ids[:3]:
            hit3 += 1

    sorted_latencies = sorted(latencies_ms)
    p95_index = min(len(sorted_latencies) - 1, int(len(sorted_latencies) * 0.95))
    return EngineMetrics(
        engine=engine,
        precision_at_1=hit1 / len(query_list),
        precision_at_3=hit3 / len(query_list),
        avg_latency_ms=statistics.mean(latencies_ms),
        p95_latency_ms=sorted_latencies[p95_index],
        queries=len(query_list),
    )


def run_wavemind(scenario: AgentScenario, encoder, top_k: int) -> EngineMetrics:
    with tempfile.TemporaryDirectory() as tmp:
        memory = WaveMind(
            db_path=Path(tmp) / "agent-memory.sqlite3",
            encoder=encoder,
            index_kind="numpy",
            score_threshold=0.0,
            width=64,
            height=64,
            layers=3,
            evolve_on_feed=3,
            field_weight=0.04,
            lexical_weight=0.20,
            short_query_lexical_weight=2.0,
            rerank_k=10,
        )
        try:
            for fact in scenario.facts:
                memory.remember(
                    fact.text,
                    namespace="agent",
                    tags=fact.tags,
                    metadata={"benchmark_id": fact.id},
                )

            rankings: dict[str, list[str]] = {}
            latencies: list[float] = []
            for query in scenario.queries:
                started = time.perf_counter()
                results = memory.query(query.text, namespace="agent", top_k=top_k)
                latencies.append((time.perf_counter() - started) * 1000.0)
                rankings[query.id] = [
                    str(result.metadata.get("benchmark_id", ""))
                    for result in results
                ]
        finally:
            memory.store.close()
    return compute_metrics(scenario.queries, rankings, latencies, engine="WaveMind")


def run_chroma(scenario: AgentScenario, encoder, top_k: int) -> EngineMetrics:
    try:
        import chromadb
        from chromadb.config import Settings
    except ImportError as exc:
        raise RuntimeError(
            'Install Chroma for this benchmark: pip install -e ".[bench]"'
        ) from exc

    client = chromadb.Client(Settings(anonymized_telemetry=False))
    collection = client.create_collection(
        name=f"wavemind_agent_memory_{time.time_ns()}",
        metadata={"hnsw:space": "cosine"},
        embedding_function=None,
    )
    embeddings = [encoder.encode_vector(fact.text).tolist() for fact in scenario.facts]
    collection.add(
        ids=[fact.id for fact in scenario.facts],
        documents=[fact.text for fact in scenario.facts],
        metadatas=[{"tags": ",".join(fact.tags)} for fact in scenario.facts],
        embeddings=embeddings,
    )

    rankings: dict[str, list[str]] = {}
    latencies: list[float] = []
    for query in scenario.queries:
        query_embedding = encoder.encode_vector(query.text).tolist()
        started = time.perf_counter()
        result = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=[],
        )
        latencies.append((time.perf_counter() - started) * 1000.0)
        rankings[query.id] = list(result.get("ids", [[]])[0])

    return compute_metrics(scenario.queries, rankings, latencies, engine="Chroma")


def run_benchmark(
    engines: Iterable[str],
    fact_count: int = 200,
    query_count: int = 50,
    encoder_kind: str = "hash",
    top_k: int = 3,
) -> dict:
    scenario = build_agent_memory_scenario(fact_count=fact_count, query_count=query_count)
    encoder = create_text_encoder(kind=encoder_kind, vector_dim=384)
    runners = {
        "wavemind": run_wavemind,
        "chroma": run_chroma,
    }

    results = []
    for engine in engines:
        key = engine.lower()
        if key not in runners:
            raise ValueError(f"Unknown engine: {engine}")
        results.append(asdict(runners[key](scenario, encoder, top_k=top_k)))

    return {
        "scenario": {
            "name": "agent_user_memory",
            "facts": len(scenario.facts),
            "queries": len(scenario.queries),
            "language": "ru",
            "top_k": top_k,
        },
        "embedding": {
            "kind": encoder_kind,
            "class": type(encoder).__name__,
            "vector_dim": getattr(encoder, "vector_dim", None),
            "note": "WaveMind and Chroma receive the same precomputed query/document embeddings.",
        },
        "results": results,
    }


def print_table(payload: dict) -> None:
    print("| engine | precision@1 | precision@3 | avg latency | p95 latency |")
    print("|---|---:|---:|---:|---:|")
    for result in payload["results"]:
        print(
            f"| {result['engine']} | "
            f"{result['precision_at_1']:.2f} | "
            f"{result['precision_at_3']:.2f} | "
            f"{result['avg_latency_ms']:.2f} ms | "
            f"{result['p95_latency_ms']:.2f} ms |"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--facts", type=int, default=200)
    parser.add_argument("--queries", type=int, default=50)
    parser.add_argument("--encoder", choices=["hash", "sentence"], default="hash")
    parser.add_argument("--engines", nargs="+", choices=["wavemind", "chroma"], default=["wavemind", "chroma"])
    parser.add_argument("--output", type=Path, default=Path("benchmarks/agent_memory_results.json"))
    args = parser.parse_args()

    payload = run_benchmark(
        engines=args.engines,
        fact_count=args.facts,
        query_count=args.queries,
        encoder_kind=args.encoder,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print_table(payload)
    print(f"\nWrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
