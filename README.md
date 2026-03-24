# NextMatch

**NextMatch** is an AI-powered, evidence-grounded platform for **job discovery**, **resume tailoring**, **matching**, and **application tracking**.

It helps candidates find relevant roles, analyze fit, tailor their resumes responsibly, and manage their application pipeline through a modular workflow with validation and reporting layers.

---

## Overview

Job seekers often use disconnected tools for searching roles, adapting resumes, and tracking applications. This creates friction, inconsistency, and low visibility into the overall process.

NextMatch addresses this by combining the main steps of the workflow into one structured platform:

- discover relevant job opportunities from multiple sources
- parse and normalize job and candidate data
- rank jobs based on candidate fit
- generate tailored resume content and cover letters
- validate generated content with evidence-grounded checks
- track applications and surface portfolio-level metrics in a dashboard

The system is designed as a modular, interview-friendly MVP with clear boundaries between parsing, orchestration, generation, validation, storage, and reporting.

---

## Core Features

### Job discovery
- Multi-source job discovery pipeline
- Support for external and manual job sources
- Job normalization and deduplication
- Ranking and filtering of relevant roles

### Candidate-job matching
- Candidate profile extraction from CV
- Job parsing into structured representation
- Match scoring and gap analysis
- Recommendations based on fit and missing signals

### Resume tailoring
- AI-assisted resume tailoring
- Bullet rewriting for role alignment
- Section reordering
- Cover letter generation

### Validation and trustworthiness
- Evidence-grounded generation workflow
- Claim checking
- Consistency validation
- Duplication detection
- Validation flags for suspicious or weak outputs

### Tracking and reporting
- Application tracking
- Dashboard analytics
- Exportable outputs
- Summary metrics for pipeline visibility

### UI
- Streamlit-based interface
- Dedicated pages for profile, search, discovery, tailoring, tracker, and dashboard views

---

## Design Principles

NextMatch was built around a few core engineering principles:

- **Modularity**: each layer has a focused responsibility
- **Grounded outputs**: generated text should be tied to available candidate evidence
- **Validation-first thinking**: AI outputs are checked before being trusted
- **Traceable workflow**: parsing, matching, generation, and tracking are separated and inspectable
- **Interview-quality architecture**: clean structure, testable modules, and explicit pipelines

---

## Architecture

The project is structured as a modular Python application:

```text
nextmatch/
├── app/
│   ├── ui/
│   │   ├── main.py
│   │   ├── pages/
│   │   │   ├── profile_page.py
│   │   │   ├── search_page.py
│   │   │   ├── discovery_page.py
│   │   │   ├── tailoring_page.py
│   │   │   ├── tracker_page.py
│   │   │   └── dashboard_page.py
│   │   └── components/
│   │       ├── job_card.py
│   │       ├── evidence_panel.py
│   │       ├── validation_panel.py
│   │       └── score_badge.py
│   ├── orchestration/
│   │   ├── discovery_pipeline.py
│   │   ├── tailoring_pipeline.py
│   │   └── application_pipeline.py
│   ├── parsers/
│   │   ├── cv_parser.py
│   │   ├── job_parser.py
│   │   ├── candidate_extractor.py
│   │   └── text_cleaner.py
│   ├── discovery/
│   │   ├── search_profiles.py
│   │   ├── job_discovery.py
│   │   ├── job_normalizer.py
│   │   ├── job_ranker.py
│   │   ├── deduper.py
│   │   └── sources/
│   │       ├── greenhouse_source.py
│   │       ├── lever_source.py
│   │       ├── manual_source.py
│   │       └── saved_source.py
│   ├── matching/
│   │   ├── matcher.py
│   │   ├── scorer.py
│   │   ├── gap_analyzer.py
│   │   └── recommender.py
│   ├── generation/
│   │   ├── prompts.py
│   │   ├── resume_tailor.py
│   │   ├── bullet_rewriter.py
│   │   ├── section_reorderer.py
│   │   └── cover_letter_generator.py
│   ├── validation/
│   │   ├── grounding_validator.py
│   │   ├── claim_checker.py
│   │   ├── consistency_validator.py
│   │   ├── duplication_validator.py
│   │   └── flags.py
│   ├── reporting/
│   │   ├── tracker.py
│   │   ├── dashboard.py
│   │   ├── metrics.py
│   │   └── exporter.py
│   ├── storage/
│   │   ├── repository.py
│   │   ├── file_store.py
│   │   └── sqlite_store.py
│   ├── schemas/
│   │   ├── candidate.py
│   │   ├── search.py
│   │   ├── job.py
│   │   ├── match.py
│   │   ├── tailoring.py
│   │   ├── validation.py
│   │   └── application.py
│   ├── services/
│   │   ├── llm_client.py
│   │   └── config.py
│   └── utils/
│       ├── ids.py
│       ├── time.py
│       └── logging.py
├── tests/
│   ├── test_cv_parser.py
│   ├── test_job_parser.py
│   ├── test_job_ranker.py
│   ├── test_matcher.py
│   ├── test_resume_tailor.py
│   ├── test_grounding_validator.py
│   ├── test_tracker.py
│   └── test_exporter.py
├── data/
├── outputs/
├── README.md
├── CLAUDE.md
├── requirements.txt
└── .env.example# NextMatch 
