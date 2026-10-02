Job Alert Bot

What it does

Every time it runs, this bot searches for:

Front-End Software Engineer

Front-End Developer

Angular Developer / Angular Software Engineer

Product Owner

Business Analyst / Technical Business Analyst

Product Manager / Technical Product Manager

Engineering Manager / Software Engineering Manager

Technology / IT Manager

It searches:

Remote US jobs

Greater Philadelphia

Delaware

New York City

Boston

Washington, DC

Nearby DC suburbs: Arlington and Alexandria

For local searches, it accepts remote, hybrid, and onsite listings.

For each result it tries to find the employer's direct application/ATS URL
(Greenhouse, Lever, Ashby, Workday, iCIMS, SmartRecruiters, etc.) instead
of sending you to Indeed/LinkedIn/ZipRecruiter.

It stores emailed jobs in SQLite, so the same posting isn't emailed again.

1. Get a SerpApi key

Create an account at https://serpapi.com/

Then put the API key in .env.

2. Gmail setup

If using Gmail, enable 2-Step Verification and create a Google App Password.

Put that App Password in:

SMTP_PASSWORD=...

Do NOT put your normal Gmail password in the script.

3. Install

python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt

4. Create .env

Copy .env.example to .env and fill in your values.

5. Test

python job_alerts.py

The first run can produce several matches. Later runs only email jobs
that haven't already been emailed.

6. Run automatically every morning

Windows Task Scheduler

Create a task that runs:

python C:\path\to\job_alerts.py

Set it to run daily, e.g. 8:00 AM.

GitHub Actions

The same script can also run on a schedule. Store these GitHub Secrets:

SERPAPI_KEY

SMTP_HOST

SMTP_PORT

SMTP_USER

SMTP_PASSWORD

EMAIL_TO

Then create .github/workflows/job-alerts.yml:

name: Job Alerts

on:
  schedule:
    - cron: "0 13 * * *"   # 8 AM Central / 13:00 UTC
  workflow_dispatch:

jobs:
  search:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - run: pip install -r requirements.txt

      - name: Restore job database
        uses: actions/cache@v4
        with:
          path: job_alerts.sqlite3
          key: job-alerts-db-${{ github.ref_name }}-${{ github.run_number }}
          restore-keys: |
            job-alerts-db-${{ github.ref_name }}-

      - name: Run job alert
        env:
          SERPAPI_KEY: ${{ secrets.SERPAPI_KEY }}
          SMTP_HOST: ${{ secrets.SMTP_HOST }}
          SMTP_PORT: ${{ secrets.SMTP_PORT }}
          SMTP_USER: ${{ secrets.SMTP_USER }}
          SMTP_PASSWORD: ${{ secrets.SMTP_PASSWORD }}
          EMAIL_TO: ${{ secrets.EMAIL_TO }}
        run: python job_alerts.py

      - name: Save job database
        uses: actions/cache/save@v4
        with:
          path: job_alerts.sqlite3
          key: job-alerts-db-${{ github.ref_name }}-${{ github.run_number }}

For a truly persistent database across GitHub Actions runs, I recommend
using a small hosted SQLite-compatible database or committing the database
to a private repository rather than relying on Actions cache.

Notes about "direct" application links

Job boards frequently expose several application destinations. The script
prioritizes recognizable employer ATS domains. If it cannot find a direct
employer/ATS destination, it drops that result rather than sending you an
aggregator link.

This is intentionally conservative: the goal is a clickable Apply Directly
button that gets you as close as possible to the employer's actual
application form.

Relevance scoring

The bot now scores jobs before emailing them.

Strong signals include:

Angular

Front-end / frontend

Software Engineer

Product Owner

Business Analyst

Technical Product Manager

Engineering Manager / Software Engineering Manager

Technical/Technology Manager

Angular and front-end roles receive the strongest weighting.

Generic roles such as Store Manager, Restaurant Manager, Sales Manager,
Retail Manager, Office Manager, and Operations Manager are excluded.

Control how many jobs you receive

In .env:

MAX_EMAIL_JOBS=20
MIN_FIT_SCORE=30
DAYS_NEW=3

For example, MAX_EMAIL_JOBS=10 gives you only the top 10 matches per run.
Increase MIN_FIT_SCORE if you want fewer but more targeted matches.