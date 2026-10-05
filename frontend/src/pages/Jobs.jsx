import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api.js";
import { Badge, ErrorBox } from "../components/ui.jsx";
import { fmtMoney } from "../util.js";

const EMPTY = {
  title: "",
  department: "",
  location: "",
  work_mode: "hybrid",
  experience_min: 0,
  experience_max: 0,
  required_skills: [],
  preferred_skills: [],
  qualifications: "",
  salary_min: 0,
  salary_max: 0,
  currency: "INR",
  openings: 1,
  constraints: "",
};

export function JobForm({ initial, onSubmit, submitLabel }) {
  const [f, setF] = useState({ ...EMPTY, ...initial });
  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === "number" ? Number(e.target.value) : e.target.value });
  const setList = (k) => (e) => setF({ ...f, [k]: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) });
  useEffect(() => setF({ ...EMPTY, ...initial }), [initial]);
  return (
    <form
      className="form"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(f);
      }}
    >
      <div className="row">
        <label className="grow">
          Job title*
          <input required value={f.title} onChange={set("title")} />
        </label>
        <label>
          Department
          <input value={f.department} onChange={set("department")} />
        </label>
      </div>
      <div className="row">
        <label>
          Location
          <input value={f.location} onChange={set("location")} />
        </label>
        <label>
          Work mode
          <select value={f.work_mode} onChange={set("work_mode")}>
            <option>remote</option>
            <option>hybrid</option>
            <option>onsite</option>
          </select>
        </label>
        <label>
          Min exp (yrs)
          <input type="number" value={f.experience_min} onChange={set("experience_min")} />
        </label>
        <label>
          Max exp (yrs)
          <input type="number" value={f.experience_max} onChange={set("experience_max")} />
        </label>
        <label>
          Openings
          <input type="number" value={f.openings} onChange={set("openings")} />
        </label>
      </div>
      <label>
        Required skills (comma separated)
        <input defaultValue={f.required_skills.join(", ")} key={`r${f.required_skills.join()}`} onBlur={setList("required_skills")} />
      </label>
      <label>
        Preferred skills (comma separated)
        <input defaultValue={f.preferred_skills.join(", ")} key={`p${f.preferred_skills.join()}`} onBlur={setList("preferred_skills")} />
      </label>
      <label>
        Qualifications
        <input value={f.qualifications} onChange={set("qualifications")} />
      </label>
      <div className="row">
        <label>
          Salary min
          <input type="number" value={f.salary_min} onChange={set("salary_min")} />
        </label>
        <label>
          Salary max
          <input type="number" value={f.salary_max} onChange={set("salary_max")} />
        </label>
        <label>
          Currency
          <input value={f.currency} onChange={set("currency")} />
        </label>
      </div>
      <label>
        Constraints (job-related only)
        <textarea rows={2} value={f.constraints} onChange={set("constraints")} />
      </label>
      <button className="btn primary">{submitLabel}</button>
    </form>
  );
}

export default function Jobs() {
  const [jobs, setJobs] = useState([]);
  const [showNew, setShowNew] = useState(false);
  const [intakeText, setIntakeText] = useState("");
  const [draft, setDraft] = useState({});
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const nav = useNavigate();

  useEffect(() => {
    api.get("/jobs").then(setJobs);
  }, []);

  const runIntake = async () => {
    setError("");
    try {
      const r = await api.post("/jobs/intake", { text: intakeText });
      setDraft(r.requirement);
      setNote(
        `Structured by ${r.source === "llm" ? "LLM" : "offline parser"}. Review and edit before creating.` +
          (r.protected_terms.length ? ` Ignored protected-attribute terms: ${r.protected_terms.join(", ")}.` : "")
      );
    } catch (e) {
      setError(e.message);
    }
  };

  const create = async (f) => {
    setError("");
    try {
      const job = await api.post("/jobs", f);
      nav(`/jobs/${job.id}`);
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <div>
      <div className="page-head">
        <h1>Requisitions</h1>
        <button className="btn primary" onClick={() => setShowNew(!showNew)}>
          {showNew ? "Cancel" : "+ New hiring requirement"}
        </button>
      </div>
      {showNew && (
        <div className="card">
          <h3>1. Describe the hiring goal</h3>
          <textarea
            rows={3}
            placeholder="e.g. We need to hire 2 senior Python backend engineers in Bengaluru, hybrid, 5-8 years, FastAPI, PostgreSQL, AWS, Docker; Kubernetes nice to have. Budget 25-40 LPA."
            value={intakeText}
            onChange={(e) => setIntakeText(e.target.value)}
          />
          <button className="btn" disabled={!intakeText.trim()} onClick={runIntake}>
            Convert to structured requirement
          </button>
          {note && <p className="small muted">{note}</p>}
          <h3>2. Confirm the requirement</h3>
          <ErrorBox error={error} />
          <JobForm initial={draft} onSubmit={create} submitLabel="Create requisition" />
        </div>
      )}
      <div className="card">
        <table className="table">
          <thead>
            <tr>
              <th>Role</th>
              <th>Location</th>
              <th>Experience</th>
              <th>Budget</th>
              <th>Status</th>
              <th>Pipeline</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((j) => (
              <tr key={j.id}>
                <td>
                  <Link to={`/jobs/${j.id}`}>{j.title}</Link>
                  <div className="small muted">{j.department}</div>
                </td>
                <td>
                  {j.location} <span className="muted small">({j.work_mode})</span>
                </td>
                <td>
                  {j.experience_min}-{j.experience_max} yrs
                </td>
                <td className="small">{j.salary_max ? `${fmtMoney(j.salary_min, j.currency)} – ${fmtMoney(j.salary_max, j.currency)}` : "—"}</td>
                <td>
                  <Badge value={j.status} />
                  {j.agent_paused && <span className="badge b-rejected">agent paused</span>}
                </td>
                <td className="small">
                  {Object.entries(j.pipeline)
                    .map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`)
                    .join(" · ") || "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
