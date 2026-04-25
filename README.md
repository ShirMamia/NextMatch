# NextMatch

**NextMatch** is an AI-assisted, evidence-grounded job application workflow platform.

It helps a candidate move through the full application pipeline in one structured system:

- parse a candidate profile from a CV
- parse and normalize job postings
- score candidate-job fit
- generate a tailored resume and cover letter
- validate generated drafts before approval
- approve and save application artifacts
- track application status over time
- view dashboard metrics
- export tracker data to XLSX

The project is built as a modular, interview-quality MVP with strong emphasis on **traceability**, **validation**, and **clear system boundaries**.

---

## What problem NextMatch solves

Job seekers often work across disconnected tools:

- one place for finding jobs
- another place for rewriting resumes
- another place for tracking applications
- no reliable validation layer between generation and action

This creates friction, inconsistency, and low trust in the final output.

NextMatch brings these steps into one workflow-driven system with explicit checkpoints:

1. **Profile ingestion**
2. **Job ingestion and matching**
3. **AI-assisted tailoring**
4. **Validation**
5. **Approval**
6. **Application tracking**
7. **Dashboard and export**

---

## Current MVP scope

The current MVP covers the core workflow through **Slice 9**.

### 1. Candidate profile parsing
- Parse a CV into a structured `CandidateProfile`
- Preserve raw CV text
- Validate key structured fields

### 2. Job parsing and normalization
- Parse job descriptions into structured `JobPosting` objects
- Preserve raw job text
- Support normalized job metadata and requirements

### 3. Job ranking and candidate-job matching
- Score candidate-job fit
- Break down fit into interpretable factors
- Surface matched skills, missing signals, strengths, gaps, and recommendations

### 4. Resume tailoring
- Generate a tailored resume draft
- Reorder relevant experience
- Rewrite bullets in a job-aligned way
- Generate a grounded cover letter draft

### 5. Validation and trustworthiness
- Validate tailored resume drafts
- Validate cover letter drafts
- Require validation before approval
- Block approval when validation fails or becomes stale

### 6. Approval workflow
- Enforce approval gates before saving
- Save approved artifacts through the repository layer
- Create an `ApplicationRecord` through the tracker service
- Prevent accidental duplicate approval of the same artifact set in the UI

### 7. Application tracking
- Persist and retrieve application records
- Manually update application status
- Automatically manage `applied_at` when status changes require it

### 8. Dashboard and export
- Compute summary metrics from all saved application records
- Show dashboard KPIs and per-status breakdown
- Export tracker data to a two-sheet XLSX file:
  - **Applications**
  - **Summary**

---

## Design principles

NextMatch is built around a few explicit engineering principles:

- **Modular architecture**  
  Each layer has a focused responsibility.

- **Grounded outputs**  
  Generated content should remain tied to candidate evidence.

- **Validation before trust**  
  Drafts are not treated as approved artifacts until they pass validation.

- **Workflow traceability**  
  Matching, generation, validation, approval, and tracking are separated and inspectable.

- **Interview-quality implementation**  
  The system is designed to be easy to explain, test, and extend.

---

## Architecture

NextMatch is organized as a modular Python application with clear layers:

- **UI** — Streamlit pages and reusable UI components
- **Parsers** — CV and job parsing
- **Matching** — candidate-job fit scoring and analysis
- **Generation** — resume and cover letter generation
- **Validation** — validation reports and approval gates
- **Orchestration** — workflow-level logic
- **Reporting** — tracker, dashboard summary, export
- **Storage** — repository abstraction and file-backed persistence
- **Schemas** — typed domain models
- **Services / Utils** — config, IDs, time helpers, LLM client

### High-level flow

```text
CV -> CandidateProfile
Job text -> JobPosting
CandidateProfile + JobPosting -> MatchResult
MatchResult + CandidateProfile + JobPosting -> TailoredResume / CoverLetterDraft
Tailored artifacts -> ValidationReport
Validated artifacts -> Approval pipeline
Approval pipeline -> ApplicationRecord
ApplicationRecord -> Tracker / Dashboard / Export
```

---

## Project structure

```text
NextMatch/
├── app/
│   ├── ui/
│   │   ├── main.py
│   │   ├── views/
│   │   │   ├── tailoring_page.py
│   │   │   ├── tracker_page.py
│   │   │   └── dashboard_page.py
│   │   └── components/
│   ├── parsers/
│   ├── matching/
│   ├── generation/
│   ├── validation/
│   ├── orchestration/
│   │   └── application_pipeline.py
│   ├── reporting/
│   │   ├── tracker.py
│   │   ├── dashboard.py
│   │   └── exporter.py
│   ├── storage/
│   ├── schemas/
│   ├── services/
│   └── utils/
├── tests/
│   ├── test_tracker.py
│   ├── test_dashboard.py
│   └── ...
├── data/
├── outputs/
├── requirements.txt
├── README.md
└── CLAUDE.md
```

---

## Main UI pages

### Tailoring Studio
- View candidate-job fit
- Generate tailored resume and cover letter drafts
- Validate drafts
- Approve and save validated artifacts

### Application Tracker
- View saved application records
- Update application status manually
- Keep application progress organized in one place

### Dashboard
- View top-level application funnel metrics
- Inspect per-status counts
- Download tracker data as XLSX

---

## Running the project

### 1. Create and activate a dedicated environment

```bash
conda create -n nextmatch python=3.12 -y
conda activate nextmatch
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Run the test suite

```bash
python -m pytest tests/ -q
```

### 4. Run the Streamlit app

```bash
python -m streamlit run app/ui/main.py
```

---

## Dependencies

The project currently relies on:

- `streamlit`
- `pydantic`
- `anthropic`
- `pdfplumber`
- `numpy`
- `pandas`
- `openpyxl`
- `python-dotenv`
- `pytest`
- `pytest-mock`

---

## Testing

The project includes focused tests for:

- CV parsing
- job parsing
- job ranking
- candidate-job matching
- resume tailoring
- validation
- approval pipeline
- tracker service
- dashboard metrics
- XLSX export

This keeps the MVP explainable and safer to extend.

---

## What is intentionally out of scope for the current MVP

The current version is a structured MVP, not a full production system.

Examples of intentionally limited or deferred areas:

- external job-source integrations at production depth
- background jobs / async orchestration
- multi-user authentication
- deployment infrastructure
- advanced tracker analytics beyond the current dashboard
- full audit/event history
- rich inline editing of generated artifacts
- database-backed persistence beyond the current MVP storage approach

---

## Why this project is strong technically

NextMatch is not just a text-generation demo.

It demonstrates:
- structured parsing
- deterministic scoring
- schema-driven validation
- approval gating
- persistent tracking
- dashboard summarization
- export
- modular architecture
- test coverage

In other words, it treats AI generation as **one layer in a controlled application workflow**, not as the whole product.

---

## Future directions

Likely next steps after the current MVP include:

- tracker usability improvements
- search and filtering in the tracker
- richer dashboard visualizations
- editable notes and better application management UX
- stronger import/export flows
- deeper source integrations
- deployment and demo hardening

---

## Status

**Current status:** MVP complete through **Slice 9**  
Includes end-to-end application workflow, tracker, dashboard, and XLSX export.
