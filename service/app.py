"""FastAPI HTTP layer for the AI-SPM gateway.

Run:  pip install fastapi uvicorn
      uvicorn service.app:app --host 127.0.0.1 --port 8000   # from the repo root

POST /check   {"input": "..."}   (optional header X-Client-Id)  -> decision record
GET  /health                     -> "ok" or "degraded" + budget status
GET  /metrics                    -> counters, escalation rate, budget

Core logic and all design decisions live in gateway.py. ANTHROPIC_API_KEY must be
set. X-Client-Id is NOT authentication -- it just labels traffic for per-client
monitoring and rate limiting (future). It must be an OPAQUE TOKEN (never PII -- no
emails/usernames): it is logged and shown in /metrics. Missing -> "anonymous".
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, Header        # noqa: E402
from pydantic import BaseModel, Field      # noqa: E402

import gateway                              # noqa: E402

app = FastAPI(title="AI-SPM gateway", version="0.2.0")


class CheckIn(BaseModel):
    # Raw-length cap at the HTTP boundary (B1 audit 1-6); gateway re-checks the
    # normalized length too.
    input: str = Field(..., max_length=gateway.MAX_INPUT_CHARS,
                       description="the user input to classify")


@app.post("/check")
def check(body: CheckIn, x_client_id: str = Header(default="anonymous")):
    return gateway.check(body.input, client_id=x_client_id or "anonymous")


@app.get("/health")
def health():
    return gateway.health()


@app.get("/metrics")
def metrics():
    return gateway.metrics()
