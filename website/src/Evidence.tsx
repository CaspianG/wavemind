import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, ArrowUpRight, Check, CircleAlert, FileJson, Github, LoaderCircle, ShieldCheck } from "lucide-react";

type EvidenceStatus = "admitted" | "blocked" | "historical" | "unknown";

type EvidenceDocument = {
  admitted?: boolean;
  status?: string;
  source_sha?: string;
  checked_in_source_sha?: string;
  generated_at?: string;
  claim_boundary?: string;
  checks_passed?: number;
  checks_total?: number;
  implemented_rows?: number;
  required_rows?: number;
};

type EvidenceEntry = {
  title: string;
  summary: string;
  file: string;
};

const evidence: EvidenceEntry[] = [
  { title: "Safe Product", summary: "Authentication, isolation, fail-closed networking, persistence and upgrade safety.", file: "safe_product_admission_results.json" },
  { title: "Workspace Experience", summary: "Verified learning across real workspaces, clients and approval boundaries.", file: "workspace_experience_admission_results.json" },
  { title: "Verified Experience", summary: "Trace, independent verification and reusable experience packets.", file: "verified_experience_admission_results.json" },
  { title: "Memory OS", summary: "Maintenance, caching, prefetch, learning, forgetting and consolidation.", file: "memory_os_admission_results.json" },
  { title: "Multimodal Memory", summary: "Real encoders, cross-modal retrieval and object-store lifecycle.", file: "multimodal_admission_results.json" },
  { title: "Agent Memory Advantage", summary: "Controlled evidence of agent-quality improvement and its current limits.", file: "agent_memory_advantage_admission_results.json" },
  { title: "Evaluation Validity", summary: "Whether benchmark methodology is strong enough to support product claims.", file: "evaluation_validity_admission_results.json" },
];

function normalizedStatus(document?: EvidenceDocument): EvidenceStatus {
  if (!document) return "unknown";
  if (document.status === "historical") return "historical";
  if (document.admitted === true || document.status === "admitted") return "admitted";
  if (document.admitted === false || document.status === "blocked") return "blocked";
  return "unknown";
}

function compactSha(sha?: string) {
  return sha ? sha.slice(0, 10) : "not recorded";
}

export default function Evidence() {
  const [documents, setDocuments] = useState<Record<string, EvidenceDocument>>({});
  const [loading, setLoading] = useState(true);
  const base = import.meta.env.BASE_URL;
  const sourceSha = import.meta.env.VITE_SOURCE_SHA || "local-build";

  useEffect(() => {
    let active = true;
    Promise.all(evidence.map(async ({ file }) => {
      const response = await fetch(`${base}data/${file}`);
      if (!response.ok) throw new Error(`${file}: ${response.status}`);
      return [file, await response.json()] as const;
    }))
      .then((rows) => active && setDocuments(Object.fromEntries(rows)))
      .catch(() => active && setDocuments({}))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [base]);

  const counts = useMemo(() => evidence.reduce((result, item) => {
    const status = normalizedStatus(documents[item.file]);
    result[status] += 1;
    return result;
  }, { admitted: 0, blocked: 0, historical: 0, unknown: 0 } as Record<EvidenceStatus, number>), [documents]);

  return <main className="evidence-page">
    <header className="evidence-nav">
      <a className="mi-brand" href={base} aria-label="WaveMind home"><span className="mi-mark" aria-hidden="true"><i /><i /></span><span>WAVEMIND</span></a>
      <div>
        <a href={base}><ArrowLeft size={15} />Product</a>
        <a href="https://github.com/CaspianG/wavemind" target="_blank" rel="noreferrer"><Github size={15} />GitHub</a>
      </div>
    </header>

    <section className="evidence-hero">
      <span className="mi-kicker">PUBLIC EVIDENCE LEDGER</span>
      <h1>Proof before claims.</h1>
      <p>Every result keeps its source SHA, status and claim boundary visible. A blocked or historical result stays visible instead of being presented as a current win.</p>
      <div className="evidence-summary">
        <span><strong>{counts.admitted}</strong> admitted snapshots</span>
        <span><strong>{counts.blocked}</strong> blocked snapshots</span>
        <span><strong>{counts.historical}</strong> historical snapshots</span>
      </div>
      <small>Site source: <code>{compactSha(sourceSha)}</code>. Checked-in evidence may describe an older SHA; exact-current claims require the matching CI artifact.</small>
    </section>

    <section className="evidence-ledger" aria-busy={loading}>
      {loading && <div className="evidence-loading"><LoaderCircle size={18} />Loading signed evidence index...</div>}
      {!loading && evidence.map((item) => {
        const document = documents[item.file];
        const status = normalizedStatus(document);
        const recordedSha = document?.source_sha || document?.checked_in_source_sha;
        const rowCount = document?.checks_total ?? document?.required_rows;
        const passedCount = document?.checks_passed ?? document?.implemented_rows;
        return <article className={`evidence-row status-${status}`} key={item.file}>
          <div className="evidence-icon" aria-hidden="true">{status === "admitted" ? <ShieldCheck /> : status === "blocked" ? <CircleAlert /> : <FileJson />}</div>
          <div className="evidence-copy">
            <div className="evidence-title"><h2>{item.title}</h2><span>{status}</span></div>
            <p>{item.summary}</p>
            {document?.claim_boundary && <blockquote>{document.claim_boundary}</blockquote>}
          </div>
          <dl>
            <div><dt>Evidence SHA</dt><dd><code>{compactSha(recordedSha)}</code></dd></div>
            {document?.generated_at && <div><dt>Generated</dt><dd>{new Date(document.generated_at).toLocaleDateString("en-GB")}</dd></div>}
            {typeof rowCount === "number" && <div><dt>Rows</dt><dd>{passedCount ?? 0}/{rowCount}</dd></div>}
          </dl>
          <a className="evidence-open" href={`${base}data/${item.file}`} target="_blank" rel="noreferrer">JSON <ArrowUpRight size={14} /></a>
        </article>;
      })}
      {!loading && Object.keys(documents).length === 0 && <div className="evidence-error"><CircleAlert size={18} />Evidence bundle is unavailable. No claim is promoted from this page.</div>}
    </section>

    <section className="evidence-library">
      <div><span className="mi-kicker">COMPLETE ARCHIVE</span><h2>Reports, benchmark rows and machine-readable artifacts.</h2></div>
      <p>The site ships the checked-in benchmark library without rewriting failed rows. Start with the current status index, then inspect the underlying report or JSON.</p>
      <div>
        <a href={`${base}data/product-status.json`} target="_blank" rel="noreferrer">Product status <ArrowUpRight size={14} /></a>
        <a href={`${base}data/leaderboard-status.json`} target="_blank" rel="noreferrer">Leaderboard status <ArrowUpRight size={14} /></a>
        <a href={`${base}benchmarks/BENCHMARK_LEADERBOARD.md`} target="_blank" rel="noreferrer">Benchmark leaderboard <ArrowUpRight size={14} /></a>
        <a href={`${base}evidence/legacy.html`} target="_blank" rel="noreferrer">Legacy dashboard <ArrowUpRight size={14} /></a>
      </div>
    </section>

    <footer className="evidence-footer"><span><Check size={14} />No synthetic greenwashing</span><span>WaveMind evidence is versioned with the code.</span></footer>
  </main>;
}
