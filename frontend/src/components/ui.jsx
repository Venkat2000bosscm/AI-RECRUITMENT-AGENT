import { CATEGORY_LABEL, pretty } from "../util.js";

export function Badge({ value, kind }) {
  if (!value) return <span className="badge muted">—</span>;
  const label = kind === "category" ? CATEGORY_LABEL[value] || pretty(value) : pretty(value);
  return <span className={`badge b-${value}`}>{label}</span>;
}

export function Score({ value }) {
  if (value == null) return <span className="muted">—</span>;
  const pct = Math.round(value * 100);
  return (
    <div className="score">
      <div className="score-bar">
        <div style={{ width: `${pct}%` }} className={pct >= 75 ? "hi" : pct >= 50 ? "mid" : "lo"} />
      </div>
      <span>{pct}</span>
    </div>
  );
}

export function Stat({ label, value, hint }) {
  return (
    <div className="stat card">
      <div className="stat-value">{value ?? "—"}</div>
      <div className="stat-label">{label}</div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  );
}

export function Tabs({ tabs, active, onChange }) {
  return (
    <div className="tabs">
      {tabs.map((t) => (
        <button key={t.id} className={active === t.id ? "tab active" : "tab"} onClick={() => onChange(t.id)}>
          {t.label}
          {t.count != null && <span className="tab-count">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function ErrorBox({ error }) {
  return error ? <div className="error">{error}</div> : null;
}

export function Chips({ items, kind = "" }) {
  if (!items?.length) return <span className="muted">none</span>;
  return (
    <div className="chips">
      {items.map((i) => (
        <span key={i} className={`chip ${kind}`}>
          {i}
        </span>
      ))}
    </div>
  );
}

export function Markdown({ text }) {
  if (!text) return <p className="muted">No content yet.</p>;
  const lines = text.split("\n");
  const out = [];
  let list = [];
  const flush = () => {
    if (list.length) out.push(<ul key={`ul${out.length}`}>{list}</ul>);
    list = [];
  };
  const inline = (s) =>
    s.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
      part.startsWith("**") ? <strong key={i}>{part.slice(2, -2)}</strong> : part
    );
  lines.forEach((line, i) => {
    if (/^\s*[-*]\s+/.test(line)) list.push(<li key={i}>{inline(line.replace(/^\s*[-*]\s+/, ""))}</li>);
    else {
      flush();
      if (line.startsWith("### ")) out.push(<h4 key={i}>{inline(line.slice(4))}</h4>);
      else if (line.startsWith("## ")) out.push(<h3 key={i}>{inline(line.slice(3))}</h3>);
      else if (line.startsWith("# ")) out.push(<h2 key={i}>{inline(line.slice(2))}</h2>);
      else if (line.trim()) out.push(<p key={i}>{inline(line)}</p>);
    }
  });
  flush();
  return <div className="markdown">{out}</div>;
}
