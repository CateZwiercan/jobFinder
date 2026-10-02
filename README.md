# Job Alert Bot

## What It Does

This bot searches for job postings matching the following roles:

- **Front-End Software Engineer**
- **Front-End Developer**
- **Angular Developer / Angular Software Engineer**
- **Product Owner**
- **Business Analyst / Technical Business Analyst**
- **Product Manager / Technical Product Manager**
- **Engineering Manager / Software Engineering Manager**
- **Technology / IT Manager**

### Search Locations

The bot searches for jobs in the following locations:

- Remote (US-based jobs)
- Greater Philadelphia
- Delaware
- New York City
- Boston
- Washington, DC
- Nearby DC suburbs: Arlington and Alexandria

For local searches, it accepts **remote**, **hybrid**, and **onsite** listings.

### Features

- **Direct Application Links**: The bot prioritizes employer's direct application/ATS URLs (e.g., Greenhouse, Lever, Ashby, Workday, iCIMS, SmartRecruiters) instead of aggregator links like Indeed, LinkedIn, or ZipRecruiter.
- **SQLite Database**: Emailed jobs are stored in an SQLite database to avoid sending duplicate postings.
- **Relevance Scoring**: Jobs are scored based on relevance, and only the most relevant ones are emailed.

---

## Setup Instructions

### 1. Get a SerpApi Key

- Create an account at [SerpApi](https://serpapi.com/).
- Store the API key as an environment variable (`SERPAPI_KEY`).

### 2. Gmail Setup

- If using Gmail, enable **2-Step Verification** and create a **Google App Password**.
- Use the App Password for the `SMTP_PASSWORD` environment variable.
- **Do NOT use your regular Gmail password.**

### 3. Install Dependencies

```bash
# Create a virtual environment
python -m venv .venv

# Activate the virtual environment
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

# Install required packages
pip install -r requirements.txt