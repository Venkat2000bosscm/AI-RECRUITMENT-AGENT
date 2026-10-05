export const CATEGORY_LABEL = {
  strong_match: "Strong Match",
  partial_match: "Partial Match",
  weak_match: "Weak Match",
  human_review: "Human Review",
};

export const APPROVAL_LABEL = {
  jd_publication: "JD publication",
  strategy_change: "Strategy change",
  shortlist: "Shortlist",
  human_review: "Human review",
  interview_schedule: "Interview schedule",
  hiring_decision: "Hiring decision",
  offer: "Offer",
  onboarding: "Onboarding",
};

export const fmtDate = (d) => (d ? new Date(d + (d.endsWith("Z") ? "" : "Z")).toLocaleString() : "—");
export const fmtMoney = (n, cur = "INR") =>
  cur === "INR" && n >= 100000 ? `₹${(n / 100000).toFixed(1)} LPA` : `${cur} ${Number(n || 0).toLocaleString()}`;
export const pretty = (s) => (s || "").replace(/_/g, " ");
export const effectiveCategory = (c) => c.hr_category_override || c.category;
