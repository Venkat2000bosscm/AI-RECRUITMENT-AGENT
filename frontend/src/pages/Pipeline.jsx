import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { Badge, Score } from "../components/ui.jsx";
import { CATEGORY_LABEL, pretty } from "../util.js";

const PAGE_SIZE = 24;

export default function Pipeline() {
  const [stages, setStages] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [searchText, setSearchText] = useState("");
  const [jobId, setJobId] = useState("");
  const [status, setStatus] = useState("");
  const [category, setCategory] = useState("");
  const [location, setLocation] = useState("");
  const [locationText, setLocationText] = useState("");
  const [loading, setLoading] = useState(true);
  const [searchError, setSearchError] = useState("");
  const [metaError, setMetaError] = useState("");
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let active = true;
    Promise.all([api.get("/pipeline/stages"), api.get("/jobs")])
      .then(([pipeline, requisitions]) => {
        if (!active) return;
        setStages(pipeline.stages || []);
        setJobs(requisitions);
        setMetaError("");
      })
      .catch((error) => active && setMetaError(error.message));
    return () => {
      active = false;
    };
  }, [retry]);

  useEffect(() => {
    const timer = setTimeout(() => {
      setQ(searchText.trim());
      setLocation(locationText.trim());
      setPage(1);
    }, 250);
    return () => clearTimeout(timer);
  }, [searchText, locationText]);

  useEffect(() => {
    let active = true;
    const params = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) });
    if (q.trim()) params.set("q", q.trim());
    if (jobId) params.set("job_id", jobId);
    if (status) params.set("status", status);
    if (category) params.set("category", category);
    if (location.trim()) params.set("location", location.trim());
    setLoading(true);
    api.get(`/candidates/search?${params}`)
      .then((response) => {
        if (!active) return;
        setItems(response.items || []);
        setTotal(response.total || 0);
        setPage(response.page || page);
        setSearchError("");
      })
      .catch((error) => active && setSearchError(error.message))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [q, jobId, status, category, location, page, retry]);

  const grouped = useMemo(() => {
    const groups = new Map(stages.map((stage) => [stage.key, []]));
    const other = [];
    items.forEach((candidate) => {
      if (groups.has(candidate.status)) groups.get(candidate.status).push(candidate);
      else other.push(candidate);
    });
    return [...stages.map((stage) => ({ ...stage, candidates: groups.get(stage.key) || [] })),
      ...(other.length ? [{ key: "other", label: "Other statuses", candidates: other }] : [])];
  }, [stages, items]);

  const jobName = (candidate) =>
    candidate.job_title || jobs.find((job) => String(job.id) === String(candidate.job_id))?.title || `Requisition #${candidate.job_id}`;
  const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const changeFilter = (setter) => (event) => {
    setter(event.target.value);
    setPage(1);
  };
  const retryLoad = () => setRetry((value) => value + 1);

  return (
    <section>
      <div className="page-head pipeline-head">
        <div>
          <h1>Candidate pipeline</h1>
          <p className="muted">Search, review and track candidates through each hiring stage.</p>
        </div>
        <Link className="btn" to="/jobs">View requisitions</Link>
      </div>
      {metaError && <div className="error" role="alert">Couldn’t load pipeline stages or requisitions: {metaError} <button className="btn small-btn" onClick={retryLoad}>Retry</button></div>}
      <div className="card pipeline-filters" aria-label="Candidate search filters">
        <label className="pipeline-search">
          Search candidates
          <input type="search" value={searchText} onChange={(event) => setSearchText(event.target.value)} placeholder="Name, skills, or resume keywords" />
        </label>
        <label>
          Requisition
          <select value={jobId} onChange={changeFilter(setJobId)}>
            <option value="">All requisitions</option>
            {jobs.map((job) => <option key={job.id} value={job.id}>{job.title}</option>)}
          </select>
        </label>
        <label>
          Status
          <select value={status} onChange={changeFilter(setStatus)}>
            <option value="">All statuses</option>
            {stages.map((stage) => <option key={stage.key} value={stage.key}>{stage.label}</option>)}
          </select>
        </label>
        <label>
          Category
          <select value={category} onChange={changeFilter(setCategory)}>
            <option value="">All categories</option>
            {Object.entries(CATEGORY_LABEL).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
          </select>
        </label>
        <label>
          Location
          <input value={locationText} onChange={(event) => setLocationText(event.target.value)} placeholder="Any location" />
        </label>
      </div>
      <div className="pipeline-summary" aria-live="polite">
        <span>{loading ? "Updating candidates…" : `${total} candidate${total === 1 ? "" : "s"} found`}</span>
        {!loading && total > 0 && <span className="muted">Showing page {page} of {lastPage}</span>}
      </div>
      {searchError && <div className="error" role="alert">Couldn’t load candidates: {searchError} <button className="btn small-btn" onClick={retryLoad}>Retry</button></div>}
      {!searchError && loading && <p className="muted" role="status">Loading pipeline…</p>}
      {!searchError && !loading && (
        <div className="pipeline-board" aria-label="Candidates grouped by pipeline stage">
          {stages.length === 0 && <div className="card muted">No pipeline stages are configured yet. Candidate results are still available in the search response.</div>}
          {grouped.map((stage) => (
            <section className="pipeline-column" key={stage.key} aria-labelledby={`stage-${stage.key}`}>
              <header className="pipeline-column-head" style={stage.color ? { "--stage-color": stage.color } : undefined}>
                <h2 id={`stage-${stage.key}`}>{stage.label}</h2>
                <span className="pipeline-count">{stage.candidates.length}</span>
              </header>
              <div className="pipeline-cards">
                {stage.candidates.map((candidate) => (
                  <article className="candidate-card" key={candidate.id}>
                    <div className="candidate-card-title">
                      <Link to={`/candidates/${candidate.id}`}>{candidate.name || `Candidate #${candidate.id}`}</Link>
                      <Score value={candidate.score} />
                    </div>
                    <div className="small muted">{jobName(candidate)}</div>
                    <div className="candidate-card-meta">
                      <Badge value={candidate.hr_category_override || candidate.category} kind="category" />
                      <span className="small muted">{candidate.location || "Location not specified"}</span>
                    </div>
                    {candidate.status && <span className="small muted">{pretty(candidate.status)}</span>}
                  </article>
                ))}
                {stage.candidates.length === 0 && <p className="pipeline-empty">No candidates in this stage on this page.</p>}
              </div>
            </section>
          ))}
          {stages.length === 0 && <p className="muted">No pipeline stages are configured.</p>}
        </div>
      )}
      {!loading && !searchError && total === 0 && <div className="card"><p className="muted">No candidates match these filters. Try adjusting your search.</p></div>}
      <nav className="pagination" aria-label="Candidate results pages">
        <button className="btn" disabled={page <= 1 || loading} onClick={() => setPage((value) => Math.max(1, value - 1))}>Previous</button>
        <span aria-live="polite">Page {page} of {lastPage}</span>
        <button className="btn" disabled={page >= lastPage || loading} onClick={() => setPage((value) => Math.min(lastPage, value + 1))}>Next</button>
      </nav>
    </section>
  );
}
