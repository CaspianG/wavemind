// Material Intelligence design: warm editorial canvas, tactile paper packets, cobalt memory thread, and calm motion.
import { useEffect, useState } from "react";
import { ArrowDownRight, ArrowUpRight, Check, Clipboard, Github, Menu, Minus, Plus, X } from "lucide-react";
import { AnimatePresence, motion } from "./motion";

const base = import.meta.env.BASE_URL;
const discussionsUrl = "https://github.com/CaspianG/wavemind/discussions";
type Language = "en" | "ru";

const initialLanguage = (): Language => {
  const requested = new URLSearchParams(window.location.search).get("lang");
  return requested === "ru" || requested === "en" ? requested : (localStorage.getItem("wavemind-language") as Language) || "en";
};

const content = {
  en: {
    nav: ["Why WaveMind", "The experience loop", "Proof", "Roadmap"],
    navIds: ["why", "loop", "proof", "roadmap"],
    cta: "Open a working conversation",
    eyebrow: "Verified experience for coding, support and operations agents",
    hero: <>Give every capable agent a memory <em>worth trusting.</em></>,
    lede: "Stop agents repeating a verified tool-work mistake. WaveMind turns traces and independent outcomes into small, cited Experience Packets with scope and rollback — runnable in five minutes.",
    explore: "Explore the thesis",
    repo: "View open-source repository",
    stamp: "LOCAL-FIRST · EVIDENCE-FIRST · MIT LICENSED",
    heroNote: "A new layer between raw context and action.",
    audience: { kicker: "THREE WAYS IN", title: <>One governed loop. <em>Three teams with costly repetition.</em></>, body: "WaveMind is for teams whose agents repeat tool work and need evidence before a learned procedure is reused.", roles: [["AGENT BUILDER", "Stop a repeated tool failure", "Carry one verified coding, support or operations procedure into the next run with scope and provenance.", "Run the demo"], ["PLATFORM TEAM", "Share one governed contract", "Use the same cited Experience Packet across Python, MCP, HTTP and agent frameworks.", "See the proof"], ["PRIVATE WORKFLOW", "Keep learning reversible", "Retain local control, explicit verification, namespace boundaries, deletion and rollback.", "Inspect evidence"]] },
    demo: { kicker: "A REAL PRODUCT LOOP", title: <>See the agent learn without <em>guessing.</em></>, body: "This is the product moment the site needs to make tangible: an outcome becomes evidence, evidence becomes a bounded procedure, and the next run receives a cited packet.", steps: [["Cold run", "The agent tries a workflow without prior experience and misses a required pagination cursor.", "Outcome: failed verification"], ["Independent check", "The environment, not the model, verifies the failed outcome and records the exact condition.", "Evidence: external state"], ["Shadow learning", "The same procedure succeeds repeatedly, but remains isolated until the evidence threshold is met.", "State: shadow procedure"], ["Verified reuse", "A held-out run receives one cited Experience Packet and completes the workflow with the validated cursor.", "State: promoted experience"]], terminal: "python examples/verified_experience_runtime.py", copy: "Copy command", source: "Open runnable source", evidence: "Open exact evidence" },
    conversion: { kicker: "FROM INTEREST TO PROOF", title: <>A serious idea needs a <em>serious next step.</em></>, investor: ["For investors", "The thesis", "WaveMind sits between raw context and action: a neutral experience-governance layer that makes agent learning inspectable, portable and reversible.", "Read the investor thesis"], partner: ["For design partners", "The pilot", "Start with one repeated tool workflow. Define success, instrument the learning loop and review the evidence after 30 days — before expanding the scope.", "Start a technical discussion"], facts: ["Open-source core", "Local-first source of truth", "Evidence-gated public claims"] },
    why: {
      kicker: "01 / WHY NOW",
      title: <>Context makes agents capable. <em>Experience makes them better.</em></>,
      body: "Most agent memory systems keep adding. They collect chat history, store fragments, and hope retrieval will decide what is true. But agents need more than recall. They need a way to learn which procedures worked, when they are safe to reuse, and when to forget them.",
      quote: "The next generation of agents will not simply remember more. They will learn more responsibly.",
      old: "Raw context", oldText: "Everything is retained. Nothing is resolved.",
      new: "Verified experience", newText: "A useful decision carries its source, boundary and exit path.",
    },
    loop: {
      kicker: "02 / THE EXPERIENCE LOOP",
      title: <>From one good outcome to a <em>better next run.</em></>,
      body: "WaveMind gives learning a lifecycle. It records what happened, waits for independent evidence, promotes only reliable procedures and serves the next run a compact packet — not a history dump.",
      steps: [
        ["Notice", "Capture the trace, tool call, environment and outcome."],
        ["Verify", "Let tests, operators or downstream state confirm the result."],
        ["Promote", "Keep new procedures in shadow until repeat evidence earns trust."],
        ["Apply", "Return the right experience, with a clear scope and rollback path."],
      ],
    },
    packet: {
      kicker: "03 / THE UNIT OF TRUST",
      title: <>Meet the <em>Experience Packet.</em></>,
      body: "A compact, cited object that tells an agent what to do, why it can do it, and when it should not.",
      states: ["Verified", "In review", "Rolled back"],
      tags: ["REPEAT EVIDENCE", "HUMAN REVIEW", "SUPERSEDED"],
      titles: ["Retry the request using the validated pagination cursor.", "Ask for the billing period before issuing a refund.", "Stop using the previous export-token workflow."],
      text: ["Observed across 12 independent support runs.", "Strong signal, held until one more independent check.", "Environment changed. The source remains visible; the advice does not."],
      evidence: ["12 independent runs", "2 of 3 verifications", "Archived safely"],
      caption: "Each packet has a visible history, a scope and a way out.",
      provenance: "Source attached",
      boundary: "Scope: support/*",
    },
    proof: {
      kicker: "04 / THE PROOF LEDGER",
      title: <>Proof belongs in the <em>product.</em></>,
      body: "We do not hide the edges of what has been measured. WaveMind treats evidence as a first-class part of memory — including what is validated, what is historical and what still needs to be proven.",
      figures: [["−39.2%", "less context", "on frozen stateful tasks"], ["100%", "task success", "in an admitted 150-task runtime slice"], ["0", "cross-namespace leaks", "in 375 contained safety attacks"]],
      note: "Claim boundary", noteText: "Generalized quality uplift, remote multi-region, managed serverless and 100M service claims remain gated. We think that honesty compounds.",
      read: "Read the evidence notes",
    },
    cases: {
      kicker: "05 / WHERE IT MATTERS",
      title: <>Memory becomes strategic when work <em>repeats.</em></>,
      items: [["Coding agents", "Carry validated fixes and environment-specific procedures between runs."], ["Support teams", "Remember corrections without bringing stale policy into the next customer conversation."], ["Operations agents", "Turn successful tool runs into auditable, scoped routines before reuse."], ["Agent platforms", "Share one portable experience lifecycle instead of rebuilding governance per framework."], ["Private workflows", "Learn locally with provenance, approval, deletion and rollback evidence."]],
    },
    roadmap: { kicker: "06 / THE BUILD", title: <>Proof before <em>surface area.</em></>, body: "Publish the safe upgrade, prove independent task lift against real alternatives, then expand only where pilot usage validates demand.", years: ["NOW", "0–6M", "6–18M"], items: [["Ship truthfully", "Publish and clean-install verify 2.13.0; keep exact-current competitive evidence public."], ["Prove the flagship", "Admit one cold-run to verified packet to better next-run workflow with paired outcome, context, cost and rollback evidence."], ["Follow observed demand", "Add review inbox, policy-as-code or cross-client experience only after design partners use and value them."]] },
    closing: { eyebrow: "THE NEXT CHAPTER", title: <>Let’s make agent learning <em>responsible by design.</em></>, body: "For investors and design partners building systems that have to become more useful over time — without becoming less trustworthy.", primary: "Open a working conversation", secondary: "Inspect the repository" },
    footer: "WaveMind · Adaptive memory, with a trail you can inspect.",
  },
  ru: {
    nav: ["Зачем WaveMind", "Цикл опыта", "Доказательства", "План"],
    navIds: ["why", "loop", "proof", "roadmap"],
    cta: "Начать предметный разговор",
    eyebrow: "Проверенный опыт для кодовых, support- и ops-агентов",
    hero: <>Дайте каждому сильному агенту память, <em>которой можно доверять.</em></>,
    lede: "Не давайте агентам повторять уже проверенную ошибку в работе с инструментами. WaveMind превращает trace и независимый outcome в компактный cited Experience Packet со scope и rollback — за пять минут.",
    explore: "Посмотреть идею",
    repo: "Открыть репозиторий",
    stamp: "LOCAL-FIRST · EVIDENCE-FIRST · ЛИЦЕНЗИЯ MIT",
    heroNote: "Новый слой между сырым контекстом и действием.",
    audience: { kicker: "ТРИ ПУТИ ВНУТРЬ", title: <>Один управляемый цикл. <em>Три команды с дорогими повторами.</em></>, body: "WaveMind нужен командам, чьи агенты повторяют tool work и обязаны получить evidence до повторного применения процедуры.", roles: [["AGENT BUILDER", "Остановить повторную tool-ошибку", "Перенесите одну проверенную coding, support или ops-процедуру в следующий запуск со scope и provenance.", "Запустить демо"], ["PLATFORM TEAM", "Разделить один governed contract", "Используйте тот же cited Experience Packet в Python, MCP, HTTP и agent frameworks.", "Открыть proof"], ["PRIVATE WORKFLOW", "Сохранить обратимость обучения", "Local control, независимая проверка, namespace boundaries, deletion и rollback.", "Проверить evidence"]] },
    demo: { kicker: "РЕАЛЬНЫЙ ПРОДУКТОВЫЙ ЦИКЛ", title: <>Посмотрите, как агент учится <em>без догадок.</em></>, body: "Вот product moment, который делает идею осязаемой: outcome становится evidence, evidence становится ограниченной процедурой, а следующий запуск получает cited packet.", steps: [["Холодный запуск", "Агент пробует workflow без прошлого опыта и пропускает обязательный курсор пагинации.", "Outcome: failed verification"], ["Независимая проверка", "Окружение, а не модель, подтверждает провал и записывает точное условие.", "Evidence: external state"], ["Обучение в shadow", "Та же процедура повторно проходит успешно, но остаётся изолированной, пока не выполнен порог evidence.", "State: shadow procedure"], ["Проверенное повторное применение", "Held-out запуск получает один cited Experience Packet и завершает workflow с проверенным курсором.", "State: promoted experience"]], terminal: "python examples/verified_experience_runtime.py", copy: "Скопировать команду", source: "Открыть исходник", evidence: "Открыть exact evidence" },
    conversion: { kicker: "ОТ ИНТЕРЕСА К PROOF", title: <>Серьёзной идее нужен <em>серьёзный следующий шаг.</em></>, investor: ["Для инвесторов", "Тезис", "WaveMind находится между сырым контекстом и действием: нейтральный слой управления опытом, который делает обучение агентов прозрачным, переносимым и обратимым.", "Прочитать инвестиционный тезис"], partner: ["Для design partners", "Pilot", "Начните с одного повторяемого tool workflow. Определите успех, подключите learning loop и разберите evidence через 30 дней — до расширения scope.", "Начать техническое обсуждение"], facts: ["Open-source core", "Local-first source of truth", "Evidence-gated public claims"] },
    why: {
      kicker: "01 / ПОЧЕМУ СЕЙЧАС",
      title: <>Контекст делает агентов сильными. <em>Опыт делает их лучше.</em></>,
      body: "Большинство систем памяти для агентов просто продолжают накапливать. Они собирают историю чата, сохраняют фрагменты и надеются, что retrieval сам решит, что верно. Но агентам нужно больше, чем recall: им нужен способ понять, какие процедуры сработали, когда их безопасно использовать снова и когда о них нужно забыть.",
      quote: "Следующее поколение агентов не будет просто помнить больше. Оно будет учиться ответственнее.",
      old: "Сырой контекст", oldText: "Сохраняется всё. Ничто не получает решения.",
      new: "Проверенный опыт", newText: "Полезное решение несёт источник, границу применимости и путь отката.",
    },
    loop: {
      kicker: "02 / ЦИКЛ ОПЫТА",
      title: <>От одного удачного результата к <em>лучшему следующему запуску.</em></>,
      body: "WaveMind даёт обучению жизненный цикл. Он сохраняет, что произошло, ждёт независимого evidence, продвигает только надёжные процедуры и передаёт следующему запуску компактный пакет, а не историю целиком.",
      steps: [["Заметить", "Зафиксировать trace, вызов инструмента, окружение и результат."], ["Проверить", "Дать тестам, операторам или состоянию системы подтвердить исход."], ["Продвинуть", "Держать новые процедуры в shadow-режиме, пока повторяемый evidence не заслужит доверия."], ["Применить", "Вернуть нужный опыт с ясным scope и путём rollback."]],
    },
    packet: {
      kicker: "03 / ЕДИНИЦА ДОВЕРИЯ",
      title: <>Познакомьтесь с <em>Experience Packet.</em></>,
      body: "Компактный объект с источниками: он говорит агенту, что делать, почему это можно сделать и когда делать этого не стоит.",
      states: ["Проверено", "На проверке", "Откат"],
      tags: ["ПОВТОРЯЕМЫЙ EVIDENCE", "ПРОВЕРКА ЧЕЛОВЕКОМ", "ЗАМЕНЕНО"],
      titles: ["Повторить запрос с проверенным курсором пагинации.", "Уточнить расчётный период до оформления возврата.", "Не использовать предыдущий workflow export-token."],
      text: ["Подтверждено в 12 независимых запусках поддержки.", "Сильный сигнал, но нужен ещё один независимый check.", "Окружение изменилось. Источник виден, совет больше не применяется."],
      evidence: ["12 независимых запусков", "2 из 3 проверок", "Безопасно архивировано"],
      caption: "У каждого пакета есть видимая история, scope и путь выхода.",
      provenance: "Источник приложен",
      boundary: "Scope: support/*",
    },
    proof: {
      kicker: "04 / КНИГА ДОКАЗАТЕЛЬСТВ",
      title: <>Доказательства — часть <em>продукта.</em></>,
      body: "Мы не скрываем границы измеренного. WaveMind делает evidence полноценной частью памяти: в том числе того, что проверено, что исторично и что ещё требует доказательства.",
      figures: [["−39.2%", "меньше контекста", "на frozen stateful tasks"], ["100%", "успех задач", "на допущенном срезе runtime из 150 задач"], ["0", "утечек между namespaces", "в 375 сдержанных safety-атаках"]],
      note: "Граница claim", noteText: "Generalized quality uplift, remote multi-region, managed serverless и 100M service claims всё ещё gated. Мы считаем, что такая честность накапливает доверие.",
      read: "Открыть evidence notes",
    },
    cases: {
      kicker: "05 / ГДЕ ЭТО ВАЖНО",
      title: <>Память становится стратегической, когда работа <em>повторяется.</em></>,
      items: [["Кодовые агенты", "Переносите проверенные фиксы и процедуры с учётом окружения между запусками."], ["Поддержка", "Помните исправления, не перенося устаревшую policy в следующий разговор с клиентом."], ["Операционные агенты", "Превращайте удачные tool runs в проверяемые процедуры с ограниченным scope до повторного использования."], ["Agent platforms", "Делите один переносимый lifecycle опыта вместо отдельного governance для каждого framework."], ["Private workflows", "Учитесь локально с provenance, approval, deletion и rollback evidence."]],
    },
    roadmap: { kicker: "06 / СОЗДАЁМ", title: <>Сначала proof, затем <em>новые поверхности.</em></>, body: "Публикуем безопасное обновление, доказываем task lift против реальных альтернатив и расширяемся только по подтверждённому pilot demand.", years: ["СЕЙЧАС", "0–6М", "6–18М"], items: [["Публиковать честно", "Выпустить и clean-install проверить 2.13.0; держать exact-current competitive evidence публичным."], ["Доказать flagship", "Допустить workflow от cold run до verified packet и лучшего next run с paired outcome, context, cost и rollback evidence."], ["Следовать спросу", "Добавлять review inbox, policy-as-code или cross-client experience только после реального использования design partners."]] },
    closing: { eyebrow: "СЛЕДУЮЩАЯ ГЛАВА", title: <>Давайте сделаем обучение агентов <em>ответственным по умолчанию.</em></>, body: "Для инвесторов и design partners, которые создают системы, обязанные становиться полезнее со временем — не теряя доверия.", primary: "Начать предметный разговор", secondary: "Изучить репозиторий" },
    footer: "WaveMind · Адаптивная память с историей, которую можно проверить.",
  },
} as const;

const packetColors = ["verified", "review", "archive"];
const motionEase: [number, number, number, number] = [0.23, 1, 0.32, 1];
const rise = { initial: { opacity: 0, y: 22 }, whileInView: { opacity: 1, y: 0 }, viewport: { once: true, amount: 0.25 }, transition: { duration: 0.55, ease: motionEase } };

export default function Home() {
  const [language, setLanguage] = useState<Language>(initialLanguage);
  const [packet, setPacket] = useState(0);
  const [menuOpen, setMenuOpen] = useState(false);
  const [openRoadmap, setOpenRoadmap] = useState<number | null>(0);
  const [demoStep, setDemoStep] = useState(0);
  const [copied, setCopied] = useState(false);
  const t = content[language];

  useEffect(() => {
    localStorage.setItem("wavemind-language", language);
    document.documentElement.lang = language;
    document.title = language === "ru" ? "WaveMind — Память, которой можно доверять" : "WaveMind — Memory Worth Trusting";
    const url = new URL(window.location.href); url.searchParams.set("lang", language); window.history.replaceState({}, "", url);
  }, [language]);

  const jump = (id: string) => { setMenuOpen(false); document.getElementById(id)?.scrollIntoView({ behavior: "smooth" }); };
  const copyCommand = async () => {
    await navigator.clipboard.writeText(t.demo.terminal);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  };

  return <main className="mi-site">
    <header className="mi-nav">
      <button className="mi-brand" onClick={() => jump("top")} aria-label="WaveMind home"><span className="mi-mark" aria-hidden="true"><i /><i /></span><span>WAVEMIND</span></button>
      <nav className="mi-links">{t.nav.map((label, index) => <button key={label} onClick={() => jump(t.navIds[index])}>{label}</button>)}</nav>
      <div className="mi-nav-actions"><LanguageSwitch language={language} setLanguage={setLanguage} /><a className="mi-evidence-link" href={`${base}evidence/`}>Evidence</a><a className="mi-github" href="https://github.com/CaspianG/wavemind" target="_blank" rel="noreferrer"><Github size={16} /><span>GitHub</span></a><button className="mi-nav-cta" onClick={() => jump("contact")}>{t.cta}<ArrowUpRight size={15} /></button><button className="mi-menu" onClick={() => setMenuOpen(!menuOpen)} aria-label="Menu">{menuOpen ? <X size={21} /> : <Menu size={21} />}</button></div>
      <AnimatePresence>{menuOpen && <motion.div className="mi-mobile-menu" initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: .2 }}>{t.nav.map((label, index) => <button key={label} onClick={() => jump(t.navIds[index])}>{label}</button>)}<LanguageSwitch language={language} setLanguage={setLanguage} /></motion.div>}</AnimatePresence>
    </header>

    <section className="mi-hero" id="top"><div className="mi-thread hero-thread" aria-hidden="true"><span /><i /><i /><i /></div><motion.div className="mi-hero-copy" {...rise}><div className="mi-eyebrow"><span />{t.eyebrow}</div><h1>{t.hero}</h1><p>{t.lede}</p><div className="mi-hero-actions"><button className="mi-primary" onClick={() => jump("why")}>{t.explore}<ArrowDownRight size={17} /></button><a className="mi-secondary" href="https://github.com/CaspianG/wavemind" target="_blank" rel="noreferrer">{t.repo}<ArrowUpRight size={15} /></a></div><span className="mi-stamp">{t.stamp}</span></motion.div><motion.div className="mi-hero-art" initial={{ opacity: 0, scale: .97, y: 18 }} animate={{ opacity: 1, scale: 1, y: 0 }} transition={{ duration: .8, delay: .08, ease: motionEase }}><div className="mi-hero-object" aria-label="Verified experience packet"><span className="mi-object-sheet sheet-one"/><span className="mi-object-sheet sheet-two"/><span className="mi-object-thread"/><span className="mi-object-seal"><Check size={18}/>verified</span></div><div className="mi-art-note"><span>WAVEMIND / 01</span><strong>{t.heroNote}</strong></div><div className="mi-art-chip"><span>verified</span><Check size={13}/></div></motion.div></section>

    <section className="mi-audience"><motion.div className="mi-audience-head" {...rise}><span className="mi-kicker">{t.audience.kicker}</span><h2>{t.audience.title}</h2><p>{t.audience.body}</p></motion.div><div className="mi-audience-grid">{t.audience.roles.map(([kind, title, body, action], index) => <motion.article className={`mi-audience-card role-${index}`} {...rise} transition={{ ...rise.transition, delay: index * .08 }} key={kind}><span>{kind}</span><h3>{title}</h3><p>{body}</p><button onClick={() => jump(index === 0 ? "demo" : "proof")}>{action}<ArrowDownRight size={16}/></button></motion.article>)}</div></section>

    <section className="mi-why" id="why"><span className="mi-margin-note why-note">MEMORY / 01<br/>AN ANNOTATED THESIS</span><motion.div className="mi-section-head" {...rise}><span className="mi-kicker">{t.why.kicker}</span><h2>{t.why.title}</h2></motion.div><motion.div className="mi-why-grid" {...rise}><div className="mi-body-copy"><p>{t.why.body}</p><blockquote>“{t.why.quote}”</blockquote></div><div className="mi-compare"><div className="mi-compare-card old"><span>01</span><h3>{t.why.old}</h3><p>{t.why.oldText}</p></div><div className="mi-compare-arrow">→</div><div className="mi-compare-card new"><span>02</span><h3>{t.why.new}</h3><p>{t.why.newText}</p></div></div></motion.div></section>

    <section className="mi-loop" id="loop"><div className="mi-loop-seal"><span className="mi-mark" aria-hidden="true"><i /><i /></span><span>VERIFY<br/>BEFORE<br/>REUSE</span></div><motion.div className="mi-loop-intro" {...rise}><div><span className="mi-kicker">{t.loop.kicker}</span><h2>{t.loop.title}</h2></div><p>{t.loop.body}</p></motion.div><div className="mi-loop-flow">{t.loop.steps.map(([title, text], index) => <motion.article className="mi-step" key={title} {...rise} transition={{ ...rise.transition, delay: index * .07 }}><span className="mi-step-index">0{index + 1}</span><div className="mi-step-dot"/><h3>{title}</h3><p>{text}</p></motion.article>)}</div></section>

    <section className="mi-demo" id="demo"><motion.div className="mi-demo-intro" {...rise}><span className="mi-kicker">{t.demo.kicker}</span><h2>{t.demo.title}</h2><p>{t.demo.body}</p></motion.div><motion.div className="mi-demo-sandbox" {...rise}><div className="mi-demo-steps">{t.demo.steps.map(([title, text, status], index) => <button key={title} className={demoStep === index ? "active" : ""} onClick={() => setDemoStep(index)}><span>0{index + 1}</span><div><strong>{title}</strong><small>{status}</small></div></button>)}</div><AnimatePresence mode="wait"><motion.div className="mi-demo-output" key={demoStep} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: .24, ease: motionEase }}><div className="mi-window-bar"><span/><span/><span/><code>experience/runtime</code></div><div className="mi-demo-state"><span>{t.demo.steps[demoStep][2]}</span><div className={`mi-demo-status status-${demoStep}`}><i/>{demoStep === 3 ? "verified" : demoStep === 2 ? "shadow" : demoStep === 1 ? "recorded" : "observed"}</div></div><h3>{t.demo.steps[demoStep][0]}</h3><p>{t.demo.steps[demoStep][1]}</p><div className="mi-demo-trace"><span>trace_id: 8f22</span><span>namespace: support/*</span><span>provenance: attached</span></div></motion.div></AnimatePresence></motion.div><motion.div className="mi-demo-actions" {...rise}><code>$ {t.demo.terminal}</code><button onClick={copyCommand}><Clipboard size={14}/>{copied ? (language === "ru" ? "Скопировано" : "Copied") : t.demo.copy}</button><a href="https://github.com/CaspianG/wavemind/blob/main/examples/verified_experience_runtime.py" target="_blank" rel="noreferrer">{t.demo.source}<ArrowUpRight size={14}/></a><a href={`${base}evidence/`}>{t.demo.evidence}<ArrowUpRight size={14}/></a></motion.div></section>

    <section className="mi-product" id="developers"><motion.div className="mi-product-copy" {...rise}><span className="mi-kicker">{language === "ru" ? "РАБОЧИЙ ПРОДУКТ" : "WORKING PRODUCT"}</span><h2>{language === "ru" ? "Память видно, можно проверить и контролировать." : "Memory you can see, verify and control."}</h2><p>{language === "ru" ? "WaveMind Studio показывает воспоминания, происхождение, статусы проверки и границы пространств имён. MCP и Python API подключают тот же слой к вашим агентам." : "WaveMind Studio exposes memories, provenance, verification state and namespace boundaries. MCP and the Python API connect the same layer to your agents."}</p><div className="mi-product-actions"><a className="mi-primary" href="https://github.com/CaspianG/wavemind#quick-start" target="_blank" rel="noreferrer">Quick start <ArrowUpRight size={16}/></a><a className="mi-secondary" href={`${base}evidence/`}>Open evidence <ArrowUpRight size={16}/></a></div></motion.div><motion.figure className="mi-product-screen" {...rise}><img src={`${base}wavemind-studio.png`} alt="WaveMind Studio memory inspection interface"/><figcaption>WaveMind Studio / local-first inspection</figcaption></motion.figure></section>

    <section className="mi-packet-section"><div className="mi-packet-intro"><motion.div {...rise}><span className="mi-kicker">{t.packet.kicker}</span><h2>{t.packet.title}</h2><p>{t.packet.body}</p></motion.div><motion.div className="mi-paper-sculpture" {...rise}><div className="paper-layer layer-a"/><div className="paper-layer layer-b"/><div className="paper-layer layer-c"/><div className="paper-thread"/><span>experience archive</span></motion.div></div><motion.div className="mi-packet-stage" {...rise}><div className="mi-packet-tabs">{t.packet.states.map((state, index) => <button key={state} onClick={() => setPacket(index)} className={packet === index ? "active" : ""}><span>{String(index + 1).padStart(2, "0")}</span>{state}</button>)}</div><AnimatePresence mode="wait"><motion.div key={packet} className={`mi-packet-card ${packetColors[packet]}`} initial={{ opacity: 0, y: 10, rotate: -0.8 }} animate={{ opacity: 1, y: 0, rotate: packet === 1 ? .65 : 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: .28, ease: motionEase }}><div className="mi-packet-card-head"><span>{t.packet.tags[packet]}</span><span>EXP–00{42 + packet}</span></div><div className="mi-packet-fold"/><h3>{t.packet.titles[packet]}</h3><p>{t.packet.text[packet]}</p><div className="mi-packet-proof"><span><Check size={14}/>{t.packet.evidence[packet]}</span><span>{t.packet.boundary}</span></div><div className="mi-packet-card-foot"><span>{t.packet.provenance}</span><ArrowUpRight size={15}/></div></motion.div></AnimatePresence><p className="mi-packet-caption">{t.packet.caption}</p></motion.div></section>

    <section className="mi-proof" id="proof"><div className="mi-proof-tabs" aria-hidden="true"><span>LEDGER</span><span>CLAIMS</span><span>NOTES</span></div><motion.div className="mi-proof-title" {...rise}><span className="mi-kicker">{t.proof.kicker}</span><h2>{t.proof.title}</h2><p>{t.proof.body}</p></motion.div><motion.div className="mi-proof-ledger" {...rise}><div className="mi-ledger-rule"/>{t.proof.figures.map(([value, label, note]) => <div className="mi-figure" key={label}><strong>{value}</strong><span>{label}</span><small>{note}</small></div>)}<div className="mi-claim-note"><div><span className="mi-note-mark">!</span><span className="mi-note-label">{t.proof.note}</span></div><p>{t.proof.noteText}</p><a href="https://github.com/CaspianG/wavemind/blob/main/docs/data/product-status.json" target="_blank" rel="noreferrer">{t.proof.read}<ArrowUpRight size={14}/></a></div></motion.div></section>

    <section className="mi-cases"><motion.div className="mi-cases-heading" {...rise}><span className="mi-kicker">{t.cases.kicker}</span><h2>{t.cases.title}</h2></motion.div><div className="mi-case-grid">{t.cases.items.map(([title, body], index) => <motion.article key={title} className={`mi-case case-${index}`} {...rise} transition={{ ...rise.transition, delay: index * .08 }}><span className="mi-case-index">0{index + 1}</span><div className="mi-case-fold"/><div className="mi-case-orb"/><h3>{title}</h3><p>{body}</p><ArrowUpRight size={18}/></motion.article>)}</div></section>

    <section className="mi-conversion" id="conversion"><motion.div className="mi-conversion-head" {...rise}><span className="mi-kicker">{t.conversion.kicker}</span><h2>{t.conversion.title}</h2></motion.div><div className="mi-conversion-grid"><motion.article className="mi-conversion-card investor-card" {...rise}><span>{t.conversion.investor[0]}</span><h3>{t.conversion.investor[1]}</h3><p>{t.conversion.investor[2]}</p><a href={discussionsUrl} target="_blank" rel="noreferrer">{t.conversion.investor[3]}<ArrowUpRight size={15}/></a></motion.article><motion.article className="mi-conversion-card partner-card" {...rise} transition={{ ...rise.transition, delay:.08 }}><span>{t.conversion.partner[0]}</span><h3>{t.conversion.partner[1]}</h3><p>{t.conversion.partner[2]}</p><a href={discussionsUrl} target="_blank" rel="noreferrer">{t.conversion.partner[3]}<ArrowUpRight size={15}/></a></motion.article></div><motion.div className="mi-confidence-strip" {...rise}>{t.conversion.facts.map((fact, index) => <span key={fact}><i>{index + 1}</i>{fact}</span>)}</motion.div></section>

    <section className="mi-roadmap" id="roadmap"><motion.div className="mi-roadmap-intro" {...rise}><div className="mi-roadmap-mark"><span className="mi-mark" aria-hidden="true"><i /><i /></span><span>THE<br/>BUILD</span></div><span className="mi-kicker">{t.roadmap.kicker}</span><h2>{t.roadmap.title}</h2><p>{t.roadmap.body}</p></motion.div><div className="mi-roadmap-list">{t.roadmap.items.map(([title, body], index) => <motion.article className={`mi-roadmap-item ${openRoadmap === index ? "open" : ""}`} key={title} {...rise} transition={{ ...rise.transition, delay: index * .07 }}><button onClick={() => setOpenRoadmap(openRoadmap === index ? null : index)}><span>{t.roadmap.years[index]}</span><strong>{title}</strong>{openRoadmap === index ? <Minus size={18}/> : <Plus size={18}/>}</button><AnimatePresence>{openRoadmap === index && <motion.p initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }} transition={{ duration: .24 }}>{body}</motion.p>}</AnimatePresence></motion.article>)}</div></section>

    <section className="mi-closing" id="contact"><div className="mi-closing-sphere"/><div className="mi-closing-paper" aria-hidden="true"><span>WAVEMIND / MEMORY NOTE</span><i/></div><motion.div {...rise}><span className="mi-closing-mark mi-mark" aria-hidden="true"><i /><i /></span><span className="mi-kicker">{t.closing.eyebrow}</span><h2>{t.closing.title}</h2><p>{t.closing.body}</p><div className="mi-hero-actions"><a className="mi-primary" href={discussionsUrl} target="_blank" rel="noreferrer">{t.closing.primary}<ArrowUpRight size={17}/></a><a className="mi-secondary" href="https://github.com/CaspianG/wavemind" target="_blank" rel="noreferrer">{t.closing.secondary}<Github size={15}/></a></div></motion.div></section>
    <footer className="mi-footer"><span>{t.footer}</span><span>© 2026</span></footer>
  </main>;
}

function LanguageSwitch({ language, setLanguage }: { language: Language; setLanguage: (language: Language) => void }) { return <div className="mi-language" aria-label="Language"><button className={language === "en" ? "active" : ""} onClick={() => setLanguage("en")}>EN</button><span>·</span><button className={language === "ru" ? "active" : ""} onClick={() => setLanguage("ru")}>RU</button></div>; }

