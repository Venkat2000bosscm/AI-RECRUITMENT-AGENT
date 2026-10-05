"""Low-cost structured extraction from resumes and free-text requirements."""

import io
import re
from datetime import date

SKILL_ALIASES: dict[str, list[str]] = {
    "Python": ["python", "python3"],
    "Java": ["java"],
    "JavaScript": ["javascript", "js", "ecmascript"],
    "TypeScript": ["typescript", "ts"],
    "Go": ["golang", "go lang"],
    "C++": ["c\\+\\+", "cpp"],
    "C#": ["c#", "csharp", "c sharp"],
    "Rust": ["rust"],
    "Kotlin": ["kotlin"],
    "Swift": ["swift"],
    "Ruby": ["ruby"],
    "PHP": ["php"],
    "Scala": ["scala"],
    "SQL": ["sql", "t-sql", "pl/sql"],
    "React": ["react", "react.js", "reactjs"],
    "Angular": ["angular", "angularjs"],
    "Vue": ["vue", "vue.js", "vuejs"],
    "Next.js": ["next.js", "nextjs"],
    "Node.js": ["node", "node.js", "nodejs"],
    "Django": ["django"],
    "Flask": ["flask"],
    "FastAPI": ["fastapi"],
    "Spring Boot": ["spring boot", "springboot", "spring"],
    ".NET": ["\\.net", "dotnet", "asp\\.net"],
    "HTML": ["html", "html5"],
    "CSS": ["css", "css3", "tailwind", "sass"],
    "REST APIs": ["rest", "restful", "rest api", "rest apis"],
    "GraphQL": ["graphql"],
    "Microservices": ["microservices", "micro-services"],
    "PostgreSQL": ["postgresql", "postgres"],
    "MySQL": ["mysql"],
    "MongoDB": ["mongodb", "mongo"],
    "Redis": ["redis"],
    "Elasticsearch": ["elasticsearch", "elastic search"],
    "Kafka": ["kafka"],
    "RabbitMQ": ["rabbitmq"],
    "AWS": ["aws", "amazon web services", "ec2", "s3", "lambda"],
    "Azure": ["azure"],
    "GCP": ["gcp", "google cloud"],
    "Docker": ["docker", "containers"],
    "Kubernetes": ["kubernetes", "k8s"],
    "Terraform": ["terraform"],
    "CI/CD": ["ci/cd", "cicd", "jenkins", "github actions", "gitlab ci"],
    "Git": ["git", "github", "gitlab"],
    "Linux": ["linux", "unix"],
    "Machine Learning": ["machine learning", "ml"],
    "Deep Learning": ["deep learning"],
    "NLP": ["nlp", "natural language processing"],
    "LLMs": ["llm", "llms", "large language models", "gpt", "generative ai", "genai"],
    "LangChain": ["langchain"],
    "LangGraph": ["langgraph"],
    "PyTorch": ["pytorch"],
    "TensorFlow": ["tensorflow"],
    "scikit-learn": ["scikit-learn", "sklearn"],
    "Pandas": ["pandas"],
    "NumPy": ["numpy"],
    "Spark": ["spark", "pyspark"],
    "Airflow": ["airflow"],
    "Data Analysis": ["data analysis", "data analytics"],
    "Power BI": ["power bi", "powerbi"],
    "Tableau": ["tableau"],
    "Excel": ["excel"],
    "Selenium": ["selenium"],
    "Testing": ["unit testing", "pytest", "junit", "test automation", "qa"],
    "Agile": ["agile", "scrum", "kanban"],
    "System Design": ["system design", "distributed systems"],
    "Security": ["security", "owasp", "iam"],
    "Figma": ["figma"],
    "Communication": ["communication", "stakeholder management"],
    "Leadership": ["leadership", "team lead", "mentoring", "mentored"],
    "Recruitment": ["recruitment", "talent acquisition", "sourcing"],
    "Salesforce": ["salesforce"],
    "SAP": ["sap"],
}

# Skills whose name is also a common English word: match the canonical name case-sensitively.
CASE_SENSITIVE_SKILLS = {"Go"}

EDUCATION_PATTERNS = [
    ("PhD", r"(?<![a-z])(ph\.?d|doctorate)(?![a-z])"),
    ("Master's", r"(?<![a-z])(m\.?tech|m\.e\.|m\.?sc|mca|mba|master'?s?|ms in)(?![a-z])"),
    ("Bachelor's", r"(?<![a-z])(b\.?tech|b\.e\.|b\.?sc|bca|b\.?com|bachelor'?s?|bs in)(?![a-z])"),
    ("Diploma", r"(?<![a-z])diploma(?![a-z])"),
]

WORK_MODES = {"remote": r"\bremote\b", "hybrid": r"\bhybrid\b", "onsite": r"\b(on-?site|in office|office)\b"}


def _alias_regex(alias: str) -> str:
    return rf"(?<![A-Za-z0-9]){alias}(?![A-Za-z0-9+#])"


def canonical_skill(skill: str) -> str:
    s = skill.strip().lower()
    for canonical, aliases in SKILL_ALIASES.items():
        if s == canonical.lower() or any(re.fullmatch(a, s) for a in aliases):
            return canonical
    return skill.strip()


def extract_skills(text: str, extra_skills: list[str] | None = None) -> list[str]:
    lowered = text.lower()
    found: set[str] = set()
    for canonical, aliases in SKILL_ALIASES.items():
        if canonical in CASE_SENSITIVE_SKILLS:
            if re.search(_alias_regex(re.escape(canonical)), text) or any(re.search(_alias_regex(a), lowered) for a in aliases):
                found.add(canonical)
        elif any(re.search(_alias_regex(a), lowered) for a in aliases + [re.escape(canonical.lower())]):
            found.add(canonical)
    for skill in extra_skills or []:
        canon = canonical_skill(skill)
        if canon in SKILL_ALIASES:
            continue
        if re.search(_alias_regex(re.escape(skill.lower())), lowered):
            found.add(canon)
    return sorted(found)


def extract_years_experience(text: str) -> float | None:
    lowered = text.lower()
    explicit = [
        float(m.group(1))
        for m in re.finditer(r"(\d{1,2}(?:\.\d)?)\s*\+?\s*(?:years?|yrs?)(?:\s+of)?(?:\s+\w+){0,3}\s+experience", lowered)
    ]
    explicit += [
        float(m.group(1)) for m in re.finditer(r"experience\s*[:\-]?\s*(\d{1,2}(?:\.\d)?)\s*\+?\s*(?:years?|yrs?)", lowered)
    ]
    explicit = [y for y in explicit if 0 < y <= 45]
    if explicit:
        return max(explicit)

    current = date.today().year
    intervals = []
    for m in re.finditer(r"\b((?:19|20)\d{2})\s*(?:-|–|—|to)\s*((?:19|20)\d{2}|present|current|now|till date)\b", lowered):
        start = int(m.group(1))
        end = current if not m.group(2)[0].isdigit() else int(m.group(2))
        if start <= end <= current + 1:
            intervals.append((start, end))
    if not intervals:
        return None
    intervals.sort()
    merged = [list(intervals[0])]
    for s, e in intervals[1:]:
        if s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    total = sum(e - s for s, e in merged)
    return float(total) if total > 0 else None


def extract_email(text: str) -> str:
    m = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
    return m.group(0) if m else ""


def extract_phone(text: str) -> str:
    m = re.search(r"(\+?\d[\d\s\-()]{8,}\d)", text)
    return m.group(1).strip() if m else ""


def extract_name(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        line = re.sub(r"^(name)\s*[:\-]\s*", "", line, flags=re.IGNORECASE)
        if "@" in line or re.search(r"\d", line) or len(line.split()) > 5:
            continue
        if re.search(r"(resume|curriculum vitae|cv)\b", line, re.IGNORECASE):
            continue
        return line.title() if line.isupper() else line
    return ""


def extract_location(text: str) -> str:
    m = re.search(r"^\s*(?:location|address|city)\s*[:\-]\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
    return m.group(1).strip()[:120] if m else ""


def extract_education(text: str) -> list[str]:
    lowered = text.lower()
    return [label for label, pattern in EDUCATION_PATTERNS if re.search(pattern, lowered)]


def extract_work_mode(text: str) -> str | None:
    lowered = text.lower()
    for mode, pattern in WORK_MODES.items():
        if re.search(pattern, lowered):
            return mode
    return None


def parse_resume(text: str, job_skills: list[str] | None = None) -> dict:
    return {
        "name": extract_name(text),
        "email": extract_email(text),
        "phone": extract_phone(text),
        "location": extract_location(text),
        "skills": extract_skills(text, job_skills),
        "years_experience": extract_years_experience(text),
        "education": extract_education(text),
        "work_mode_preference": extract_work_mode(text),
        "length": len(text),
    }


def parse_requirement(text: str) -> dict:
    """Heuristic requirement intake used when no LLM is configured."""
    lowered = text.lower()
    title = ""
    m = re.search(
        r"(?:hire|hiring|need|looking for|recruit)\s+(?:an?\s+|\d+\s+)?([A-Za-z .+/#-]{3,60}?)(?:\s+with|\s+in|\s+for|,|\.|$)",
        text,
        re.IGNORECASE,
    )
    if m:
        title = m.group(1).strip().title()
    exp_min = exp_max = 0
    m = re.search(r"(\d{1,2})\s*(?:-|to|–)\s*(\d{1,2})\s*(?:years?|yrs?)", lowered)
    if m:
        exp_min, exp_max = int(m.group(1)), int(m.group(2))
    else:
        m = re.search(r"(\d{1,2})\s*\+?\s*(?:years?|yrs?)", lowered)
        if m:
            exp_min = int(m.group(1))
            exp_max = exp_min + 3
    salary_min = salary_max = 0.0
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|to|–)\s*(\d+(?:\.\d+)?)\s*(lpa|lakhs?|l|k|cr)?", lowered)
    if m and m.group(3):
        mult = {"lpa": 100000, "lakh": 100000, "lakhs": 100000, "l": 100000, "k": 1000, "cr": 10000000}[m.group(3)]
        salary_min, salary_max = float(m.group(1)) * mult, float(m.group(2)) * mult
    location = ""
    m = re.search(r"\b(?:in|at|based in|location[:\s])\s*([A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+)?)", text)
    if m:
        location = m.group(1)
    skills = extract_skills(text)
    return {
        "title": title,
        "experience_min": exp_min,
        "experience_max": exp_max,
        "required_skills": skills[:6],
        "preferred_skills": skills[6:],
        "location": location,
        "work_mode": extract_work_mode(text) or "hybrid",
        "salary_min": salary_min,
        "salary_max": salary_max,
    }


def extract_text(filename: str, data: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if name.endswith(".docx"):
        import docx

        document = docx.Document(io.BytesIO(data))
        return "\n".join(p.text for p in document.paragraphs)
    return data.decode("utf-8", errors="ignore")
