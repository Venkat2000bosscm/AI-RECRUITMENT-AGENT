import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api.js";
import ApprovalCard from "../components/ApprovalCard.jsx";
import { Badge, Chips, ErrorBox, LoadError, Score } from "../components/ui.jsx";
import { CATEGORY_LABEL, effectiveCategory, fmtDate, fmtMoney, pretty } from "../util.js";

function FeedbackForm({ interview, onDone }) {
  const [f, setF] = useState({ rating: 4, recommendation: "hire", strengths: "", concerns: "", notes: "" });
  const [error, setError] = useState("");
  const set = (k) => (e) => setF({ ...f, [k]: k === "rating" ? Number(e.target.value) : e.target.value });
  const submit = async (e) => {
    e.preventDefault();
    try {
      await api.post(`/interviews/${interview.id}/feedback`, f);
      onDone();
    } catch (err) {
      setError(err.message);
    }
  };
  return (
    <form className="form" onSubmit={submit}>
      <div className="row">
        <label>
          Rating
          <select value={f.rating} onChange={set("rating")}>
            {[1, 2, 3, 4, 5].map((n) => (
              <option key={n}>{n}</option>
            ))}
          </select>
        </label>
        <label>
          Recommendation
          <select value={f.recommendation} onChange={set("recommendation")}>
            {["strong_hire", "hire", "no_hire", "strong_no_hire"].map((r) => (
              <option key={r} value={r}>
                {pretty(r)}
              </option>
            ))}
          </select>
        </label>
      </div>
      <label>
        Strengths
        <input value={f.strengths} onChange={set("strengths")} />
      </label>
      <label>
        Concerns
        <input value={f.concerns} onChange={set("concerns")} />
      </label>
      <label>
        Notes
        <textarea rows={3} value={f.notes} onChange={set("notes")} placeholder="Additional observations or context" />
      </label>
      <ErrorBox error={error} />
      <button className="btn primary">Submit feedback</button>
    </form>
  );
}

export default function CandidateDetail({ onChange }) {
  const { id } = useParams();
  const [c, setC] = useState(null);
  const [interviews, setInterviews] = useState([]);
  const [approvals, setApprovals] = useState([]);
  const [offers, setOffers] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [emails, setEmails] = useState([]);
  const [interviewers, setInterviewers] = useState([]);
  const [override, setOverride] = useState({ category: "", note: "" });
  const [offerForm, setOfferForm] = useState({ salary: "", start_date: "" });
  const [error, setError] = useState("");
  const [showResume, setShowResume] = useState(false);

  const load = async () => {
    try {
      const [candidate, interviewData, approvalData, offerData, onboardingData, emailData, interviewerData] = await Promise.all([
        api.get(`/candidates/${id}`),
        api.get(`/candidates/${id}/interviews`),
        api.get(`/approvals?status=all&candidate_id=${id}`),
        api.get(`/offers?candidate_id=${id}`),
        api.get(`/candidates/${id}/onboarding`),
        api.get(`/emails?candidate_id=${id}`),
        api.get("/interviewers"),
      ]);
      setC(candidate);
      setInterviews(interviewData);
      setApprovals(approvalData);
      setOffers(offerData);
      setTasks(onboardingData);
      setEmails(emailData);
      setInterviewers(interviewerData);
      setError("");
      onChange?.();
    } catch (e) {
      setError(e.message);
      throw e;
    }
  };
  useEffect(() => {
    setC(null);
    setError("");
    load().catch(() => {});
  }, [id]);

  const act = async (fn) => {
    setError("");
    try {
      await fn();
      await load();
    } catch (e) {
      setError(e.message);
    }
  };

  if (!c && error) return <LoadError error={`Couldn’t load this candidate: ${error}`} onRetry={() => load().catch(() => {})} />;
  if (!c) return <p role="status">Loading candidate…</p>;
  const b = c.score_breakdown || {};

  return (
    <div>
      <Link to={`/jobs/${c.job_id}`} className="small">
        ← Back to requisition
      </Link>
      <div className="page-head">
        <div>
          <h1>{c.name || `Candidate #${c.id}`}</h1>
          <div className="muted">
            {c.email} · {c.phone} · {c.location || "location n/a"} · source: {c.source}
          </div>
        </div>
        <div className="row">
          <Badge value={effectiveCategory(c)} kind="category" />
          <Badge value={c.status} />
        </div>
      </div>
      <ErrorBox error={error} />
      <div className="grid two">
        <div className="card">
          <h3>AI screening summary</h3>
          <p>{c.summary || "Not screened yet."}</p>
          <div className="grid three small">
            <div>
              <div className="muted">Overall score</div>
              <Score value={c.score} />
            </div>
            <div>
              <div className="muted">Confidence</div>
              {c.confidence?.toFixed(2) ?? "—"}
            </div>
            <div>
              <div className="muted">Experience</div>
              {c.parsed?.years_experience ?? "?"} yrs
            </div>
          </div>
          <h4>Score breakdown</h4>
          <p className="small muted">Each factor is a normalized match score; the weight shows how much that factor contributes to the screening score. These are review signals, not a hiring decision.</p>
          {["required_skills", "preferred_skills", "experience", "similarity"].map(
            (k) =>
              b[k] != null && (
                <div key={k} className="bar-row">
                  <span className="bar-label">
                    {pretty(k)} <span className="muted">{b.weights?.[k] != null ? `×${b.weights[k]} weight` : ""}</span>
                  </span>
                  <div className="bar">
                    <div
                      className="fill c-pipeline"
                      role="img"
                      aria-label={`${pretty(k)} match strength: ${Math.round(b[k] * 100)}%`}
                      style={{ width: `${Math.min(100, Math.max(0, b[k] * 100))}%` }}
                    />
                  </div>
                  <span className="bar-val">{Math.round(b[k] * 100)}%</span>
                </div>
              )
          )}
          <h4>Matching skills</h4>
          <Chips items={c.matched_skills} kind="ok" />
          <h4>Gaps vs. required</h4>
          <Chips items={c.missing_skills} kind="gap" />
          <h4>Review flags</h4>
          {c.flags.length ? (
            <ul className="small">
              {c.flags.map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
          ) : (
            <span className="muted">none</span>
          )}
          <h4>Extracted profile</h4>
          <div className="small">
            Education: {c.parsed?.education?.join(", ") || "—"} · All skills: {c.parsed?.skills?.join(", ") || "—"}
          </div>
          <button className="btn small-btn" onClick={() => setShowResume(!showResume)}>
            {showResume ? "Hide" : "Show"} resume (redacted for scoring)
          </button>
          {showResume && <pre className="resume">{c.resume_text}</pre>}
        </div>

        <div>
          <div className="card">
            <h3>HR controls</h3>
            <p className="small muted">AI signals are recommendations. Override them at any time — every change is audit-logged.</p>
            <div className="row">
              <select value={override.category} onChange={(e) => setOverride({ ...override, category: e.target.value })}>
                <option value="">Category…</option>
                {Object.entries(CATEGORY_LABEL).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
              <input placeholder="Reason / note" value={override.note} onChange={(e) => setOverride({ ...override, note: e.target.value })} />
              <button
                className="btn"
                disabled={!override.category}
                onClick={() => act(() => api.post(`/candidates/${id}/override`, { category: override.category, note: override.note }))}
              >
                Override
              </button>
            </div>
            <div className="row">
              {c.status === "screened" && (
                <button className="btn primary" onClick={() => act(() => api.post(`/candidates/${id}/override`, { status: "shortlisted", note: "Manual shortlist" }))}>
                  Shortlist manually
                </button>
              )}
              {!["rejected", "hired", "declined"].includes(c.status) && (
                <button className="btn danger" onClick={() => act(() => api.post(`/candidates/${id}/override`, { status: "rejected", note: "Rejected by HR" }))}>
                  Reject
                </button>
              )}
              <button className="btn" onClick={() => act(() => api.post(`/candidates/${id}/rescreen`))}>
                Re-screen
              </button>
            </div>
            {c.hr_note && <p className="small">HR note: {c.hr_note}</p>}
          </div>

          <div className="card">
            <h3>Interviews</h3>
            {["shortlisted", "interview_scheduled", "interviewed"].includes(c.status) && (
              <div className="row">
                <select id="iv">
                  <option value="">Auto-match interviewer</option>
                  {interviewers.map((i) => (
                    <option key={i.id} value={i.id}>
                      {i.name} ({i.expertise.join(", ")})
                    </option>
                  ))}
                </select>
                <button
                  className="btn"
                  onClick={() =>
                    act(() =>
                      api.post(`/candidates/${id}/interviews`, {
                        interviewer_id: Number(document.getElementById("iv").value) || null,
                        round_name: interviews.length ? "Round " + (interviews.length + 1) : "Technical",
                      })
                    )
                  }
                >
                  Propose interview
                </button>
              </div>
            )}
            {interviews.length === 0 && <p className="muted">No interviews yet.</p>}
            {interviews.map((iv) => (
              <div key={iv.id} className="subcard">
                <div className="row">
                  <strong>{iv.round_name}</strong> with {iv.interviewer_name} · {fmtDate(iv.start_time)} <Badge value={iv.status} />
                </div>
                <details>
                  <summary>Interview kit ({iv.questions.length} questions)</summary>
                  <ol className="small">
                    {iv.questions.map((q, i) => (
                      <li key={i}>
                        <span className="muted">[{q.category}]</span> {q.question}
                      </li>
                    ))}
                  </ol>
                  <strong className="small">Checklist</strong>
                  <ul className="small">
                    {iv.checklist.map((x) => (
                      <li key={x}>{x}</li>
                    ))}
                  </ul>
                </details>
                {iv.feedback_summary && <p className="small"><strong>Feedback summary:</strong> {iv.feedback_summary}</p>}
                {iv.status === "scheduled" && <FeedbackForm interview={iv} onDone={load} />}
              </div>
            ))}
          </div>

          <div className="card">
            <h3>Offer</h3>
            {c.status === "selected" && offers.every((o) => ["rejected"].includes(o.status)) && (
              <div className="row">
                <input type="number" placeholder="Salary (blank = midpoint)" value={offerForm.salary} onChange={(e) => setOfferForm({ ...offerForm, salary: e.target.value })} />
                <input type="date" value={offerForm.start_date} onChange={(e) => setOfferForm({ ...offerForm, start_date: e.target.value })} />
                <button
                  className="btn primary"
                  onClick={() => act(() => api.post(`/candidates/${id}/offer`, { salary: offerForm.salary ? Number(offerForm.salary) : null, start_date: offerForm.start_date }))}
                >
                  Draft offer
                </button>
              </div>
            )}
            {offers.length === 0 && <p className="muted">No offer yet. Offers can be drafted after the hiring decision-maker selects the candidate.</p>}
            {offers.map((o) => (
              <div key={o.id} className="subcard">
                <div className="row">
                  {fmtMoney(o.salary, o.currency)} · start {o.start_date} <Badge value={o.status} />
                </div>
                <details>
                  <summary>Offer letter</summary>
                  <pre className="resume">{o.content}</pre>
                </details>
                {o.status === "sent" && (
                  <div className="row">
                    <button className="btn primary" onClick={() => act(() => api.post(`/offers/${o.id}/response`, { accepted: true }))}>
                      Record acceptance
                    </button>
                    <button className="btn danger" onClick={() => act(() => api.post(`/offers/${o.id}/response`, { accepted: false }))}>
                      Record decline
                    </button>
                  </div>
                )}
              </div>
            ))}
            {tasks.length > 0 && (
              <>
                <h4>Onboarding tasks</h4>
                <table className="table compact">
                  <tbody>
                    {tasks.map((t) => (
                      <tr key={t.id}>
                        <td>{t.title}</td>
                        <td className="muted">{t.owner}</td>
                        <td>
                          <select value={t.status} onChange={(e) => act(() => api.patch(`/onboarding/${t.id}`, { status: e.target.value }))}>
                            <option value="pending">pending</option>
                            <option value="in_progress">in progress</option>
                            <option value="done">done</option>
                          </select>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>
        </div>
      </div>

      <h2>Approvals</h2>
      {approvals.length === 0 && <p className="muted">None.</p>}
      {approvals.map((a) => (
        <ApprovalCard key={a.id} approval={a} onDone={load} />
      ))}
      <h2>Communications</h2>
      <div className="card">
        {emails.length === 0 && <p className="muted">No emails sent.</p>}
        {emails.map((e) => (
          <details key={e.id}>
            <summary>
              {fmtDate(e.created_at)} · <strong>{e.subject}</strong> <Badge value={e.status} />
            </summary>
            <pre className="resume">{e.body}</pre>
          </details>
        ))}
      </div>
    </div>
  );
}
