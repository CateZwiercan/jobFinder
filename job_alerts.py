#!/usr/bin/env python3


from __future__ import annotations

import hashlib
import html
import os
import re
import smtplib
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv


load_dotenv()

SERPAPI_KEY = os.environ["SERPAPI_KEY"]
EMAIL_TO = os.environ["EMAIL_TO"]
EMAIL_FROM = os.environ["EMAIL_FROM"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]

DB_PATH = "job_alerts.sqlite3"
DAYS_NEW = 3
MAX_EMAIL_JOBS = 20
MIN_FIT_SCORE = 30

# Override with environment variables if they exist
DB_PATH = os.getenv("DB_PATH", DB_PATH)
DAYS_NEW = int(os.getenv("DAYS_NEW", DAYS_NEW))
MAX_EMAIL_JOBS = int(os.getenv("MAX_EMAIL_JOBS", MAX_EMAIL_JOBS))
MIN_FIT_SCORE = int(os.getenv("MIN_FIT_SCORE", MIN_FIT_SCORE))

# Search phrases. Each phrase gets searched in each target market.
SEARCHES = [
    "frontend software engineer",
    "front end software engineer",
    "frontend developer",
    "Angular developer",
    "Angular software engineer",
    "Product Owner",
    "Technical Product Owner",
    "Business Analyst",
    "Technical Business Analyst",
    "Product Manager",
    "Technical Product Manager",
    "Engineering Manager",
    "Software Engineering Manager",
    "IT Manager",
    "Technology Manager",
]

# Manager searches are intentionally technical/product-oriented rather than
# generic people/operations management.
MANAGER_REQUIRED_TERMS = (
    "engineering manager",
    "software engineering manager",
    "frontend manager",
    "front end manager",
    "development manager",
    "software development manager",
    "technical manager",
    "technology manager",
    "it manager",
    "product manager",
)

# Roles to deprioritize when the title is otherwise too broad.
GENERIC_MANAGER_TERMS = (
    "store manager",
    "restaurant manager",
    "retail manager",
    "sales manager",
    "account manager",
    "property manager",
    "office manager",
    "warehouse manager",
    "district manager",
    "operations manager",
    "general manager",
)

# Remote is searched separately because a remote job may not be tied to one
# of the local metros.
REMOTE_SEARCHES = [
    "frontend software engineer remote",
    "front end software engineer remote",
    "Angular developer remote",
    "Angular software engineer remote",
    "Product Owner remote",
    "Business Analyst remote",
    "Technical Business Analyst remote",
    "Product Manager remote",
    "Technical Product Manager remote",
    "Engineering Manager remote",
    "Software Engineering Manager remote",
]

# Local markets requested by the user.
LOCAL_MARKETS = [
    ("Greater Philadelphia", "Philadelphia, PA"),
    ("Greater Philadelphia", "King of Prussia, PA"),
    ("Greater Philadelphia", "Malvern, PA"),
    ("Greater Philadelphia", "Conshohocken, PA"),
    ("Greater Philadelphia", "Wayne, PA"),
    ("Delaware", "Wilmington, DE"),
    ("Delaware", "Newark, DE"),
    ("New York City", "New York, NY"),
    ("Boston", "Boston, MA"),
    ("DC", "Washington, DC"),
    ("DC", "Arlington, VA"),
    ("DC", "Alexandria, VA"),
]

# These are the kinds of application URLs we consider "direct".
# Aggregator links such as Indeed/ZipRecruiter/LinkedIn are deliberately
# rejected when a company/ATS link is also available.
DIRECT_HOST_HINTS = (
    "greenhouse.io",
    "lever.co",
    "ashbyhq.com",
    "myworkdayjobs.com",
    "workday.com",
    "icims.com",
    "smartrecruiters.com",
    "jobvite.com",
    "bamboohr.com",
    "ultipro.com",
    "ukg.com",
    "paycom.com",
    "paylocity.com",
    "successfactors.com",
    "oraclecloud.com",
    "taleo.net",
    "phenom.com",
    "eightfold.ai",
    "recruitee.com",
)

AGGREGATOR_HOSTS = (
    "indeed.com",
    "linkedin.com",
    "ziprecruiter.com",
    "glassdoor.com",
    "monster.com",
    "careerbuilder.com",
    "simplyhired.com",
    "talent.com",
    "jooble.org",
    "lensa.com",
    "bebee.com",
    "dice.com",
    "builtina.com",
    "builtin.com",
)


@dataclass
class Job:
    title: str
    company: str
    location: str
    via: str
    description: str
    posted: str
    apply_url: str
    source_query: str
    fit_score: int = 0


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sent_jobs (
            job_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            company TEXT NOT NULL,
            location TEXT,
            apply_url TEXT NOT NULL,
            first_seen TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def job_id(job: Job) -> str:
    # URL is the strongest identifier; fall back to title/company/location.
    raw = job.apply_url or "|".join(
        [job.title, job.company, job.location]
    )
    return hashlib.sha256(normalize(raw).encode()).hexdigest()


def looks_like_direct_url(url: str) -> bool:
    if not url:
        return False

    try:
        host = urlparse(url).netloc.lower().split(":")[0]
    except Exception:
        return False

    if any(bad in host for bad in AGGREGATOR_HOSTS):
        return False

    if any(hint in host for hint in DIRECT_HOST_HINTS):
        return True

    # Company career domains can vary, so we also accept non-aggregator
    # domains as a fallback. The script prefers ATS links first.
    return bool(host)


def choose_direct_link(job: dict) -> str | None:
    """
    SerpApi Google Jobs may return multiple apply_options.
    Prefer an employer ATS/careers URL over aggregators.
    """
    options = job.get("apply_options") or []

    # First pass: known ATS/career platforms.
    for option in options:
        link = option.get("link")
        if not link:
            continue
        host = urlparse(link).netloc.lower()
        if any(hint in host for hint in DIRECT_HOST_HINTS):
            return link

    # Second pass: any non-aggregator link.
    for option in options:
        link = option.get("link")
        if link and looks_like_direct_url(link):
            return link

    # Some results have an explicit share/apply link.
    for key in ("apply_link", "link"):
        link = job.get(key)
        if link and looks_like_direct_url(link):
            return link

    return None


def score_job(job: Job) -> int:
    """
    Score how closely a job matches the user's target profile.

    Higher = stronger match. This is an ordering mechanism only; jobs below
    the minimum threshold are filtered out.
    """
    title = normalize(job.title)
    text = normalize(f"{job.title} {job.description}")

    score = 0

    # Strongest fit: Angular/front-end.
    if "angular" in title:
        score += 45
    elif "angular" in text:
        score += 28

    if "front end" in title or "frontend" in title:
        score += 40
    elif "front end" in text or "frontend" in text:
        score += 20

    # Product/business tracks.
    if "product owner" in title:
        score += 38
    if "business analyst" in title:
        score += 35
    if "technical business analyst" in title:
        score += 10
    if "product manager" in title:
        score += 32
    if "technical product manager" in title:
        score += 8

    # Technical management.
    if "engineering manager" in title or "software engineering manager" in title:
        score += 32
    elif "development manager" in title or "software development manager" in title:
        score += 28
    elif "technical manager" in title or "technology manager" in title:
        score += 25
    elif "it manager" in title:
        score += 20

    # Direct software-engineering signal.
    if "software engineer" in title:
        score += 25
    elif "software developer" in title:
        score += 22

    # Helpful technical keywords.
    for keyword, points in (
        ("typescript", 5),
        ("javascript", 5),
        ("react", 3),
        ("api", 3),
        ("web application", 3),
        ("saas", 2),
        ("agile", 2),
        ("scrum", 2),
    ):
        if keyword in text:
            score += points

    # Penalize clearly unrelated manager roles.
    if any(term in title for term in GENERIC_MANAGER_TERMS):
        score -= 60

    # Remote is useful, but local requested markets are equally eligible.
    if "remote" in text:
        score += 5

    return score


def relevant_title(title: str) -> bool:
    t = normalize(title)

    # Explicitly requested functions.
    wanted = (
        "front end",
        "frontend",
        "angular",
        "product owner",
        "business analyst",
        "product manager",
        "engineering manager",
        "software engineering manager",
        "technology manager",
        "technical manager",
        "it manager",
    )
    if not any(term in t for term in wanted):
        return False

    # A generic "manager" result should not make it through unless it is
    # explicitly technical/product/engineering related.
    if "manager" in t:
        if any(term in t for term in GENERIC_MANAGER_TERMS):
            return False
        if not any(term in t for term in MANAGER_REQUIRED_TERMS):
            return False

    return True


def work_arrangement_matches(job: dict, is_remote_search: bool) -> bool:
    text = normalize(
        " ".join(
            [
                job.get("title", ""),
                job.get("location", ""),
                job.get("description", ""),
                " ".join(job.get("detected_extensions", {}).values())
                if isinstance(job.get("detected_extensions"), dict)
                else "",
            ]
        )
    )

    remote_words = ("remote", "work from home", "fully remote", "remote us")
    hybrid_words = ("hybrid", "remote or hybrid")
    onsite_words = ("onsite", "on-site", "in office", "office")

    if is_remote_search:
        return any(w in text for w in remote_words)

    # Local search: accept local jobs whether hybrid or onsite.
    return True


def fetch_jobs(query: str, location: str | None = None) -> list[dict]:
    params = {
        "engine": "google_jobs",
        "q": query,
        "hl": "en",
        "api_key": SERPAPI_KEY,
    }
    if location:
        params["location"] = location

    response = requests.get(
        "https://serpapi.com/search.json",
        params=params,
        timeout=45,
    )
    response.raise_for_status()
    data = response.json()

    if "error" in data:
        raise RuntimeError(data["error"])

    return data.get("jobs_results", [])


def posted_within_window(job: dict) -> bool:
    """
    Google Jobs usually gives strings like:
      "Today"
      "1 day ago"
      "3 days ago"
      "30+ days ago"
    We intentionally keep only recent postings.
    """
    posted = normalize(
        job.get("detected_extensions", {}).get("posted_at", "")
        if isinstance(job.get("detected_extensions"), dict)
        else ""
    )

    if not posted:
        # If no age is supplied, keep it; SQLite deduplication still prevents
        # repeated alerts.
        return True

    if "today" in posted or "just posted" in posted:
        return True

    match = re.search(r"(\d+)\s+day", posted)
    if match:
        return int(match.group(1)) <= DAYS_NEW

    if "week" in posted or "month" in posted:
        return False

    return True


def convert_job(raw: dict, query: str) -> Job | None:
    title = raw.get("title", "").strip()
    company = raw.get("company_name", "").strip()
    location = raw.get("location", "").strip()
    description = raw.get("description", "").strip()
    via = raw.get("via", "").strip()
    posted = ""

    extensions = raw.get("detected_extensions") or {}
    if isinstance(extensions, dict):
        posted = extensions.get("posted_at", "")

    if not title or not company:
        return None

    if not relevant_title(title):
        return None

    if not posted_within_window(raw):
        return None

    apply_url = choose_direct_link(raw)
    if not apply_url:
        # User specifically asked for direct application links.
        return None

    return Job(
        title=title,
        company=company,
        location=location or "Location not provided",
        via=via,
        description=description,
        posted=posted or "Recently posted",
        apply_url=apply_url,
        source_query=query,
        fit_score=0,  # Calculated after the Job object is created.
    )


def search_all() -> list[Job]:
    jobs: dict[str, Job] = {}

    # Local jobs: remote/hybrid/onsite in requested markets.
    for market_name, location in LOCAL_MARKETS:
        for query in SEARCHES:
            print(f"Searching {query!r} in {location}...")
            try:
                results = fetch_jobs(query, location)
                for raw in results:
                    job = convert_job(raw, f"{query} | {location}")
                    if job:
                        # Make sure the result is actually local to the requested
                        # market rather than an unrelated national listing.
                        if location.lower().split(",")[0] in normalize(
                            raw.get("location", "")
                        ) or "remote" in normalize(raw.get("location", "")):
                            job.fit_score = score_job(job)
                            if job.fit_score >= MIN_FIT_SCORE:
                                jobs[job_id(job)] = job
            except Exception as exc:
                print(f"  Search failed: {exc}")

            time.sleep(0.25)

    # Remote US jobs.
    for query in REMOTE_SEARCHES:
        print(f"Searching {query!r} across the US...")
        try:
            results = fetch_jobs(query, "United States")
            for raw in results:
                job = convert_job(raw, f"{query} | United States")
                if job and work_arrangement_matches(raw, True):
                    job.fit_score = score_job(job)
                    if job.fit_score >= MIN_FIT_SCORE:
                        jobs[job_id(job)] = job
        except Exception as exc:
            print(f"  Search failed: {exc}")

        time.sleep(0.25)

    return list(jobs.values())


def get_unsent_jobs(jobs: list[Job]) -> list[Job]:
    conn = db()
    try:
        result = []

        for job in jobs:
            jid = job_id(job)
            exists = conn.execute(
                "SELECT 1 FROM sent_jobs WHERE job_id = ?",
                (jid,),
            ).fetchone()

            if not exists:
                result.append(job)

        return result
    finally:
        conn.close()


def mark_sent(jobs: list[Job]):
    conn = db()
    try:
        now = datetime.now(timezone.utc).isoformat()

        for job in jobs:
            conn.execute(
                """
                INSERT OR IGNORE INTO sent_jobs
                (job_id, title, company, location, apply_url, first_seen)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id(job),
                    job.title,
                    job.company,
                    job.location,
                    job.apply_url,
                    now,
                ),
            )

        conn.commit()
    finally:
        conn.close()


def job_email_html(jobs: list[Job]) -> str:
    today = datetime.now().strftime("%B %-d, %Y")

    cards = []
    for job in sorted(
        jobs,
        key=lambda x: (-x.fit_score, normalize(x.company), normalize(x.title)),
    ):
        cards.append(
            f"""
            <div style="border:1px solid #ddd;border-radius:10px;
                        padding:16px;margin:0 0 14px 0;">
              <h2 style="margin:0 0 6px 0;font-size:18px;">
                {html.escape(job.title)}
              </h2>
              <div style="margin-bottom:6px;">
                <strong>{html.escape(job.company)}</strong>
              </div>
              <div style="color:#555;margin-bottom:6px;">
                {html.escape(job.location)}
                &nbsp;•&nbsp; {html.escape(job.posted)}
                &nbsp;•&nbsp; Fit score: <strong>{job.fit_score}</strong>
              </div>
              <p style="margin:10px 0;line-height:1.45;">
                {html.escape(job.description[:500])}
              </p>
              <a href="{html.escape(job.apply_url, quote=True)}"
                 style="display:inline-block;padding:10px 15px;
                        background:#111;color:#fff;text-decoration:none;
                        border-radius:6px;">
                Apply directly
              </a>
            </div>
            """
        )

    return f"""
    <html>
      <body style="font-family:Arial,sans-serif;max-width:800px;margin:auto;">
        <h1>New job matches — {today}</h1>
        <p>
          Found <strong>{len(jobs)}</strong> new jobs matching your saved
          roles and locations. Links below prioritize the employer's
          application/ATS page instead of job-board listings.
        </p>
        {''.join(cards)}
        <p style="color:#777;font-size:12px;">
          Automated job alert. Always verify the role is still open before
          applying.
        </p>
      </body>
    </html>
    """


def job_email_text(jobs: list[Job]) -> str:
    lines = [f"NEW JOB MATCHES: {len(jobs)}", ""]

    for job in jobs:
        lines.extend(
            [
                job.title,
                job.company,
                f"{job.location} | {job.posted} | Fit score: {job.fit_score}",
                job.apply_url,
                "",
            ]
        )

    return "\n".join(lines)


def send_email(jobs: list[Job]):
    if not jobs:
        print("No new jobs. No email sent.")
        return

    message = EmailMessage()
    message["Subject"] = f"🚀 {len(jobs)} new job matches"
    message["From"] = SMTP_USER
    message["To"] = EMAIL_TO

    message.set_content(job_email_text(jobs))
    message.add_alternative(job_email_html(jobs), subtype="html")

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.starttls()
        smtp.login(SMTP_USER, SMTP_PASSWORD)
        smtp.send_message(message)

    print(f"Sent {len(jobs)} jobs to {EMAIL_TO}")


def main():
    started = datetime.now()
    print(f"Job alert started: {started.isoformat()}")

    all_jobs = search_all()

    # Final deduplication.
    unique = {}
    for job in all_jobs:
        unique[job_id(job)] = job

    new_jobs = get_unsent_jobs(list(unique.values()))

    # Highest-fit jobs first, with a configurable daily email cap.
    new_jobs.sort(
        key=lambda x: (-x.fit_score, normalize(x.company), normalize(x.title))
    )
    new_jobs = new_jobs[:MAX_EMAIL_JOBS]

    print(f"Matching jobs found: {len(unique)}")
    print(f"New jobs to email: {len(new_jobs)}")
    print(f"Daily email cap: {MAX_EMAIL_JOBS}")
    print(f"Minimum fit score: {MIN_FIT_SCORE}")

    if new_jobs:
        send_email(new_jobs)
        mark_sent(new_jobs)

    print("Done.")


if __name__ == "__main__":
    main()
