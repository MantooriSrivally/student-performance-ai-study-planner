# Student Performance AI — Jury-Ready Frontend

This package adds a presentation-grade frontend and a thin local integration runner around the **existing Python pipeline**.

## Architecture

```text
Browser
  │
  ├── view/edit/upload five source JSON objects
  ▼
frontend/server.js
  │
  ├── writes a temporary data directory
  └── launches pipeline_runner.py
              │
              ▼
        existing backend/app/core/pipeline.py
        Load → Validate → KPI → Report
              │
              ▼
        strict StudentPerformanceReport JSON
              │
              ▼
Browser renders the report
```

The backend pipeline files are preserved. The runner passes `data_dir=<temporary directory>` to the existing `StudentDataPipeline`; it does not modify the pipeline implementation.

## Run locally

1. Install the backend dependencies:

```bash
cd backend
python -m pip install -r requirements.txt
cd ..
```

2. Start the presentation frontend:

```bash
node frontend/server.js
```

3. Open `http://localhost:4173`.

The default report uses the existing mock data and the local report engine. If you configure the backend's supported Gemini environment variables, the existing analyzer can use that engine; no frontend changes are required.

## New student flow

Use **Data Lab → Open source-data editor** or import the generated JSON template.

The UI accepts the same five source objects used by the existing backend:

- `student.json`
- `interview.json`
- `assignment.json`
- `assessment.json`
- `attendance.json`

Click **Run pipeline on these sources**. The server creates a temporary directory, executes the same Python pipeline against those sources, validates the result, and sends only the report back to the browser.

This means a new student's data follows the same load → validation → KPI → report contract as the mock student.

## Production / Docker

```bash
docker build -t student-performance-ai .
docker run --rm -p 4173:4173 student-performance-ai
```

For a cloud deployment, put the container behind HTTPS and set any required environment variables at deployment time. Do not commit API keys.

## Jury presentation features

- Executive overview with animated score ring
- Academic, interview, attendance and placement KPIs
- Evidence-backed dimension score map
- Interview question-by-question deep dive
- Placement readiness, blockers and target roles
- 90-day action plan
- Strengths and growth evidence
- Counselor recommendation
- Strict JSON report viewer
- Print / PDF-friendly presentation mode
- New-student input editor and JSON bundle import
- Pipeline status and error feedback
- Responsive layout for laptop/projector/tablet use

## Important

The included original backend `.env` was intentionally not packaged because API credentials must never be distributed with the application.
