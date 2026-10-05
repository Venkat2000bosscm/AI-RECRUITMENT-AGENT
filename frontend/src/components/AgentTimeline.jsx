import { fmtDate } from "../util.js";

const PHASE_ICON = {
  planning: "🧭",
  tool: "🛠️",
  monitoring: "📈",
  adaptation: "🔁",
  approval: "✋",
  completion: "✅",
};

export default function AgentTimeline({ runs }) {
  if (!runs?.length) return <p className="muted">The agent has not run for this requisition yet.</p>;
  return runs.map((run) => (
    <div key={run.id} className="card run">
      <div className="run-head">
        <strong>Run #{run.id}</strong> <span className="muted small">{fmtDate(run.started_at)}</span>
        <span className="spacer" />
        <span className="small">{run.outcome}</span>
      </div>
      <ol className="timeline">
        {run.steps.map((s, i) => (
          <li key={i} className={`phase-${s.phase}`}>
            <span className="phase">
              {PHASE_ICON[s.phase]} {s.phase}
            </span>
            <code>{s.action}</code>
            <span className="detail">{s.detail}</span>
          </li>
        ))}
      </ol>
    </div>
  ));
}
