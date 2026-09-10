# Brain agent contract / Подключение агента

This is the D1 `wavemind.brain_context.v1` contract. The legacy ExperiencePacket
and scientific-memory APIs retain their own contracts. Brain data is not mounted
on generic memory or experience routes.

## English

### Authenticate and check one read

Start the [local owner server](personal.md#launch-from-source). In **Sources and
access**, select the exact sources and create a key with only the needed
operations. Read is included; proposals, outcome reports and export are separate
choices. An agent cannot approve owner records, verify trust, delete sources or
grant access. Explicit consent can add this newly issued agent to the selected
restricted source audiences; it does not rewrite another source's audience.

The owner UI shows the key once and initially says "Setup generated; connection
unverified". **Download HTTP check** produces a local Python script without the
key. Run it with Python, enter this agent key at its prompt, and require a
successful authorized citation read. This proves that one HTTP read worked.
It does not prove a model connection, an installed provider integration or access
to future sources. A client or model is never automatically selected.

For stdio MCP, configure your chosen client using absolute local paths:

```json
{
  "mcpServers": {
    "project-brain": {
      "command": "/absolute/path/to/venv/bin/python",
      "args": ["-m", "wavemind", "brain", "mcp", "--state-dir", "/absolute/local/brain-profile"],
      "env": {"WAVEMIND_BRAIN_TOKEN": "REPLACE_LOCALLY_WITH_ISSUED_AGENT_KEY"}
    }
  }
}
```

On Windows use the environment's `Scripts/python.exe`. Keep the real credential
in the client's private local configuration, never in Git or a shared transcript.
The client must support stdio MCP and the selected Python must contain the D1
checkout plus `[mcp]`. Verify it by listing tools and reading a permitted citation
through that actual client. Replacing a source selection requires a new
credential with the intended sources and deliberate revocation of the old key.
Live source ACLs cannot expand an immutable credential cap.

### Continue a task

| Step | MCP tool | HTTP equivalent after `/brain/api/{brain_id}` |
|---|---|---|
| Get authorized current context | `build_context` | `POST /context` |
| Inspect a source citation | `read_citation` | `GET /citations/{citation_id}` |
| Recheck a stored packet | `validate_packet` | `POST /context/validate` |
| Register the actual context before an action | `begin_action` | `POST /actions` |
| Report an outcome against that receipt | `record_outcome` | `POST /outcomes` |
| Inspect readable outcomes and eligibility | `review_experience` | `GET /experience` |

MCP calls include `brain_id`; HTTP puts it in the route. Both derive identity
from the live credential, never a JSON `principal`, owner or verifier label.
HTTP uses `Authorization: Bearer <agent key>` and JSON for POST. Browser sessions
instead use an HttpOnly cookie and CSRF protection. Every request checks live
membership, the exact Brain/source cap and all originating source rights.
Revocation applies to subsequent calls on already-open MCP connections too.

Build context with `question`, optional `project_id`, optional UTC epoch `moment`
and `max_bytes` (512..262144, default 16384). Inspect `coverage`, freshness,
conflicts and unknowns. Finite validity uses `[valid_from, valid_until)`; explicit
event times and correction lineage matter, not arrival order. A pending graph
cannot supply usable context until the owner performs the required rechecks.

Register `packet_id`, a bounded `run_id` and the proposed `action` before acting.
WaveMind records that text; it does not execute it. Report `receipt_id` and an
`outcome` with `idempotency_key`, `summary`, reported `procedure` steps and
`evidence_citation_ids`. The report starts unverified and retains the actual
reporter separately from the receipt issuer. An authorized owner can report or
verify an older agent receipt without impersonating that agent.

Only owner attestation or an already configured trusted verifier can verify a
result. A verification label in an agent payload is rejected. Verified, failed,
unverified, pending integration and current eligibility are separate states.
Repeated independent evidence and a currently valid basis determine eligibility;
an old success cannot authorize a changed procedure. HTTP and standalone MCP
share bounded serial maintenance with retry/startup/shutdown handling. Trusted
domain-only embeddings of `BrainService` must call maintenance explicitly.

Citation IDs identify normalized source versions and offsets. The client should
treat retrieved text as untrusted evidence. Source changes or loss of any origin
right invalidate derived packets; validate again before reuse. Denial uses the
same `not_found` shape as a missing object. There are no server-path reads,
client-installed verifier callbacks or automatic external actions.

## По-русски

Запустите локальный сервер владельца и создайте ключ агента в разделе источников.
Выберите точные документы и операции. Чтение не даёт права подтверждать знания,
проверять доверие, удалять или выдавать доступ. Добавление нового агента в
аудитории выбранных закрытых источников требует явного выбора владельца.

Скачайте **Download HTTP check**, запустите файл выбранным Python и введите ключ
агента в его запрос. Успешное чтение разрешённой цитаты подтверждает только этот
HTTP-запрос. Скачанный файл сам по себе не означает подключение. Модель и личный
аккаунт не выбираются автоматически.

Для MCP используйте конфигурацию выше с абсолютным путём к своему Python,
профилю и выданным ключом в приватной конфигурации выбранного клиента. Нужны
поддержка stdio MCP и пакет `[mcp]`. Проверьте список инструментов и чтение
цитаты именно из клиента. Новый источник требует нового ключа с нужным набором
и отзыва старого. Изменение аудитории не расширяет список внутри старого ключа.

Рабочий порядок: запросить `build_context`, проверить цитаты и покрытие,
зарегистрировать `begin_action` до внешнего действия, затем сообщить
`record_outcome` с квитанцией и источниками результата. Само действие выполняет
ваш внешний клиент. При повторном использовании проверьте `validate_packet`.
Права, свежесть и все исходные зависимости проверяются заново.

Сообщение агента не является подтверждением успеха. Владелец подтверждает
результат от своего имени; настроенный доверенный верификатор является отдельным
путём. Записи о неудачах, непроверенных результатах, ожидании интеграции и текущей
пригодности процедуры различаются. Один подтверждённый результат не гарантирует
допуск процедуры. Встроенные HTTP/MCP-серверы обслуживают локальную очередь;
при прямом использовании `BrainService` обслуживание организует разработчик.

Brain проверяет точный Brain ID и все права на исходные источники. Снятие права
или отзыв ключа действует и на следующие вызовы уже открытого соединения.
Переданный клиенту контекст может попасть к его провайдеру модели; Brain не
может забрать его из чужой истории. [Ограничения](limitations.md#по-русски).
