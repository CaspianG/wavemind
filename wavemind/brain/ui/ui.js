// Safe DOM primitives and presentation copy. Source content is always text.
let language = 'ru';
export function setLanguage(value) { language = value === 'en' ? 'en' : 'ru'; document.documentElement.lang = language; }
const ru = {
  'An update accepts exactly one pasted text or one file.': 'Для обновления нужен ровно один текст или один файл.',
  'Cancellation discards a received preview. An interrupted request may leave an uncommitted draft until its 15-minute expiry; it is never saved automatically.': 'Отмена удаляет полученный предпросмотр. Прерванный запрос может оставить несохранённый черновик на 15 минут; автоматически он не сохраняется.',
  'Technical packet details': 'Технические сведения пакета', 'Current facts': 'Текущие факты', 'Reusable experience': 'Доступный опыт', 'Source quotations': 'Цитаты источников', 'No current facts in this selection.': 'В этой выборке нет текущих фактов.',
  'Coverage is partial; this is not a complete account.': 'Покрытие частичное; это не полное описание.',
  'Causal effects have not been established.': 'Причинные эффекты не установлены.',
  'Source text is untrusted data, not instructions.': 'Текст источников — недоверенные данные, а не инструкции.',
  'The safety filter is heuristic and cannot prevent every instruction-injection attempt.': 'Защитный фильтр эвристический и не предотвращает все попытки подмены инструкций.',
  'Selection uses a bounded local text search.': 'Выборка использует ограниченный локальный текстовый поиск.',
  'Conservative source tracking can omit reviewed history.': 'Консервативный учёт источников может исключать проверенную историю.',
  'Unresolved overlapping conflicts exclude whole records.': 'Неразрешённые пересекающиеся конфликты исключают записи целиком.',
  'Dependencies need rechecking; this packet cannot start an action.': 'Зависимости требуют перепроверки; этот пакет не позволяет начать действие.',
  'Restored sources await owner inspection in quarantine.': 'Восстановленные источники изолированы и ожидают проверки владельцем.',
  'Some content was omitted to fit the byte limit.': 'Часть содержимого исключена из-за ограничения размера.',
  'Facts': 'Факты', 'Citations': 'Цитаты', 'Network calls': 'Сетевые вызовы',
  'active': 'Подтверждено', 'proposed': 'Предложено', 'conflicted': 'Конфликт', 'superseded': 'Заменено', 'revoked': 'Отозвано', 'paused': 'Приостановлено', 'deleted': 'Удалено', 'quarantined': 'Изолировано',
  'pending': 'Ожидает обработки', 'partial': 'Частичное', 'completed': 'Завершено', 'cleanup_pending': 'Очистка не завершена', 'purged': 'Приватные данные очищены', 'unverified': 'Не проверено', 'verified': 'Проверено', 'failed': 'Неудачный результат', 'verification_failed': 'Проверка не выполнена', 'shadow': 'Ещё недостаточно проверок', 'manual': 'Ручное подтверждение', 'operator_attestation': 'Подтверждение оператора', 'configured': 'Настроенный проверяющий',
  'Rejected by owner': 'Отклонено владельцем',
  'Add or revise records': 'Добавить или исправить записи', 'Reveal key': 'Показать ключ',
  'fact': 'Факт', 'goal': 'Цель', 'constraint': 'Ограничение', 'decision': 'Решение', 'commitment': 'Обязательство', 'project': 'Проект', 'client': 'Клиент', 'person': 'Человек', 'organization': 'Организация', 'artifact': 'Объект',
  'related_to': 'Связано с', 'justified_by': 'Обосновано', 'depends_on': 'Зависит от', 'supersedes': 'Заменяет', 'action_outcome': 'Действие и результат',
  'Verification': 'Проверка', 'Verification source': 'Источник проверки', 'Verification method': 'Способ проверки', 'Verifier': 'Проверяющий', 'Reported steps': 'Сообщённые шаги', 'Integration status': 'Состояние интеграции', 'Status': 'Состояние', 'New audience': 'Новый круг читателей',
  'Project memory': 'Память проекта', 'Owner key': 'Ключ владельца', 'Sign in': 'Войти', 'Sign out': 'Выйти',
  'Projects': 'Проекты', 'Known and current': 'Что известно', 'Changes': 'Что изменилось', 'Experience': 'Опыт', 'Sources and access': 'Источники и доступ',
  'Personal project': 'Личный проект', 'Client workspace': 'Клиентский проект', 'Project name': 'Название проекта', 'Create memory': 'Создать память',
  'Source text': 'Текст источника', 'Source name': 'Название источника', 'Files': 'Файлы', 'Preview': 'Предпросмотр', 'Save source': 'Сохранить источник',
  'Cancel import': 'Отменить импорт', 'Import cancelled': 'Импорт отменён', 'Source saved': 'Источник сохранён', 'Audience': 'Кому доступен источник',
  'Only you': 'Только вам', 'Selected identities': 'Выбранным участникам', 'All live members (including future members)': 'Всем участникам, включая будущих',
  'Reader identities, one per line': 'Идентификаторы читателей, по одному в строке', 'Update source': 'Обновить источник', 'New source': 'Новый источник',
  'Data is not sent to an external model': 'Данные не отправляются внешней модели',
  'Model not connected. Entries below are owner-entered proposals, not AI extraction.': 'Модель не подключена. Ниже вы вводите предложения вручную; это не извлечение ИИ.',
  'D1 local pilot: plaintext storage for nonsecret materials. Python is required. Installation (D2), team deployment (D3), and real usefulness (D4) remain separate.': 'Локальный пилот D1: открытое хранение несекретных материалов. Нужен Python. Установка D2, командное развёртывание D3 и реальная полезность D4 — отдельные этапы.',
  'Keep decisions, constraints and their sources ready for your next session.': 'Сохраняйте решения, ограничения и источники для следующего обращения.',
  'No memories yet. Create your first project.': 'Памяти пока нет. Создайте первый проект.', 'No sources yet. Preview a note or file to begin.': 'Источников пока нет. Начните с предпросмотра заметки или файла.',
  'Citation source': 'Источник цитат', 'Versions': 'Версии', 'Current version': 'Текущая версия', 'All versions (history)': 'Все версии (история)',
  'Load citations': 'Загрузить цитаты', 'Load more citations': 'Ещё цитаты', 'Selected evidence': 'Выбранные свидетельства', 'Use citation': 'Выбрать цитату',
  'This is a page of citations. Load more when available. Source/version changes clear selection.': 'Это страница цитат. При наличии загрузите следующую. Смена источника или версии очищает выбор.',
  'Entity name': 'Название сущности', 'Entity kind': 'Тип сущности', 'Propose entity': 'Предложить сущность', 'Record ID': 'ID записи', 'Record type': 'Тип записи',
  'Topic key': 'Ключ темы', 'Record text': 'Текст записи', 'Project or client': 'Проект или клиент', 'Replaces record': 'Исправляет запись', 'Propose record': 'Предложить запись',
  'Valid from (UTC epoch, optional)': 'Действует с (UTC epoch, необязательно)', 'Valid until (exclusive, optional)': 'Действует до (не включая, необязательно)',
  'Relation kind': 'Тип связи', 'From record': 'От записи', 'To record': 'К записи', 'Propose relation': 'Предложить связь',
  'Approve': 'Подтвердить', 'Reject': 'Отклонить', 'Recheck': 'Перепроверить', 'No records yet. Propose a cited record, then review it.': 'Записей пока нет. Предложите запись с цитатой и подтвердите её.',
  'Context question': 'Вопрос для контекста', 'Context scope': 'Область контекста', 'All readable sources': 'Все доступные источники', 'Maximum bytes': 'Максимум байтов',
  'Build context': 'Собрать контекст', 'Validate current packet': 'Проверить актуальность пакета', 'Packet freshness': 'Актуальность пакета', 'Coverage': 'Покрытие',
  'Unknowns': 'Неизвестное', 'Conflicts': 'Конфликты', 'Warnings': 'Предупреждения', 'Expires': 'Истекает', 'Bytes': 'Байты', 'Estimated tokens': 'Оценка токенов',
  'Empty or unavailable scope has no fallback to other projects.': 'Пустая или недоступная область не заменяется другими проектами.',
  'History is conservative: overlapping unresolved conflicts can suppress whole records. It is not complete historical coverage.': 'История консервативна: неразрешённые пересекающиеся конфликты могут исключать запись целиком. Полное историческое покрытие не обещается.',
  'Recheck dependencies': 'Перепроверить зависимости', 'Graph pending': 'Граф ожидает проверки', 'No changes visible.': 'Доступных изменений нет.',
  'Refresh history': 'Обновить историю', 'More outcomes': 'Ещё результаты', 'More procedures': 'Ещё процедуры', 'No outcomes yet.': 'Результатов пока нет.',
  'Historical outcome': 'Исторический результат', 'Current procedure eligibility': 'Текущая применимость процедуры', 'Reporter': 'Кто сообщил', 'Receipt': 'Квитанция',
  'Reported steps, not observed execution or causality. One attestation does not establish eligibility.': 'Шаги сообщены, а не наблюдались; причинность не установлена. Одно подтверждение не доказывает применимость.',
  'Outcome to verify': 'Результат для проверки', 'Successful result': 'Успешный результат', 'Verification note': 'Примечание проверяющего', 'Attest result': 'Подтвердить результат',
  'Registered verifier ID': 'ID зарегистрированного проверяющего', 'Use registered verifier': 'Вызвать зарегистрированного проверяющего',
  'Manual attestation is your statement. A registered verifier must already be configured locally; this field cannot install code or URLs.': 'Ручное подтверждение — ваше свидетельство. Проверяющий должен быть заранее зарегистрирован локально; поле не устанавливает код или URL.',
  'Action description (not executed)': 'Описание действия (не выполняется)', 'Register preaction receipt': 'Зарегистрировать квитанцию перед действием',
  'Receipt ID': 'ID квитанции', 'Outcome summary': 'Описание результата', 'Reported steps, one per line': 'Сообщённые шаги, по одному в строке', 'Record outcome': 'Записать результат',
  'Pause': 'Приостановить', 'Resume': 'Возобновить', 'Revoke': 'Отозвать', 'Delete': 'Удалить', 'Apply audience': 'Применить доступ',
  'Pause stops ingestion; existing readable content remains readable. Revocation/deletion blocks future reads. Retained backups and data already forwarded to another client cannot be recalled.': 'Пауза останавливает загрузку; прежние данные остаются читаемыми. Отзыв/удаление блокирует новые чтения. Сохранённые копии и уже переданные клиенту данные отозвать нельзя.',
  'Confirm this source change?': 'Подтвердить изменение источника?', 'Agent label': 'Название агента', 'Allow proposals': 'Разрешить предложения', 'Allow outcome reports': 'Разрешить сообщения о результате',
  'Allow export': 'Разрешить экспорт', 'Grant source': 'Разрешить источник', 'Add this agent to the selected source audiences': 'Добавить этого агента к доступу выбранных источников',
  'Create agent key': 'Создать ключ агента', 'Setup generated; connection unverified': 'Настройка создана; соединение не проверено', 'One-time agent key': 'Одноразовый показ ключа агента',
  'Download HTTP check': 'Скачать HTTP-проверку', 'Hide key': 'Скрыть ключ', 'Currently readable source references': 'Сейчас доступные ссылки на источники',
  'Select sources deliberately. Source caps are immutable. For a new document, the owner imports it, creates a new scoped credential, and retires the old one. Source-capped agents cannot import.': 'Выбирайте источники явно. Ограничение ключа неизменно. Новый документ загружает владелец, затем создаёт новый ограниченный ключ и отзывает старый. Такие агенты не могут загружать источники.',
  'The downloaded Python check asks for the agent key (or WAVEMIND_BRAIN_TOKEN) and reads one allowed citation. Its successful result proves that HTTP read only; no AI model connection is implied.': 'Скачанная Python-проверка спрашивает ключ агента (или WAVEMIND_BRAIN_TOKEN) и читает разрешённую цитату. Успех подтверждает только это HTTP-чтение; подключение модели ИИ не подразумевается.',
  'Credentials': 'Ключи доступа', 'Revoke credential': 'Отозвать ключ', 'Confirm credential revocation? Historical ACL identities remain inert.': 'Отозвать ключ? Исторические ID доступа останутся неактивными.',
  'Export JSON': 'Экспорт JSON', 'Backup and recovery': 'Копии и восстановление', 'Managed sources': 'Управляемые источники', 'More managed sources': 'Ещё управляемые источники',
  'Review quarantined source': 'Просмотреть изолированный источник', 'Admit reviewed source': 'Допустить просмотренный источник', 'More versions': 'Ещё версии', 'More recovery citations': 'Ещё цитаты восстановления',
  'Admission is not semantic approval. Recheck records and earn fresh experience after cleanup.': 'Допуск не подтверждает смысл записей. Перепроверьте записи и накопите новый опыт после очистки.',
  'Backup uses the local CLI and a new destination. Restore requires an empty target and a trusted local owner; credentials are not restored. Existing archives are never rotated or deleted automatically.': 'Резервирование выполняется локальной CLI в новое назначение. Восстановление требует пустой цели и доверенного локального владельца; ключи не восстанавливаются. Старые архивы не удаляются автоматически.',
  'import_previews_not_restored: committed sources are preserved; unfinished imports and retry screens must be previewed again. Old preview IDs cannot resume. Source-version digest prevents duplicate commits.': 'import_previews_not_restored: сохранённые источники переносятся; незаконченный импорт и повторы требуют нового предпросмотра. Старые ID не возобновляются. Дайджест версии предотвращает дубликаты.',
  'Archive warnings describe the snapshot when created. Refresh live state. cleanup_pending means cleanup unfinished; purged means that private cleanup completed. Runtime status in export still requires_live_context_validation.': 'Предупреждения архива описывают снимок при создании. Обновляйте текущее состояние. cleanup_pending — очистка не завершена; purged — завершена. Статус процедуры в экспорте требует requires_live_context_validation.',
  'Choose a source and at least one citation.': 'Выберите источник и хотя бы одну цитату.', 'Choose at least one source.': 'Выберите хотя бы один источник.',
  'Session ended. Sign in again.': 'Сеанс завершён. Войдите снова.', 'Request failed. Check the visible fields and retry.': 'Запрос не выполнен. Проверьте поля и повторите.',
  'Working…': 'Выполняется…', 'Done': 'Готово', 'Select': 'Выберите', 'None': 'Нет', 'Refresh': 'Обновить',
};
export const t = key => language === 'ru' ? (ru[key] || key) : key;
export function showText(node, value) { node.textContent = String(value ?? ''); }
export function el(tag, text, attrs = {}) {
  const node = document.createElement(tag);
  if (text !== undefined) showText(node, text);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  return node;
}
export function add(parent, ...children) { parent.append(...children.filter(Boolean)); return parent; }
export function button(text, action, secondary = false) {
  const node = el('button', t(text), {type: 'button'});
  if (secondary) node.className = 'secondary';
  node.addEventListener('click', async event => {
    node.disabled = true;
    try { await action(event); } finally { node.disabled = false; }
  }); return node;
}
export function field(parent, name, {type = 'text', value = '', options, rows} = {}) {
  const label = el('label'); add(label, el('span', t(name)));
  const input = el(options ? 'select' : rows ? 'textarea' : 'input');
  if (options) for (const [id, title] of options) add(input, el('option', t(title), {value: id}));
  else if (!rows) input.type = type;
  input.setAttribute('aria-label', t(name));
  if (!options || options.some(option => option[0] === value)) input.value = value;
  if (type === 'password') input.autocomplete = 'off';
  if (type === 'file') input.multiple = true;
  add(label, input); add(parent, label); return input;
}
export function check(parent, name, checked = false) {
  const label = el('label', undefined, {class: 'check'}), input = el('input', undefined, {type: 'checkbox', 'aria-label': t(name)});
  input.checked = checked; add(label, input, el('span', t(name))); add(parent, label); return input;
}
export function card(parent, title, attrs = {}) { const node = el('div', undefined, {class: 'card', ...attrs}); if (title) add(node, el('h3', t(title))); add(parent, node); return node; }
export function note(parent, text) { add(parent, el('p', t(text), {class: 'muted'})); }
export function details(parent, title) { const node = el('details'); add(node, el('summary', t(title))); add(parent, node); return node; }
export function download(name, text, mime = 'application/json') {
  const url = URL.createObjectURL(new Blob([text], {type: mime}));
  const link = el('a', '', {href: url, download: name}); link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export const lines = input => input.value.split('\n').map(s => s.trim()).filter(Boolean);

export function citationPicker(parent, s) {
  const area = card(parent, 'Selected evidence');
  const source = field(area, 'Citation source', {options: [['', 'Select'], ...s.sources.map(x => [x.id, x.title])]});
  const mode = field(area, 'Versions', {options: [['current', 'Current version'], ['all', 'All versions (history)']]});
  const list = el('div'); let next = null, generation = 0; const selected = new Set();
  const reset = () => { generation++; next = null; selected.clear(); list.replaceChildren(); more.hidden = true; };
  source.onchange = reset; mode.onchange = reset;
  async function load(append) {
    if (!source.value) throw new Error(t('Choose a source and at least one citation.'));
    if (!append) reset();
    const current = generation;
    const query = new URLSearchParams({limit: '50', versions: mode.value});
    if (next) query.set('cursor', next);
    try {
      const page = await s.api(`${s.brain}/sources/${source.value}/citations?${query}`);
      if (current !== generation) return;
      for (const citation of page.citations) {
        const item = check(list, `${t('Use citation')} ${citation.id}`);
        item.onchange = () => item.checked ? selected.add(citation.id) : selected.delete(citation.id);
        add(list, el('blockquote', citation.text), el('small', `v${citation.version} · ${citation.id}`));
      }
      next = page.next_cursor; more.hidden = !next;
    } catch (error) { if (current !== generation) return; reset(); throw error; }
  }
  const more = button('Load more citations', () => s.run(() => load(true))); more.hidden = true;
  add(area, button('Load citations', () => s.run(() => load(false))), list, more);
  note(area, 'This is a page of citations. Load more when available. Source/version changes clear selection.');
  return () => { if (!selected.size) throw new Error(t('Choose a source and at least one citation.')); return [...selected]; };
}
