import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api.js";
import AgentTimeline from "../components/AgentTimeline.jsx";
import ApprovalCard from "../components/ApprovalCard.jsx";
import { Badge, Chips, ErrorBox, LoadError, Markdown, Score, Tabs } from "../components/ui.jsx";
import { effectiveCategory, fmtMoney } from "../util.js";
import { JobForm } from "./Jobs.jsx";

export default function JobDetail({ onChange }) {
  const { id } = useParams();
  const [job, setJob] = useState(null);
  const [candidates, setCandidates] = useState([]);
  const [approvals, setApprovals] = useState([]);
  const [runs, setRuns] = useState([]);
  const [tab, setTab] = useState("candidates");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(false);
  const [jdDraft, setJdDraft] = useState(null);
  const [paste, setPaste] = useState("");
  const [filter, setFilter] = useState("all");
  const fileRef = useRef();

  const load = async () => {
    try {
      const [jobData, candidateData, approvalData, runData] = await Promise.all([
        api.get(`/jobs/${id}`),
        api.get(`/jobs/${id}/candidates`),
        api.get(`/approvals?status=all&job_id=${id}`),
        api.get(`/jobs/${id}/agent/runs`),
      ]);
      setJob(jobData);
      setCandidates(candidateData);
      setApprovals(approvalData);
      setRuns(runData);
      setError("");
      onChange?.();
    } catch (e) {
      setError(e.message);
      throw e;
    }
  };
  useEffect(() => {
    setJob(null);
    setError("");
    load().catch(() => {});
  }, [id]);

  const act = async (label, fn) => {
    setBusy(label);
    setError("");
    try {
      await fn();
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy("");
    }
  };

  if (!job && error) return <LoadError error={`Couldn’t load this requisition: ${error}`} onRetry={() => load().catch(() => {})} />;
  if (!job) return <p role="status">Loading requisition…</p>;
  const pendingApprovals = approvals.filter((a) => a.status === "pending");
  const shown = candidates.filter((c) => filter === "all" || effectiveCategory(c) === filter || c.status === filter);

  const upload = (files) =>
    act("upload", async () => {
      const form = new FormData();
      [...files].forEach((f) => form.append("files", f));
      await api.upload(`/jobs/${id}/candidates/upload`, form);
      fileRef.current.value = "";
    });

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>{job.title}</h1>
          <div className="muted">
            {job.department} · {job.location} ({job.work_mode}) · {job.experience_min}-{job.experience_max} yrs ·{" "}
            {job.salary_max ? `${fmtMoney(job.salary_min, job.currency)} – ${fmtMoney(job.salary_max, job.currency)}` : "budget n/a"} ·{" "}
            {job.openings} opening(s) · <Badge value={job.status} />
          </div>
        </div>
        <div className="row">
          <button className="btn primary" disabled={!!busy} onClick={() => act("agent", () => api.post(`/jobs/${id}/agent/run`))}>
            {busy === "agent" ? "Agent running…" : "▶ Run agent"}
          </button>
          <button className="btn" onClick={() => act("pause", () => api.post(`/jobs/${id}/pause`, { paused: !job.agent_paused }))}>
            {job.agent_paused ? "Resume agent" : "Pause agent"}
          </button>
          {job.status !== "closed" && (
            <button className="btn danger" onClick={() => act("close", () => api.post(`/jobs/${id}/close`))}>
              Close
            </button>
          )}
        </div>
      </div>
      <ErrorBox error={error} />
      {pendingApprovals.length > 0 && (
        <div className="banner info">
          {pendingApprovals.length} pending approval(s) for this requisition —{" "}
          <a href="#" onClick={(e) => (e.preventDefault(), setTab("approvals"))}>
            review
          </a>
        </div>
      )}
      <Tabs
        active={tab}
        onChange={setTab}
        tabs={[
          { id: "candidates", label: "Candidates", count: candidates.length },
          { id: "jd", label: "Requirement & JD" },
          { id: "approvals", label: "Approvals", count: pendingApprovals.length },
          { id: "agent", label: "Agent activity", count: runs.length },
        ]}
      />

      {tab === "candidates" && (
        <div>
          <div className="card">
            <h3>Add applications</h3>
            <div className="row">
              <input ref={fileRef} type="file" multiple accept=".pdf,.docx,.txt,.md" onChange={(e) => upload(e.target.files)} />
              <span className="muted small">PDF, DOCX or TXT — parsed, redacted and screened automatically.</span>
            </div>
            <textarea rows={3} placeholder="…or paste resume text" value={paste} onChange={(e) => setPaste(e.target.value)} />
            <div className="row">
              <button
                className="btn"
                disabled={!paste.trim() || !!busy}
                onClick={() => act("paste", async () => (await api.post(`/jobs/${id}/candidates`, { resume_text: paste }), setPaste("")))}
              >
                Add & screen
              </button>
              <button className="btn" disabled={!!busy} onClick={() => act("screen", () => api.post(`/jobs/${id}/screen?rescreen=true`))}>
                Re-screen all
              </button>
              <button className="btn" disabled={!!busy} onClick={() => act("shortlist", () => api.post(`/jobs/${id}/propose-shortlist`))}>
                Propose shortlist
              </button>
            </div>
          </div>
          <div className="row filters">
            {["all", "strong_match", "partial_match", "weak_match", "human_review", "shortlisted", "rejected"].map((f) => (
              <button key={f} className={filter === f ? "chip active" : "chip"} onClick={() => setFilter(f)}>
                {f.replace(/_/g, " ")}
              </button>
            ))}
          </div>
          <div className="card">
            <table className="table">
              <thead>
                <tr>
                  <th>Candidate</th>
                  <th>Score</th>
                  <th>Signal</th>
                  <th>Conf.</th>
                  <th>Matched</th>
                  <th>Gaps</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((c) => (
                  <tr key={c.id}>
                    <td>
                      <Link to={`/candidates/${c.id}`}>{c.name || `Candidate #${c.id}`}</Link>
                      <div className="small muted">{c.source}</div>
                    </td>
                    <td>
                      <Score value={c.score} />
                    </td>
                    <td>
                      <Badge value={effectiveCategory(c)} kind="category" />
                      {c.hr_category_override && <div className="small muted">HR override</div>}
                    </td>
                    <td>{c.confidence != null ? c.confidence.toFixed(2) : "—"}</td>
                    <td>
                      <Chips items={c.matched_skills} kind="ok" />
                    </td>
                    <td>
                      <Chips items={c.missing_skills} kind="gap" />
                    </td>
                    <td>
                      <Badge value={c.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {shown.length === 0 && <p className="muted">No candidates.</p>}
          </div>
        </div>
      )}

      {tab === "jd" && (
        <div className="grid two">
          <div className="card">
            <div className="page-head">
              <h3>Approved requirement</h3>
              <button className="btn" onClick={() => setEditing(!editing)}>
                {editing ? "Cancel" : "Edit"}
              </button>
            </div>
            {editing ? (
              <JobForm
                initial={job}
                submitLabel="Save requirement"
                onSubmit={(f) => act("save", async () => (await api.patch(`/jobs/${id}`, f), setEditing(false)))}
              />
            ) : (
              <dl className="dl">
                <dt>Required skills</dt>
                <dd>
                  <Chips items={job.required_skills} />
                </dd>
                <dt>Preferred skills</dt>
                <dd>
                  <Chips items={job.preferred_skills} />
                </dd>
                <dt>Qualifications</dt>
                <dd>{job.qualifications || "—"}</dd>
                <dt>Constraints</dt>
                <dd>{job.constraints || "—"}</dd>
                <dt>Channels</dt>
                <dd>{job.channels.join(", ") || "—"}</dd>
              </dl>
            )}
          </div>
          <div className="card">
            <div className="page-head">
              <h3>Job description</h3>
              <div className="row">
                <button className="btn" disabled={!!busy} onClick={() => act("jd", () => api.post(`/jobs/${id}/generate-jd`))}>
                  {busy === "jd" ? "Generating…" : "✨ Generate with AI"}
                </button>
                <button className="btn" onClick={() => setJdDraft(jdDraft == null ? job.description : null)}>
                  {jdDraft == null ? "Edit" : "Cancel"}
                </button>
                {["draft"].includes(job.status) && (
                  <button className="btn primary" disabled={!!busy} onClick={() => act("submit", () => api.post(`/jobs/${id}/submit-jd`))}>
                    Submit for approval
                  </button>
                )}
              </div>
            </div>
            {jdDraft != null ? (
              <>
                <textarea rows={20} value={jdDraft} onChange={(e) => setJdDraft(e.target.value)} />
                <button
                  className="btn primary"
                  onClick={() => act("savejd", async () => (await api.patch(`/jobs/${id}`, { description: jdDraft }), setJdDraft(null)))}
                >
                  Save JD
                </button>
              </>
            ) : (
              <Markdown text={job.description} />
            )}
          </div>
        </div>
      )}

      {tab === "approvals" && (
        <div>
          {approvals.length === 0 && <p className="muted">No approvals yet.</p>}
          {approvals.map((a) => (
            <ApprovalCard key={a.id} approval={a} onDone={load} />
          ))}
        </div>
      )}

      {tab === "agent" && (
        <div>
          <p className="muted small">
            Each run: Planning → Reasoning → Tool usage → Execution → Monitoring → Adaptation → Human approval checkpoint. The agent stops whenever
            an HR decision is required and resumes automatically after it.
          </p>
          <AgentTimeline runs={runs} />
        </div>
      )}
    </div>
  );
}
