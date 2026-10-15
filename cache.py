"""On-disk verdict cache so real-mode re-runs don't re-pay for unchanged inputs.

Keyed by (model, system, normalized_text). A cache hit costs nothing; only new
or changed inputs hit the API. This is what makes iterative tuning on hundreds
or thousands of cases affordable: tweak a layer1 rule, re-run, and only the
inputs that now reach layer2 for the first time cost money.
"""
import hashlib
import json

from config import REPORT_DIR

CACHE_FILE = REPORT_DIR / "verdict_cache.json"
_cache = None
_dirty = False


def _load():
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            _cache = {}
    return _cache


def key_for(model, system, text):
    h = hashlib.sha256()
    for part in (model or "", system or "", text or ""):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def get(key):
    return _load().get(key)


def put(key, verdict):
    global _dirty
    _load()[key] = verdict
    _dirty = True


def save():
    if _cache is None or not _dirty:
        return
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(_cache, ensure_ascii=False), encoding="utf-8")
