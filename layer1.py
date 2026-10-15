"""Layer 1: normalization pipeline + static detection. Cost: $0, fully offline.

The job of this layer is to defeat the cheap tricks that slip past a naive
regex: width/compatibility variants, invisible characters, look-alike glyphs,
and encoded payloads. Only AFTER cleaning do we run static signatures.
"""
import base64
import binascii
import re
import unicodedata

# Invisible / zero-width characters to physically delete before matching.
ZERO_WIDTH = dict.fromkeys(
    map(
        ord,
        [
            "​",  # zero width space
            "‌",  # zero width non-joiner
            "‍",  # zero width joiner
            "\u200E",  # LTR mark
            "\u200F",  # RTL mark
            "⁠",  # word joiner
            "﻿",  # zero width no-break space / BOM
            "­",  # soft hyphen
        ],
    ),
    None,
)

# Minimal homoglyph map: common Cyrillic / Greek look-alikes -> ASCII.
# (Not exhaustive; extend as you meet new evasions in the wild.)
HOMOGLYPHS = {
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x",
    "ѕ": "s", "і": "i", "ј": "j", "ԁ": "d", "ɡ": "g", "ո": "n",
    "А": "A", "Е": "E", "О": "O", "Р": "P", "С": "C", "Х": "X", "В": "B",
    "Н": "H", "К": "K", "М": "M", "Т": "T",
    "ο": "o", "ε": "e", "α": "a", "ρ": "p", "ν": "v", "τ": "t",
}


def _strip_homoglyphs(text):
    return "".join(HOMOGLYPHS.get(ch, ch) for ch in text)


def _decode_candidates(text):
    """Try to decode base64 / hex substrings; return any decoded plaintext."""
    found = []
    for m in re.findall(r"[A-Za-z0-9+/]{16,}={0,2}", text):
        try:
            dec = base64.b64decode(m, validate=True).decode("utf-8", "strict")
            if dec.isprintable():
                found.append(dec)
        except (binascii.Error, ValueError, UnicodeDecodeError):
            pass
    for m in re.findall(r"(?:[0-9a-fA-F]{2}){8,}", text):
        try:
            dec = bytes.fromhex(m).decode("utf-8", "strict")
            if dec.isprintable():
                found.append(dec)
        except (ValueError, UnicodeDecodeError):
            pass
    return found


def normalize(text):
    """NFKC -> strip zero-width -> fold homoglyphs. Returns cleaned text."""
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(ZERO_WIDTH)
    text = _strip_homoglyphs(text)
    return text


# Known prompt-injection signatures (matched case-insensitively).
# NOTE: some of these are deliberately broad (e.g. "system prompt") so the
# harness can SHOW you their false-positive cost. Tune them down using the
# measured FPR, don't just add more.
INJECTION_SIGNATURES = [
    r"ignore (all )?(the )?previous instructions",
    r"ignore all (provided |the )?(context|instructions)",
    r"ignore (the )?above",
    r"disregard (all )?(previous|prior)",
    r"forget (everything|all)\b",
    r"vergiss alles",            # German: "forget everything"
    r"olvid[ae] todo",           # Spanish: "forget everything"
    # "you are now" removed: it fired on benign personas ("you are now an expert
    # resume analyst"). Real "you are now DAN"-style jailbreaks are caught by the
    # judge (layer2) and by \bDAN\b / "developer mode". (gold-set finding)
    r"developer mode",
    r"\bDAN\b",
    r"reveal your (system )?prompt",
    r"print your instructions",
    r"repeat everything above",
    r"これまでの(指示|命令)を無視",
    r"命令を無視",
    r"システムプロンプト",
]

# PII / secret signatures. Credit cards are handled separately (Luhn) below so a
# plain 16-digit order/reference number doesn't trigger a false positive.
PII_SIGNATURES = {
    "mynumber": r"(?<!\d)\d{12}(?!\d)",                  # Japanese My Number (12 digits)
    "anthropic_key": r"sk-ant-[A-Za-z0-9_\-]{20,}",
    "openai_key": r"sk-[A-Za-z0-9]{20,}",
    "aws_key": r"AKIA[0-9A-Z]{16}",
}


def _luhn_ok(digits):
    """Luhn checksum: real card numbers pass, random digit runs almost never do."""
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _has_card_number(text):
    """True if text has a 13-19 digit run (spaces/hyphens allowed) passing Luhn."""
    for m in re.findall(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)", text):
        digits = re.sub(r"[ -]", "", m)
        if 13 <= len(digits) <= 19 and _luhn_ok(digits):
            return True
    return False


def static_scan(text):
    """Scan normalized text (+ any decoded payloads) for signatures."""
    haystacks = [text] + _decode_candidates(text)
    joined = "\n".join(haystacks)
    low = joined.lower()
    matched = []
    for pat in INJECTION_SIGNATURES:
        if re.search(pat, low, re.IGNORECASE):
            matched.append(["injection", pat])
    for name, pat in PII_SIGNATURES.items():
        if re.search(pat, joined):
            matched.append(["pii", name])
    if _has_card_number(joined):
        matched.append(["pii", "credit_card"])
    return matched, haystacks


def inspect(text):
    """Full Layer 1 pass. Returns a verdict dict."""
    normalized = normalize(text)
    matched, haystacks = static_scan(normalized)
    return {
        "layer": 1,
        "blocked": bool(matched),
        "matched": matched,
        "normalized_text": normalized,
        "decoded_payloads": haystacks[1:],
    }
