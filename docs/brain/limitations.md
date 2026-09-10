# D1 limits and evidence / Ограничения и проверки D1

D1 is a local engineering preview for nonsecret pilot material. Passing its
tests establishes the tested behavior at the recorded source commit. It does
not establish measured user value, a causal effect or a scientific breakthrough.

## Storage, access and import

The authoritative store is `brain.sqlite3`; private experience uses
`brain-experience.sqlite3`, and local authentication has its own
`brain-auth.sqlite3`. Data is plaintext. Token digests do not encrypt source
content. This is not OS-account isolation or protection against a privileged
local process. The dedicated Brain launch does not expose these stores on
legacy generic memory/experience routes.

Owner initialization requires an explicit new local key-file destination. The
key is 32 random bytes encoded with `token_urlsafe`, while authentication stores
only a SHA-256 lookup digest; terminal `getpass` reads an already issued key and
does not enroll a chosen password. This is why the password-hashing alert for
that exact flow is a documented false positive. If chosen passwords or weaker
issuance are introduced, this conclusion no longer applies. The key file is
protected plaintext, not encryption: POSIX creates it as the current owner with
mode 0600, and Windows creates a protected noninherited current-user-only DACL.
Unsupported private creation fails closed.

The owner chooses each new UI import's audience; it starts owner-private.
Service callers that omit `new_source_readers` or supply null use all live Brain
members for a new source. Existing-source updates and deduplication preserve the
live audience. Agent caps contain exact Brain/source pairs and cannot expand
after issuance. Changing a live audience alone cannot grant a key a new source.

One import accepts at most 20 files, 10 MiB per file, 50 MiB total, 2 MiB of
extracted UTF-8 text per file and 30 seconds of parsing per file. Supported
inputs include text/Markdown, supported JSON chat messages and PDF text. Archives,
symlink/reparse traversal and HTTP server-path inputs are rejected. Failed files
remain visible in preview and cannot be silently committed. HTTP JSON upload
also has an encoded body bound; general request bodies are limited to 1 MiB.

JSON conversations normalize to `role: content` lines. Message timestamps may
be validated but are not retained in the extracted text or source-version
metadata. Citations refer to normalized text, not original JSON bytes. Explicit
claim event times and validity remain separate; imported timestamps do not
automatically establish chronology. PDF extraction is not a claim of OCR support.

## Knowledge and verification

Records have explicit statuses `proposed`, `active`, `conflicted`, `superseded`
and `revoked`. Validity is `[valid_from, valid_until)`, with unknown bounds
represented by null. Approval and declared topic/project keys govern conflict
handling; D1 does not discover every semantic contradiction automatically.
Partially overlapping conflicts suppress whole records, not separate historical
segments. Provenance stays conservative after rejecting competitors: a former
origin can still restrict visibility or cause dependent records to be erased
when that source is deleted. Historical coverage is therefore limited.

Every derived record, citation, history entry and export needs all originating
source rights. Coverage can be partial, stale or pending. An unknown answer must
remain unknown. A received context packet is not permission to skip revalidation.

An agent's result label is not verification. An owner attestation is the owner's
statement; a configured verifier is trusted local code registered separately.
Reported procedure steps are not tools executed by WaveMind. Verified outcomes
can await integration. Eligibility requires repeated independent evidence and
valid current dependencies; changed sources cannot reuse old private credit.
Failed and unverified history remains readable only under current authority.

## Recovery and deletion

Pause retains a readable snapshot; revoke removes live read eligibility. Delete
erases live source payload and derived records, with private cleanup retried by
the local maintenance queue. `cleanup_pending` means work remains; `purged`
requires actual cleanup. Neither proves physical secure erasure from a disk,
third-party history or retained backup.

Backups contain permitted committed source versions/chunks and readable history.
They do not import credentials, live memberships or ephemeral import previews.
`import_previews_not_restored` means unfinished imports must be previewed again.
Reader/editor export requires independent read rights; agent export additionally
requires the export operation. Backup and recovery management belong to a human
owner. Quarantine content is available only to the explicit restore owner.

Current tombstones and pending gates override a stale archive. Unknown-history
restore quarantines sources for owner review, admission and semantic recheck;
equal source digests alone cannot prove archived approvals or verification
scores. Fresh private learning is required. `bootstrap_required` means a trusted
authenticated target owner is missing; archive/body identity cannot supply one.
`recovery_required` requires resolving the recovery state before ordinary use.
No lost-owner-secret reset is provided.

The protected key file is flushed before the owner credential is committed.
There is no atomic transaction spanning the file and SQLite. A write or flush
failure leaves no newly usable owner. A crash after file creation but before the
database commit can leave an ambiguous file; a later `init` refuses to overwrite
it, reports incomplete initialization, and requires manual inspection rather
than inventing a reset or deleting user data. Repeated `init` never replaces an
existing owner or key file.

Sanitized backups can preserve readable history as `cleanup_pending` while
omitting an unavailable shared private namespace. `private_cleanup_pending`
warns about that snapshot. A historical warning does not prove cleanup is still
pending in the restored live profile; inspect current state after maintenance.

## Reproduce engineering acceptance

From a clean checkout with dev dependencies, actual MCP, Node and Playwright
plus Chromium/Chrome available:

```sh
python scripts/verify_brain_d1.py --expected-source-sha EXACT_CHECKED_OUT_COMMIT --output /absolute/local/brain-d1-evidence.json
```

Set `BRAIN_UI_NODE`, `BRAIN_UI_PLAYWRIGHT` and `BRAIN_UI_CHROME` to explicit local
runtime paths when they are not available by default. Use the Python where
the project and dev/MCP dependencies are installed. The runner allocates a new
short system-temp test directory and retains it as local test evidence. It
never opens a user's existing browser profile. `--brain-only` is diagnostic and
leaves F13 unexecuted. Do not substitute a prior artifact for a current run.

| Gate | Actual required coverage |
|---|---|
| F01 | Persistence, restart, HTTP and standalone MCP startup maintenance |
| F02 | Idempotent import/receipts, private-commit crash and retry |
| F03 | Event order, half-open corrections and corrected-basis learning |
| F04 | Explicit conflicts and owner resolution |
| F05 | Versioned citations and live exact-source rights |
| F06 | Brain/source isolation and all-origin read/export restrictions |
| F07 | Dependency invalidation, pending states and maintenance |
| F08 | Receipt binding, replay rejection, real verification boundaries |
| F09 | Live source, derived and private-copy deletion |
| F10 | Export, backup, quarantine and stale-backup recovery |
| F11 | Import bounds and HTTP/MCP/path/session safety |
| F12 | Real browser P1/B1 twice with variations, separate HTTP clients and real stdio MCP |
| F13 | Complete repository suite's required legacy compatibility coverage |
| F14 | Explicit connection/action choice, no default model or external action |

The source-controlled [runner](../../scripts/verify_brain_d1.py) lists exact
mandatory test identifiers and maps every collected test in the relevant modules.
Absent, skipped or failed Brain tests cannot pass. F13 permits only the closed
16-case historical allowlist for missing optional distributions/tools and one
Windows symlink privilege condition. Seven exact preexisting scientific tests
can also remain unexecuted when their external LongMemEval/MemOps checkout is
absent at its expected path before and after the run. These are explicitly
partial scientific coverage, not successful scientific compatibility checks.
Present-but-invalid upstreams and installed-but-broken packages are not
"missing". Optional cases remain explicitly unexecuted/partial; any unexpected
skip or collection error blocks acceptance. The JSON contains actual outcomes,
versions and before/after source hashes, without source contents, credentials,
profile paths or raw exception messages.

The reusable [D1 workflow](../../.github/workflows/brain-d1.yml) is a dependency
of the existing required full-check job. Its candidate-labelled artifact must
match the actual checked-out SHA, including a PR merge SHA when applicable.
Local tests are not GitHub CI or SAST evidence. Existing Safe Product admission
still needs its own real compatibility/security dependencies. Historical
2.14.0 publication facts and the evaluation-validity **15/16 blocked** verdict
remain separate from D1.

Review coverage also has a recorded limit: a separate Task6 diagnostic was
interrupted by a tool restriction and was not retried. Its additional dependency
completeness question remains unverified. The two confirmed defects were fixed
and reviewed separately; this does not imply an exhaustive security review.

## Remaining stages

| Stage | Required evidence still outside D1 |
|---|---|
| D2 | Bundled signed Windows install/update/uninstall, a real publisher certificate and clean-machine tests |
| D3 | Team TLS/authentication/backup deployment and operational validation |
| D4 | 10 novice users, 14-day retention, 3 real team pilots and a frozen scientific comparison |

Windows SDK signing/packaging tools have been located in the development
environment; a publisher certificate, signed artifact and clean-install test
have not been established. Finding tools is not a completed installation gate.
Synthetic browser examples cannot replace participants, retention or team pilots.
The existing failed LongMemEval and quantum-sensing conclusions remain failed.

## По-русски

D1 является локальным инженерным прототипом для несекретных материалов. Данные
хранятся открытым текстом в отдельных SQLite-файлах; хеши ключей не шифруют
документы. Нужны Python и браузер, а для MCP ещё и пакет `[mcp]`. Нет готовой
массовой установки, автоматического чтения чатов, выбранного аккаунта или
подключённой модели.

Для инициализации нужен явно выбранный новый локальный файл ключа. Ключ создаётся
из 32 случайных байтов через `token_urlsafe`; в базе хранится только поисковый
SHA-256-дайджест. `getpass` лишь читает уже выданный ключ, а не регистрирует пароль
пользователя, поэтому предупреждение о слабом хешировании пароля ложно только для
этого контракта. Файл содержит открытый текст: в POSIX он создаётся с режимом
0600 для текущего владельца, а в Windows — с защищённым ненаследуемым DACL только
для текущего пользователя. Если такую защиту создать нельзя, операция закрывается
с ошибкой.

Импорт ограничен 20 файлами, 10 МиБ на файл, 50 МиБ суммарно, 2 МиБ извлечённого
UTF-8 текста на файл и 30 секундами разбора. Архивы, ссылки/reparse-переходы и
чтение серверного пути через HTTP запрещены. Цитаты относятся к нормализованному
тексту. Времена сообщений JSON не сохраняются в тексте или метаданных версии;
порядок событий задаётся явно в записях. Все семантические противоречия система
автоматически не находит, историческое покрытие ограничено.

Новый импорт через UI изначально приватен владельцу. Сервисный null означает
всех живых участников Brain. Обновление сохраняет текущую аудиторию. Ключ агента
ограничен неизменяемыми точными парами Brain/источник; новые документы требуют
нового ключа. Любая производная запись требует прав на все исходные источники.

Подтверждение владельцем, результат настроенного верификатора, ожидание
интеграции и пригодность процедуры различаются. Сообщённые шаги не выполняются
WaveMind. Старый успех не доказывает пользу памяти и не разрешает процедуру
после изменения оснований. При `cleanup_pending` очистка продолжается;
`purged` означает выполненную очистку живых копий, а не стирание чужих архивов.

Резервная копия сохраняет разрешённые зафиксированные версии и историю, но не
ключи, живые членства и незавершённые предпросмотры. Без текущей достоверной
истории восстановление требует карантина, проверки владельцем и повторной
проверки зависимостей. `bootstrap_required` означает отсутствие доверенного
владельца назначения, `recovery_required` требует разрешить состояние
восстановления. Ключ владельца нельзя сбросить архивом или повторным `init`.
Файл ключа сбрасывается на диск до фиксации владельца в SQLite, но общей атомарной
транзакции нет. Сбой записи не создаёт действующего владельца. После аварии может
остаться неоднозначный файл без зафиксированного владельца; повторный `init` его
не удаляет и не перезаписывает, а сообщает о незавершённой инициализации.

Команда проверки выше запускает настоящие тесты с привязкой к чистому SHA.
Неисполненный обязательный тест не становится успешным. Только закрытый список
исторических необязательных пропусков допускается в F13, причём эти проверки
остаются явно неисполненными. P1/B1 являются синтетическими сценариями без
пользовательских материалов и модели. Незавершённая отдельная диагностическая
проверка Task6 остаётся непроверенной, несмотря на исправление двух подтверждённых
дефектов.

D2 требует подписанной установки, обновления и удаления на чистой Windows.
D3 требует развёртывания для команды с TLS, аутентификацией и резервными копиями.
D4 требует 10 новых пользователей, удержания 14 дней, 3 реальных командных пилотов
и зафиксированного научного сравнения. Эти этапы не закрываются скриншотами.
