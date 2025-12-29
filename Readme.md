Backend service for scanning stock market announcements, classifying events, and preparing trading signals using LLM-powered analysis and structured workflows.

## Setup (pip)

1. Create and activate a virtual environment: `python3 -m venv .venv && source .venv/bin/activate`
2. Install dependencies: `pip install -r requirements.txt`
3. Run database/init scripts as needed (see SETUP_GUIDE.md) before starting the pipeline.

## Setup (uv)

1. Ensure uv is installed: `pip install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`
2. Install dependencies into an isolated environment: `uv venv .venv && source .venv/bin/activate && uv pip install -r requirements.txt`
3. Proceed with environment configuration and data ingest per SETUP_GUIDE.md.
