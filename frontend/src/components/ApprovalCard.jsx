import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { APPROVAL_LABEL, CATEGORY_LABEL, fmtDate, fmtMoney } from "../util.js";
import { Badge, ErrorBox } from "./ui.jsx";

function Overrides({ approval, overrides, setOverrides }) {
  const p = approval.payload;
  if (approval.type === "shortlist") {
    const selected = overrides.candidate_ids ?? p.candidate_ids;
    const toggle = (id) =>
      setOverrides({
        ...overrides,
        candidate_ids: selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id],
      });
    return (
      <div>
        <table className="table compact">
          <thead>
            <tr>
              <th />
              <th>Candidate</th>
              <th>Score</th>
              <th>Signal</th>
              <th>Gaps</th>
            </tr>
          </thead>
          <tbody>
            {p.candidates.map((c) => (
              <tr key={c.id}>
                <td>
                  <input type="checkbox" checked={selected.includes(c.id)} onChange={() => toggle(c.id)} />
                </td>
                <td>
                  <Link to={`/candidates/${c.id}`}>{c.name || `#${c.id}`}</Link>
                </td>
                <td>{Math.round((c.score || 0) * 100)}</td>
                <td>
                  <Badge value={c.category} kind="category" />
                </td>
                <td className="small">{c.missing_skills.join(", ") || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <label className="inline">
          <input
            type="checkbox"
            checked={!!overrides.reject_others}
            onChange={(e) => setOverrides({ ...overrides, reject_others: e.target.checked })}
          />
          Send rejection emails to unselected candidates
        </label>
      </div>
    );
  }
  if (approval.type === "offer") {
    return (
      <div className="row">
        <label>
          Salary ({p.currency})
          <input
            type="number"
            value={overrides.salary ?? p.salary}
            onChange={(e) => setOverrides({ ...overrides, salary: Number(e.target.value) })}
          />
        </label>
        <label>
          Start date
          <input
            type="date"
            value={overrides.start_date ?? p.start_date}
            onChange={(e) => setOverrides({ ...overrides, start_date: e.target.value })}
          />
        </label>
        {p.warnings?.length > 0 && <div className="warn">{p.warnings.join("; ")}</div>}
      </div>
    );
  }
  if (approval.type === "interview_schedule") {
    const slots = [p.start_time, ...(p.alternative_slots || [])];
    return (
      <label>
        Slot with {p.interviewer}
        <select
          value={overrides.start_time ?? p.start_time}
          onChange={(e) => setOverrides({ ...overrides, start_time: e.target.value })}
        >
          {slots.map((s) => (
            <option key={s} value={s}>
              {fmtDate(s)}
            </option>
          ))}
        </select>
      </label>
    );
  }
  if (approval.type === "human_review") {
    return (
      <div>
        <p className="small">
          Suggested: <Badge value={p.suggested_category} kind="category" /> · Flags: {p.flags.join("; ")}
        </p>
        <label>
          Set category
          <select
            value={overrides.category ?? p.suggested_category}
            onChange={(e) => setOverrides({ ...overrides, category: e.target.value })}
          >
            {["strong_match", "partial_match", "weak_match"].map((c) => (
              <option key={c} value={c}>
                {CATEGORY_LABEL[c]}
              </option>
            ))}
          </select>
        </label>
      </div>
    );
  }
  if (approval.type === "jd_publication") {
    return <p className="small">Channels: {(p.channels || []).join(", ")}</p>;
  }
  if (approval.type === "strategy_change") {
    return (
      <ul className="small">
        {p.actions.map((a, i) => (
          <li key={i}>
            <strong>{a.type.replace(/_/g, " ")}</strong>{" "}
            {a.channels?.join(", ") || a.move_to_preferred?.join(", ") || a.experience_min || a.detail}
          </li>
        ))}
      </ul>
    );
  }
  if (approval.type === "hiring_decision") {
    return (
      <p className="small">
        Avg rating: <strong>{p.average_rating ?? "—"}</strong> · Recommendations: {p.recommendations.join(", ")}
        <br />
        {p.feedback_summary}
      </p>
    );
  }
  if (approval.type === "onboarding") {
    return (
      <ul className="small">
        {p.tasks.map((t) => (
          <li key={t.title}>
            {t.title} <span className="muted">({t.owner})</span>
          </li>
        ))}
      </ul>
    );
  }
  return null;
}

export default function ApprovalCard({ approval, onDone }) {
  const [overrides, setOverrides] = useState({});
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pending = approval.status === "pending";
  const approveLabel = approval.type === "hiring_decision" ? "Select candidate" : "Approve";
  const rejectLabel = approval.type === "hiring_decision" ? "Do not hire" : "Reject";

  const decide = async (approved) => {
    setBusy(true);
    setError("");
    try {
      await api.post(`/approvals/${approval.id}/decide`, { approved, comment, overrides });
      onDone?.();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={`card approval ${pending ? "" : "decided"}`}>
      <div className="approval-head">
        <span className={`badge t-${approval.type}`}>{APPROVAL_LABEL[approval.type]}</span>
        <strong>{approval.title}</strong>
        <span className="spacer" />
        <Badge value={approval.status} />
      </div>
      <p className="rationale">{approval.rationale}</p>
      <Overrides approval={approval} overrides={overrides} setOverrides={setOverrides} />
      <div className="meta small muted">
        Requested by {approval.requested_by} · {fmtDate(approval.created_at)}
        {approval.job_id && (
          <>
            {" "}
            · <Link to={`/jobs/${approval.job_id}`}>job #{approval.job_id}</Link>
          </>
        )}
        {approval.candidate_id && (
          <>
            {" "}
            · <Link to={`/candidates/${approval.candidate_id}`}>candidate #{approval.candidate_id}</Link>
          </>
        )}
        {!pending && (
          <>
            {" "}
            · decided by {approval.decided_by} {approval.decision_comment && `— "${approval.decision_comment}"`}
          </>
        )}
      </div>
      <ErrorBox error={error} />
      {pending && (
        <div className="row actions">
          <input placeholder="Comment (optional)" value={comment} onChange={(e) => setComment(e.target.value)} />
          <button className="btn primary" disabled={busy} onClick={() => decide(true)}>
            {approveLabel}
          </button>
          <button className="btn danger" disabled={busy} onClick={() => decide(false)}>
            {rejectLabel}
          </button>
        </div>
      )}
      {approval.type === "offer" && approval.payload.salary != null && !pending && (
        <div className="small muted">Salary: {fmtMoney(approval.payload.hr_overrides?.salary ?? approval.payload.salary)}</div>
      )}
    </div>
  );
}
