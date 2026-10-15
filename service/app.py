"""FastAPI HTTP layer for the AI-SPM gateway.

Run:  pip install fastapi uvicorn
      uvicorn service.app:app --host 127.0.0.1 --port 8000   # from the repo root

POST /check   {"input": "..."}  -> decision record
GET  /health                    -> ok + budget status
GET  /metrics                   -> counters, escalation rate, budget

The core logic (and all design decisions) live in gateway.py; this file is a thin
async wrapper so the detector can serve requests. ANTHROPIC_API_KEY must be set.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI          # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

import gateway                        # noqa: E402

app = FastAPI(title="AI-SPM gateway", version="0.1.0")


class CheckIn(BaseModel):
    input: str = Field(..., description="the user input to classify")


@app.post("/check")
def check(body: CheckIn):
    return gateway.check(body.input)


@app.get("/health")
def health():
    return {"status": "ok", "budget": gateway.budget_status()}


@app.get("/metrics")
def metrics():
    return gateway.metrics()
