\# NextMatch — Claude Code Working Guide



\## Project Identity

NextMatch is an interview-quality, production-oriented MVP for AI-assisted job discovery, truthful resume tailoring, and application management.



The product helps a user:

1\. Upload a master CV

2\. Parse the CV into a structured candidate profile

3\. Define one or more search profiles

4\. Discover and rank relevant jobs

5\. Parse a selected job into structured requirements

6\. Compute candidate-job fit

7\. Generate a tailored resume draft

8\. Generate a cover letter draft

9\. Validate all generated content against source evidence

10\. Save approved outputs into an application tracker

11\. View dashboard analytics across jobs and applications



This project is not an auto-apply bot.



This project is an evidence-grounded career copilot.



\---



\## Project Priorities

When tradeoffs exist, optimize in this order:



1\. Truthfulness

2\. Traceability

3\. Deterministic validation

4\. Clean architecture

5\. Interview-quality clarity

6\. Useful product flow

7\. Feature breadth



Do not sacrifice trustworthiness for flashier features.



\---



\## Product Philosophy

The strongest version of NextMatch is:

\- job discovery

\- structured job analysis

\- candidate-job matching

\- truthful resume tailoring

\- evidence mapping

\- validation

\- application tracking

\- dashboard analytics



The weakest version of NextMatch is:

\- aggressive auto-apply automation

\- brittle browser workflows

\- unsupported claim generation

\- uncontrolled scraping

\- overbuilt infrastructure with weak core logic



Do not optimize for the weak version.



\---



\## Core Truthfulness Rules

The system may:

\- reorder content

\- prioritize more relevant content

\- rewrite phrasing

\- shorten or refine bullets

\- improve targeting toward a job description

\- restructure resume sections for relevance



The system must not:

\- invent responsibilities

\- invent achievements

\- invent metrics

\- invent tools or technologies

\- inflate experience level

\- convert weak familiarity into strong expertise

\- add claims not grounded in the user's source material



Every tailored claim must be traceable to source evidence.



Human approval is required before any generated artifact is considered final.



\---



\## V1 Scope



\### In Scope

\- Master CV upload and parsing

\- Candidate profile creation

\- Search profile creation

\- Manual job ingestion

\- Structured job ingestion from safe sources

\- Job normalization

\- Job ranking

\- Job parsing

\- Candidate-job match scoring

\- Gap analysis

\- Tailored resume generation

\- Cover letter generation

\- Grounding validation

\- Application tracker

\- Dashboard analytics

\- Export of generated artifacts and records



\### Explicitly Out of Scope

\- Automatic external submission

\- Browser automation

\- CAPTCHA handling

\- ATS login automation

\- Multi-user authentication

\- Background workers

\- distributed queues

\- large-scale unrestricted scraping

\- fabricated claims

\- direct integration with restricted platforms through brittle automation



If a requested feature conflicts with V1 scope, preserve V1 discipline.



\---



\## Architecture Principles

1\. Prefer a modular monolith.

2\. Use strict Pydantic schemas for all major boundaries.

3\. Keep business logic out of Streamlit UI files.

4\. Treat all LLM outputs as untrusted until validated.

5\. Prefer deterministic logic when it is sufficient.

6\. Keep modules small, explicit, and single-purpose.

7\. Optimize for readability and explainability in interviews.

8\. Avoid premature infrastructure.

9\. Preserve auditability for tailored content.

10\. Build in slices, not in large uncontrolled jumps.



\---



\## Decision Rule: Deterministic First

Before using the LLM, ask whether the task can be done well enough with deterministic logic.



Prefer deterministic logic for:

\- validation

\- scoring formulas

\- filtering

\- deduplication

\- status handling

\- aggregation

\- dashboard metrics

\- repository and storage logic

\- schema normalization



Use the LLM mainly for:

\- parsing messy free text into structured fields

\- rewriting resume content

\- cover letter drafting

\- semantic matching support where deterministic rules alone are insufficient



Do not use the LLM for tasks that should remain deterministic and auditable.



\---



\## Data Model Expectations

Use Pydantic models for at least:

\- CandidateProfile

\- SearchProfile

\- JobPosting

\- MatchResult

\- TailoredBullet

\- TailoredResume

\- ValidationFlag

\- ApplicationRecord



Generated content must be structured before being consumed downstream.



If a schema is missing, define it before spreading ad hoc dictionaries through the codebase.



\---



\## Important Product Distinction

Maintain a clear separation between:



\### Search Profile Fit

How well a discovered job matches what the user says they want.



\### Candidate-Job Fit

How well the parsed candidate profile matches a specific job posting.



Do not collapse these into one score unless there is a very good reason.

If both are shown, label them clearly.



\---



\## Repo Structure Goals

The repository should be organized into modules such as:

\- ui

\- orchestration

\- parsers

\- discovery

\- matching

\- generation

\- validation

\- reporting

\- storage

\- schemas

\- services

\- tests



Responsibilities should remain clear and non-overlapping.



Avoid large files that combine parsing, business logic, UI handling, and persistence together.



\---



\## UI Expectations

Use Streamlit.



The UI should eventually support:

\- Candidate Profile page

\- Search Preferences page

\- Discovered Jobs page

\- Tailoring Studio page

\- Tracker page

\- Dashboard page



UI goals:

\- simple

\- demo-friendly

\- clear state transitions

\- easy inspection of generated output

\- explicit visibility of validation flags

\- explicit visibility of evidence mapping



Do not hide important review information behind overly clever UI abstractions.



\---



\## Output Expectations

Tailored outputs should include:

\- structured match analysis

\- tailored resume draft

\- cover letter draft

\- validation flags

\- evidence mapping

\- approval state



Generated outputs should be reviewable before being saved as approved artifacts.



\---



\## Validation Expectations

Validation must include checks such as:

\- unsupported claim detection

\- missing source evidence

\- duplicate or near-duplicate bullets

\- inconsistent claims

\- low-confidence tailored content

\- malformed structured output

\- empty or low-value generated content



Validation flags should be explicit, structured, and user-visible.



Prefer deterministic validation whenever possible.



\---



\## Storage and Persistence Expectations

For V1, prefer simple local persistence:

\- JSON artifacts

\- CSV or Excel tracker

\- optional SQLite if needed for clean structured storage



Do not introduce a heavier database or distributed architecture unless the current scope truly requires it.



Persistence logic should remain separate from UI and generation logic.



\---



\## Testing Expectations

Each slice should include focused tests where appropriate.



Prioritize tests for:

\- parsers

\- normalization logic

\- ranking logic

\- scoring logic

\- validation logic

\- tracker logic

\- exporter logic



Avoid overengineering tests for purely presentational Streamlit code.



If adding a module with meaningful logic, strongly prefer adding at least one focused test for it.



\---



\## Failure Behavior

When something is uncertain or malformed:

\- fail safely

\- return explicit flags

\- preserve partial structured output if safe

\- do not silently invent missing values

\- do not silently continue with broken assumptions



When assumptions are necessary:

\- choose practical assumptions

\- state them clearly

\- keep them local to the slice

\- do not rewrite the product vision around them



\---



\## Working Style

When implementing:

1\. First inspect the current repository state.

2\. Do not assume files exist unless they exist on disk.

3\. Do not rewrite large unrelated areas.

4\. Keep changes tightly scoped to the requested slice.

5\. Prefer explicit modules over mixed-responsibility files.

6\. Preserve import cleanliness and module boundaries.

7\. When in doubt, preserve truthfulness and validation over feature breadth.

8\. Do not rename or restructure major areas without a clear reason.

9\. Do not introduce hidden magic or unnecessary abstraction.



\---



\## Required Slice Discipline

Develop in slices.



For each slice:

1\. Re-state the exact scope

2\. Inspect current files relevant to the slice

3\. Confirm which relevant files already exist

4\. Implement only the requested modules

5\. Add or update focused tests

6\. Keep imports and architecture clean

7\. Summarize what was added

8\. Summarize what remains

9\. State any assumptions made



Do not jump ahead into later slices unless explicitly asked.



\---



\## Preferred Slice Order

A strong default order is:

1\. Foundations

2\. Candidate parsing

3\. Job parsing

4\. Matching

5\. Resume tailoring

6\. Validation

7\. Tracker

8\. Dashboard

9\. Job discovery

10\. Polish



If a different order is proposed, justify it clearly.



\---



\## Demo Standard

This project should always remain demoable.



A strong end-to-end demo should eventually show:

1\. Upload master CV

2\. Parse candidate profile

3\. Define search profile

4\. View discovered jobs

5\. Open one job

6\. Show match analysis

7\. Generate tailored resume

8\. Show evidence and validation flags

9\. Approve and save

10\. View tracker and dashboard



Design decisions should support this demo flow.



\---



\## Code Quality Standard

This repository should remain interview-quality:

\- clean architecture

\- realistic scope

\- strong tradeoff decisions

\- clear separation of concerns

\- explicit safeguards against hallucination

\- readable code

\- testable logic

\- minimal but professional UX



Do not try to make the project look larger by adding fragile or distracting features.



\---



\## What Claude Code Should Avoid

Do not:

\- assume success without checking outputs

\- add unsupported claims to generated content

\- overbuild infrastructure

\- mix UI logic with domain logic

\- create giant utility files that hide important behavior

\- introduce brittle automation as a shortcut

\- replace structured models with loose dictionaries everywhere

\- change project framing without being asked



\---



\## What a Good Response Looks Like

When asked to work on the project, prefer responses that are:

\- concrete

\- scoped

\- architecture-aware

\- explicit about assumptions

\- explicit about risks

\- practical for immediate implementation

\- aligned with the current repository state



Avoid vague advice when a concrete implementation decision is possible.

