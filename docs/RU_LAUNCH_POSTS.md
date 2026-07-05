# WaveMind: русскоязычные материалы для запуска

Этот файл хранит заготовки для VC, Telegram, личных блогов и коротких постов.
Тон: просто, честно, без завышенных обещаний. Главная мысль: WaveMind не
заменяет vector DB, а добавляет слой динамической памяти поверх поиска.

## Короткое объяснение

WaveMind - это память для программ: она не просто ищет похожий текст, а
пытается понять, какая информация всё ещё важна. Старое может затухать,
повторяющееся усиливаться, временное исчезать, а разные пользователи и проекты
не смешиваются между собой.

Обычный vector search отвечает: "что похоже на запрос?" WaveMind добавляет
второй слой: "что из найденного сейчас действительно важно?"

## Пост для VC / блога

### Заголовок

Почему обычной векторной базы мало для памяти AI-агентов

### Текст

Я делаю WaveMind - open-source библиотеку для динамической памяти.

Проблема простая: большинство систем памяти сейчас устроены как обычный поиск.
Пользователь что-то сказал, мы сделали embedding, положили его в базу, потом
нашли ближайшие куски текста.

Это работает, но у такой памяти нет ощущения времени и важности.

Например:

- пользователь раньше говорил одно, потом исправил факт;
- временная информация должна исчезнуть;
- часто используемая информация должна стать "горячее";
- память одного пользователя не должна протекать к другому;
- старый факт не должен всплывать наравне с новым.

WaveMind пытается решать именно эту часть.

Внутри всё приземлённо:

- SQLite хранит текст, вектора, метаданные и состояние памяти;
- vector search находит кандидатов;
- динамический слой учитывает hotness, TTL, priority, decay, namespaces и tags;
- сверху есть CLI, Python API, FastAPI сервер и интеграции с фреймворками.

Это не замена Chroma, Qdrant или Pinecone. Скорее слой памяти рядом с ними или
поверх них. Векторная база хорошо отвечает на вопрос "что похоже?", а WaveMind
пытается добавить вопрос "что всё ещё важно?"

Самое важное сейчас - не красивые слова про волны, а проверяемые benchmark'и.
В репозитории есть результаты по dynamic memory, LoCoMo, LongMemEval,
BEIR/SciFact, NoMIRACL Russian и production load profile. Там честно написано,
где WaveMind сильнее, а где пока проигрывает по скорости.

Установка:

```sh
python -m pip install wavemind
wavemind remember "Пользователь предпочитает короткие ответы" --namespace demo
wavemind query "как отвечать пользователю?" --namespace demo
```

Сейчас проект ранний, но уже рабочий: можно хранить память локально, поднимать
HTTP API, делать backup, смотреть audit log, метрики и трассировки.

GitHub: https://github.com/CaspianG/wavemind

## Telegram-пост

Делаю WaveMind - open-source память для программ и AI-агентов.

Обычная векторная база умеет искать похожие куски текста. Но память - это не
только похожесть.

Память должна понимать:

- что часто вспоминается;
- что устарело;
- что было исправлено;
- что временное;
- что относится к конкретному пользователю или проекту.

WaveMind хранит данные в SQLite, ищет кандидатов через vector search, а потом
применяет динамический слой: hotness, decay, TTL, priority, namespaces, tags.

Это не замена Chroma/Qdrant. Это слой памяти, который можно поставить рядом с
ними или использовать локально.

Быстрый запуск:

```sh
python -m pip install wavemind
wavemind remember "Андрей предпочитает короткие ответы" --namespace demo
wavemind query "как отвечать Андрею?" --namespace demo
```

Репозиторий: https://github.com/CaspianG/wavemind

## Короткие посты

### Пост 1

Обычный vector search отвечает: "что похоже на запрос?"

Но память должна отвечать ещё на один вопрос: "что из этого всё ещё важно?"

WaveMind - open-source попытка сделать такой слой памяти: SQLite, vector search,
hotness, decay, TTL, namespaces и audit log.

https://github.com/CaspianG/wavemind

### Пост 2

AI-агент без нормальной памяти быстро превращается в чат на 10 сообщений.

Он забывает предпочтения, тянет старые факты, путает пользователей и не понимает,
что временная информация уже устарела.

WaveMind делает память динамической: важное усиливается, старое затухает,
временное исчезает.

### Пост 3

WaveMind не пытается заменить Chroma или Qdrant.

Идея другая: оставить обычный vector search для кандидатов, а поверх добавить
слой памяти: priority, hotness, TTL, decay, namespaces, corrections.

То есть не "ещё одна векторная база", а память поверх поиска.

## Комментарий от пользователя, который реально попробовал

Tried WaveMind for a few hours through the CLI and the API. The project is
still early, but the idea is genuinely interesting: memory is treated less like
a flat vector list and more like something that changes with use.

What I liked most is the practical part. SQLite as the source of truth makes it
easy to inspect and back up. Namespaces, TTL, forget, audit log, and the API are
already there, so it is not just a concept repo.

The benchmarks are also useful because they are not hiding the tradeoffs.
Static vector search is faster, but WaveMind is trying to solve a different
problem: stale facts, corrections, and memory priority over time.

I can see this being useful for long-running agents or personal assistants
where "what still matters" is more important than just "what text is nearest".

## Что отвечать на критику

### "Это просто vector DB"

Нет. Vector DB отвечает за кандидатов. WaveMind хранит состояние памяти:
hotness, TTL, priority, namespace, audit, explicit forget и динамическое
ранжирование.

### "Chroma быстрее"

Да, в статическом retrieval Chroma быстрее. Это честно написано в README.
WaveMind должен выигрывать там, где важны устаревание, исправления, TTL,
namespace isolation и повторное использование памяти.

### "Где научная новизна?"

Сейчас это инженерный слой динамической памяти, а не полноценная непрерывная
физическая модель. Исследовательское направление - graph memory, excitation,
inhibition, decay и consolidation с проверяемыми экспериментами.

### "Можно сделать на metadata filters"

Частично да. Но тогда это будет логика приложения. WaveMind пытается сделать
такую политику памяти частью reusable memory layer.
