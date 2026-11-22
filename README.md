# NextMatch

NextMatch is a Streamlit workspace for comparing job opportunities, tailoring application drafts, and tracking their progress. It connects each draft to the candidate’s evidence and requires validation and human approval before saving it.

[![Tests](https://github.com/ShirMamia/NextMatch/actions/workflows/tests.yml/badge.svg)](https://github.com/ShirMamia/NextMatch/actions/workflows/tests.yml)

## Try the sample

With Python 3.12, create and activate a virtual environment, then run:

```sh
python -m pip install -r requirements.txt
python -m streamlit run app/ui/main.py
```

Choose **Load sample profile and jobs** in the sidebar. Open **Tailoring Studio** to see the BI Analyst match and its skill evidence. In **Discover Jobs**, select the Data Engineer posting, then return to the studio to see the Airflow gap. The sample uses fictional records and runs locally without an API key.

## What you can do

- **Compare jobs.** Keep preference-based discovery ranking distinct from the candidate-to-job score. Inspect skill matches, scoring factors, and gaps.
- **Draft and review.** Parse CVs and job descriptions, generate a resume and cover letter against the original evidence, and inspect validation details before approving.
- **Track outcomes.** Manage application statuses and notes, inspect each application's event history, review dashboard metrics, and export applications and a summary to Excel.

## Architecture

```text
Streamlit → typed CV and job inputs → deterministic matching
                     ↓
        Anthropic-assisted drafting → evidence validation → manual approval
                                                                  ↓
                                             local tracker → dashboard / XLSX
```

`app/matching` computes fitness and evidence summaries. `app/generation`, `app/validation`, and `app/orchestration` handle drafting, review, and approval. `app/reporting` works through the file-backed repository to track applications and export results.

## Optional model-backed workflow

Copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY` to enable document parsing and draft generation. Those actions send the relevant input text to Anthropic. Keep credentials and personal CVs local. The app stores approved application data and exports locally in `data/` and `outputs/`, which are ignored by Git.

## Checks

```sh
python -m pytest tests -q
```

The suite covers parsers with mocked model responses, matching, validation, status transitions, reporting, and the Streamlit sample.
