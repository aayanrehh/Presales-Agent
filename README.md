# AI Delivery & Presales Assistant

Production-oriented Streamlit MVP for converting RFP, SOW, and enterprise discovery text into validated presales artifacts:

- Scope and functional requirements
- RAID risk matrix
- QA strategy and staffing estimate
- Word briefing export
- PowerPoint pitch deck export

## Architecture

The app uses a decoupled multi-agent pipeline governed by hidden local protocol files:

1. `.engine_knowledge/skill.md` - orchestrator protocol and validation gates
2. `.engine_knowledge/agent_rfp.md` - scope extraction expert
3. `.engine_knowledge/agent_raid.md` - risk engineering expert
4. `.engine_knowledge/agent_qa.md` - QA architect and staffing estimator
5. `.engine_knowledge/templates/` - rigid markdown output templates

Each stage must pass Pydantic validation before the next stage executes. The current runtime uses a local keyless analysis engine, so no external model API key is required. If ingestion or schema validation fails, the app logs the exception to `app.log` and safely falls back to deterministic internal sample storage.

## Quick Start

Recommended path for most local installs:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python verify_requirements.py
.venv/bin/streamlit run app.py
```

Conda path if Python package resolution is inconsistent on your machine:

```bash
conda env create -f environment.yml
conda activate presales-agent
python verify_requirements.py
streamlit run app.py
```

## Tests

```bash
.venv/bin/python -m unittest discover -s tests
```

With Conda:

```bash
python -m unittest discover -s tests
```

## Local Setup Fallbacks

Use this order if someone cannot run the project locally:

1. Use `requirements.txt` with Python 3.12+ in a virtual environment.
2. Use `environment.yml` with Conda or Mamba if pip dependency resolution fails.
3. Recreate the virtual environment from scratch if Streamlit imports an old global package.
4. Add a Dockerfile only if the project needs fully identical environments across reviewers, demos, or cloud deployment.

## Production Notes

- No API keys are required for the current local analysis backend.
- `app.log` is ignored by git and records pipeline events and validation failures.
- TXT and Markdown ingestion are enabled now; PDF, DOCX, and OCR extraction slots are isolated for future extension.
- Word and PPTX exporters live in `utils.py`; a PDF export framework placeholder is also wired for expansion.
