# Sales/Tech RAG Agent (Local, No Docker)

Production-ready RAG service on FastAPI for sales and technical teams.

- No Docker required
- No OpenAI key required
- Local HuggingFace model (GGUF via `llama.cpp`)
- CPU-only
- Answers only from uploaded docs with mandatory citations

## 1) Quick Start (Windows PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env -Force
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

First LLM request auto-downloads model:

- Repo: `bartowski/Qwen2.5-7B-Instruct-GGUF`
- File: `Qwen2.5-7B-Instruct-Q4_K_M.gguf`
- Saved to `./models/`

## 2) Local Infrastructure

Qdrant runs in embedded local mode (file-based):

- Path from `.env`: `QDRANT_PATH=./data/qdrant`
- No external DB server/container required

## 3) API

### Health

```bash
GET /health
```

### Upload document

```bash
POST /documents/upload
multipart/form-data:
  file=<pdf|docx|xlsx>
  version=<v1|v2|...>
```

Example:

```bash
curl -X POST "http://localhost:8000/documents/upload" \
  -F "file=@./samples/Product_Manual.pdf" \
  -F "version=v1"
```

### Ask

```bash
POST /ask
Content-Type: application/json
```

Body:

```json
{
  "question": "Какие ограничения SLA указаны для техподдержки?",
  "type": "technical",
  "version": "v1"
}
```

## 4) Key Features

- Strict RAG prompt: generation only from retrieved context
- Similarity threshold gate (`SIMILARITY_THRESHOLD`)
- Refusal on no/low relevance:
  - `В базе знаний отсутствуют релевантные данные.`
- Citation enforcement and post-validation
- JSON logging for requests, latency, docs, confidence, token usage, errors
- Document versioning metadata + soft delete endpoint

## 5) Test

```powershell
python -m pytest -q
```

## 6) Minimal RAM Guidance

- API process + embeddings: from 16 GB RAM
- Local 7B GGUF inference: recommended 24-32 GB RAM

## 7) Project Layout

```text
app/
  api/
  core/
  rag/
  ingestion/
  models/
  logging/
  config/
  services/
tests/
requirements.txt
README.md
```
