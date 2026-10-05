import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import ApprovalCard from "../components/ApprovalCard.jsx";
import { Badge, Stat } from "../components/ui.jsx";
import { CATEGORY_LABEL, pretty } from "../util.js";

const FUNNEL = ["applied", "screened", "shortlisted", "interview_scheduled", "interviewed", "selected", "offered", "hired"];

export default function Dashboard() {
  const [s, setS] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [approvals, setApprovals] = useState([]);

  const load = () => {
    api.get("/analytics/summary").then(setS);
    api.get("/jobs").then(setJobs);
    api.get("/approvals?status=pending").then(setApprovals);
  };
  useEffect(load, []);
  if (!s) return <p>Loading…</p>;

  const screened = s.candidates.screened || 1;
  const maxFunnel = Math.max(1, ...FUNNEL.map((k) => s.pipeline[k] || 0));

  return (
    <div>
      <h1>Recruitment Dashboard</h1>
      <div className="grid stats">
        <Stat label="Open requisitions" value={s.jobs.published} hint={`${s.jobs.draft} draft`} />
        <Stat label="Candidates screened" value={`${s.candidates.screened}/${s.candidates.total}`} />
        <Stat label="Pending HR approvals" value={s.approvals.pending} />
        <Stat label="Human-review rate" value={`${s.human_review_pct}%`} hint={`HR overrides: ${s.hr_override_pct}%`} />
        <Stat label="Interviews scheduled" value={s.interviews.scheduled} hint={`${s.interviews.completed} completed`} />
        <Stat label="Offers accepted" value={s.offers.accepted} hint={`${s.offers.sent} awaiting response`} />
        <Stat label="Avg hours to shortlist" value={s.avg_hours_to_shortlist ?? "—"} />
        <Stat
          label="AI calls (LLM / template)"
          value={`${s.ai_usage.llm_calls} / ${s.ai_usage.template_calls}`}
          hint={`est. LLM cost $${s.ai_usage.estimated_llm_cost_usd}`}
        />
      </div>

      <div className="grid two">
        <div className="card">
          <h3>Screening signals</h3>
          {Object.entries(s.categories).map(([k, v]) => (
            <div key={k} className="bar-row">
              <span className="bar-label">{CATEGORY_LABEL[k]}</span>
              <div className="bar">
                <div className={`fill c-${k}`} style={{ width: `${(100 * v) / screened}%` }} />
              </div>
              <span className="bar-val">{v}</span>
            </div>
          ))}
          <p className="small muted">Signals support HR review — they are not automatic employment decisions.</p>
        </div>
        <div className="card">
          <h3>Pipeline</h3>
          {FUNNEL.map((k) => (
            <div key={k} className="bar-row">
              <span className="bar-label">{pretty(k)}</span>
              <div className="bar">
                <div className="fill c-pipeline" style={{ width: `${(100 * (s.pipeline[k] || 0)) / maxFunnel}%` }} />
              </div>
              <span className="bar-val">{s.pipeline[k] || 0}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="grid two">
        <div>
          <h2>Requisitions</h2>
          <div className="card">
            <table className="table">
              <thead>
                <tr>
                  <th>Role</th>
                  <th>Status</th>
                  <th>Candidates</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((j) => (
                  <tr key={j.id}>
                    <td>
                      <Link to={`/jobs/${j.id}`}>{j.title}</Link>
                      <div className="small muted">{j.location}</div>
                    </td>
                    <td>
                      <Badge value={j.status} />
                    </td>
                    <td>{j.candidate_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <div>
          <h2>Needs your decision</h2>
          {approvals.length === 0 && <p className="muted">Nothing pending.</p>}
          {approvals.slice(0, 3).map((a) => (
            <ApprovalCard key={a.id} approval={a} onDone={load} />
          ))}
          {approvals.length > 3 && <Link to="/approvals">View all {approvals.length} approvals →</Link>}
        </div>
      </div>
    </div>
  );
}
