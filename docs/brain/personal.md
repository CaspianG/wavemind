# Personal project memory / Личная память проекта

[English](#english) · [По-русски](#по-русски) · [Agent connection](agent-contract.md) · [Limits](limitations.md)

## English

Brain keeps selected sources and reviewed decisions in a local profile that you
own. For a move, you can record the budget, the deadline, why you chose a mover
and who still needs to approve the plan. A later assistant can request this
context with citations. You decide which sources it may see.

This D1 source preview requires Python 3.10+ and a local browser. It stores
plaintext, so use only nonsecret pilot material. There is no automatic chat
import, model connection or measured promise that it will save you time.

### Launch from source

Use a checkout containing `wavemind/brain`, with Python and pip available. In
PowerShell, from that checkout, create a project virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[mcp]"
.\.venv\Scripts\python.exe -m wavemind brain init --state-dir C:\WaveMindPilot\profile
.\.venv\Scripts\python.exe -m wavemind brain serve --state-dir C:\WaveMindPilot\profile
```

Choose your own ordinary local profile path outside the checkout. On Linux or
macOS, use `.venv/bin/python` and an absolute local directory instead. The base
package includes the HTTP server, SQLite support and PDF parser; `[mcp]` adds
stdio MCP. Dependency installation can access package registries. Running this
Brain workflow does not download a model or call a provider.

`init` prints `owner_secret` once. Store it privately and keep it out of source
documents, screenshots, chat messages and Git. `serve` prompts for the owner key
in an interactive terminal. Open `http://127.0.0.1:8000/brain` and sign in with
the same key. Keep that server terminal open; stop it with Ctrl+C when finished.
For a noninteractive local process, the CLI accepts `--token-file` or
`WAVEMIND_BRAIN_TOKEN`; neither is an HTTP request parameter.

The existing `install.bat`, `wavemind studio`, public 2.14.0 package and Docker
image belong to the legacy library. They are not a bundled D1 installer. A
signed Windows installation without developer tools is the separate D2 stage.

### Make a small, reviewable memory

1. Select RU or EN, create a personal project and open its import panel. Paste a
   nonsecret note or select supported files. New owner-UI imports start private
   to you. Review each file's result and audience before saving; cancel removes
   that preview. Updates preserve the existing source's audience.
2. Open **Known and current**. Use actual source citations to propose a goal,
   constraint, decision or fact, and explicitly approve each record you accept.
   Link a project and a decision's rationale if useful. Imported text is evidence;
   it is not an instruction to the application and is not automatically a fact.
3. Ask for context in the selected project. Inspect its citations, current facts,
   conflicts and unknowns. Partial coverage means the packet is not a complete
   account. Diagnostic byte/token figures describe this packet, not model billing.
4. To change the budget, import the correction and propose a replacement with
   the original record ID and its actual effective time. Review it. Competing
   claims remain conflicted until you resolve them; the last imported text does
   not automatically win. A pending graph needs dependency recheck and any
   required individual record review before context becomes usable.
5. In **Sources and access**, create an agent key for explicit sources and
   operations. Deliberately add that unique agent to the selected source
   audiences if it needs access. Follow the [connection guide](agent-contract.md).
   You remain responsible for configuring the external client and model.

![Actual personal-project context with a corrected budget and unresolved question.](../assets/brain/personal-context.png)

Actual D1 browser screenshot from a synthetic nonsecret scenario. No model
answers, real user's documents or measured benefit appear in this demonstration.

### Results, removal and portability

An agent can register a receipt for the context before acting, then report what
happened. The action happens outside WaveMind. Its report begins unverified.
In **Experience**, an owner attestation records your judgment; a registered
verifier must already have been configured by trusted local code. Neither a
report nor one confirmation guarantees procedure eligibility. Verified results
may still be waiting for integration, and a previously successful procedure may
be ineligible after its sources change. HTTP/MCP maintenance retries the local
queue; domain-only embedders must schedule maintenance themselves.

Pause stops a source's active contribution while retaining a readable snapshot.
Revoke removes live read eligibility and invalidates dependent context. Delete
erases its live payload and dependent records, including private experience
copies through cleanup. Inspect `cleanup_pending` until actual cleanup reports
`purged`. Deletion cannot retract copies already sent to another client or
remove an old backup from another location.

The UI offers authorized JSON export and recovery guidance. For local files,
the following commands prompt for your owner key. Replace the Brain ID from the
UI and choose new destinations; existing destinations are rejected.

```powershell
.\.venv\Scripts\python.exe -m wavemind brain export --state-dir C:\WaveMindPilot\profile --brain-id BRAIN_ID --destination C:\WaveMindPilot\export.json
.\.venv\Scripts\python.exe -m wavemind brain backup --state-dir C:\WaveMindPilot\profile --brain-id BRAIN_ID --destination C:\WaveMindPilot\backup.zip
.\.venv\Scripts\python.exe -m wavemind brain init --state-dir C:\WaveMindPilot\restored-profile
.\.venv\Scripts\python.exe -m wavemind brain restore --state-dir C:\WaveMindPilot\restored-profile --archive C:\WaveMindPilot\backup.zip
```

Use the new profile's owner key for restore. Restore requires an empty target;
it does not overwrite the running profile. An optional `--current-state-dir`
must name a separate profile that this authenticated owner is authorized to
read. Without it, current history is unknown and quarantine applies.

Export is readable authorized data; backup is the supported recovery archive.
Keep both private. Backups preserve committed source versions and readable
history, but do not transfer credentials, live memberships or unfinished import
previews. Current tombstones override stale backups. A new profile must first
be initialized with its own owner; without known current history, restored
sources remain quarantined until explicit owner review, admission and semantic
recheck. Old source digests cannot prove old approvals or scores. This is not
a lost-key reset feature. See [recovery limits](limitations.md#recovery-and-deletion).

### If something does not work

`No module named wavemind` usually means you used a different Python from the
one where you installed the checkout. Use that virtual environment's executable.
If the server cannot bind, choose `--port 8001` and open exactly
`http://127.0.0.1:8001/brain`. A different Host or Origin is rejected.
`doctor --state-dir ...` checks authenticated local state and reports
`model_connected: false`; it is not a model connectivity test.

An expired or revoked session needs a fresh valid sign-in. A rejected import
shows a per-file error; revise the file and preview it again. `not_found` can
mean absent data or insufficient live rights. Check the selected Brain, source
audience and credential cap rather than retrying under a different identity.
The [limits guide](limitations.md) explains pending and recovery states.

## По-русски

Память Brain хранит выбранные источники и подтверждённые решения в вашей
локальной папке. Например, для переезда можно сохранить бюджет, срок, причину
выбора перевозчика и вопрос о том, кто подписывает документы. Следующий
помощник запросит разрешённый контекст со ссылками на источники. Вы выбираете,
что ему доступно.

D1 запускается из исходного кода: нужны Python 3.10+, pip и браузер. Команды
PowerShell в разделе выше создают окружение, устанавливают текущий checkout,
инициализируют профиль и запускают сервер. Замените путь на свою локальную
папку вне репозитория. `[mcp]` нужен для клиента MCP; при установке зависимости
скачиваются из реестра пакетов. В рабочем цикле Brain модель не скачивается и
провайдер не вызывается. Данные хранятся открытым текстом; используйте только
несекретные материалы. Польза для реальных людей пока не измерена.

`init` один раз выводит `owner_secret`. Сохраните ключ приватно. `serve`
запрашивает его в терминале; затем откройте `http://127.0.0.1:8000/brain` и
войдите с тем же ключом. Терминал сервера должен оставаться открытым. Для
остановки нажмите Ctrl+C. Это запуск для разработчика, а не готовый подписанный
установщик. Старые Studio, `install.bat` и пакет 2.14.0 относятся к библиотеке.

Создайте личный проект, вставьте заметку или выберите файл и посмотрите
предпросмотр. Новые импорты через интерфейс изначально видны только владельцу;
проверьте показанную аудиторию перед сохранением. Обновление сохраняет права
существующего источника. Отмена убирает текущий предпросмотр. Из цитат создайте
цель, ограничение, решение или факт и подтвердите те записи, которым доверяете.
Импорт не превращает текст в подтверждённое знание автоматически.

Например: "Бюджет 60 000, переезд до пятницы; сначала осмотр, чтобы избежать
потери вещей. Кто подписывает акт, пока неизвестно". После изменения бюджета
добавьте источник исправления, укажите заменяемую запись и действительное время
изменения. Подтвердите замену и запросите контекст снова. Конфликты требуют
вашего решения; более поздняя загрузка сама по себе не побеждает. Частичное
покрытие и открытые вопросы остаются видимыми.

В разделе источников выдайте агенту ключ на выбранные документы и операции,
явно разрешив добавить его в аудитории этих источников. Новый документ требует
нового ключа с нужным набором источников и отзыва старого. Скачанная настройка
не означает подключённую модель. [Инструкция подключения](agent-contract.md#по-русски)
разделяет проверку чтения по HTTP и настройку внешнего клиента.

Внешний агент регистрирует контекст до действия и сообщает результат после
него. В разделе опыта вы можете подтвердить результат от своего имени.
Подтверждение владельцем, проверка настроенным в коде верификатором, завершение
интеграции и пригодность процедуры к повторному использованию являются разными
состояниями. Один успех не доказывает, что память стала причиной успеха.

Пауза сохраняет читаемый снимок. Отзыв закрывает живое чтение. Удаление стирает
живое содержимое и зависимые записи; при `cleanup_pending` очистка ещё не
завершена. Экспорт JSON и архив резервной копии содержат разрешённые данные и
тоже требуют приватного хранения. Команды выше работают с новым путём назначения.
Ключи и незавершённые предпросмотры не переносятся. Восстановление требует
отдельного пустого профиля и его нового ключа владельца; текущая рабочая папка
не перезаписывается. При восстановлении без
достоверной текущей истории записи проходят карантин, вашу проверку и повторную
проверку зависимостей. Потерянный ключ нельзя сбросить повторным `init`.

При ошибке проверьте выбранный Python, путь профиля и точный адрес сервера.
После истечения сессии войдите снова. `not_found` не раскрывает, отсутствует
запись или нет доступа. `recovery_required` требует проверки восстановления;
`bootstrap_required` означает отсутствие доверенного владельца нового профиля.
[Все ограничения](limitations.md#по-русски).
