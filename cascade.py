"""Two-stage cascade judge (cost-effective precision).

Cheap Haiku judges first. Only when Haiku lands in an uncertain band (default:
"low" -- right at the decision boundary) do we escalate to Sonnet, whose verdict
OVERRIDES Haiku's for that case. high/none stay on Haiku -- escalating confident
calls would just pay 20x for nothing.

The final verdict is cached under its OWN namespace (keyed by the escalation
policy), never mixed with the single-model caches -- so re-runs are free and the
intermediate Haiku/Sonnet verdicts stay separate.
"""
import cache
import config
import layer2

HAIKU = "claude-haiku-5-5"
SONNET = "claude-sonnet-5-5"


def cascade_judge(text, escalate=None, mode="real"):
    if escalate is None:
        escalate = config.CASCADE_ESCALATE
    escalate = tuple(escalate)
    policy = f"cascade:{HAIKU}->{SONNET}|esc={','.join(sorted(escalate))}"
    fkey = cache.key_for(policy, layer2.SYSTEM, text)
    hit = cache.get(fkey)
    if hit is not None:
        out = dict(hit)
        out["_usage"] = {"cost_usd": 0.0, "cached": True}
        return out

    haiku = layer2.judge(text, mode=mode, model=HAIKU)
    final, escalated = haiku, False
    if haiku.get("risk") in escalate:
        sonnet = layer2.judge(text, mode=mode, model=SONNET)
        if not str(sonnet.get("reasoning", "")).startswith("[error]"):
            final, escalated = sonnet, True   # boundary case: Sonnet is authoritative

    store = {k: v for k, v in final.items() if k != "_usage"}
    store["_escalated"] = escalated
    cache.put(fkey, store)
    out = dict(store)
    out["_usage"] = final.get("_usage", {})
    return out
