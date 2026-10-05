"""BYOK gap notices. Never scrape logins. Never invent keys."""
from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Optional

# Official intake only. Env names, not values.
CATALOG: dict[str, dict] = {
    "Orbis (Moody's BvD)": {
        "env": ("ORBIS_API_KEY", "BVD_API_KEY"),
        "how": (
            "Umowa Moody's Bureau van Dijk (Orbis). "
            "Portal produktu: https://www.bvdinfo.com/en-gb/our-products/data/international/orbis . "
            "API live: https://api.bvdinfo.com (bez tokenu HTTP 401). "
            "Wklej ORBIS_API_KEY do /root/.behive_runtime.env (chmod 600)."
        ),
    },
    "LEX Wolters Kluwer": {
        "env": ("LEX_API_KEY", "WOLTERS_KLUWER_API_KEY"),
        "extra_env": ("LEX_API_BASE",),
        "how": (
            "Nie ma self-serve klucza. Oferta: pl-handel@wolterskluwer.com, tel. 22 535 88 00. "
            "sip.lex.pl to logowanie Borg, nie REST. api.lex.wolterskluwer.pl nie ma DNS. "
            "Po umowie: LEX_API_KEY i LEX_API_BASE w /root/.behive_runtime.env. Nie logować BeHive na SIP."
        ),
    },
    "Bisnode D&B": {
        "env": ("BISNODE_API_KEY", "DNB_API_KEY", "DNB_DIRECT_KEY"),
        "how": (
            "Umowa Dun & Bradstreet / Bisnode. "
            "API live: https://api.bisnode.com i https://plus.dnb.com (401 bez tokenu). "
            "Wklej BISNODE_API_KEY lub DNB_API_KEY do /root/.behive_runtime.env (chmod 600)."
        ),
    },
    "WTO Timeseries API": {
        "env": ("WTO_API_KEY", "WTO_TIMESERIES_KEY"),
        "how": (
            "Darmowy signup: https://apiportal.wto.org/signup . "
            "Documents Online (symbole/tytuły) działa bez klucza. Timeseries JSON wymaga subscription key. "
            "Wklej WTO_API_KEY do /root/.behive_runtime.env."
        ),
    },
    "OpenCorporates": {
        "env": ("OPENCORPORATES_API_KEY",),
        "how": (
            "Klucz z https://opencorporates.com/api_accounts/new . "
            "Wklej OPENCORPORATES_API_KEY do /root/.behive_runtime.env."
        ),
    },
}


def env_names(api_name: str) -> tuple[str, ...]:
    row = CATALOG.get(api_name) or {}
    return tuple(row.get("env") or ()) + tuple(row.get("extra_env") or ())


def has_key(api_name: str) -> bool:
    for k in (CATALOG.get(api_name) or {}).get("env") or ():
        if os.environ.get(k):
            return True
    return False


def status_list() -> list[dict]:
    out = []
    for name, row in CATALOG.items():
        present = [k for k in row["env"] if os.environ.get(k)]
        extra_missing = [k for k in (row.get("extra_env") or ()) if not os.environ.get(k)]
        out.append(
            {
                "api": name,
                "needed": list(row["env"]),
                "present": bool(present),
                "present_vars": present,
                "extra_needed": extra_missing,
                "how": row["how"],
            }
        )
    return out


def gap_doc(api: dict, topic: str = "") -> Optional[dict]:
    name = api.get("name") or ""
    row = CATALOG.get(name)
    if not row:
        needed = f"{name.upper().replace(' ', '_').replace('.', '_')}_API_KEY"
        how = f"Ustaw {needed} w /root/.behive_runtime.env (chmod 600). Oficjalny kontrakt vendora, nie logowanie BeHive."
        env = (needed,)
    else:
        env = row["env"]
        how = row["how"]
    env_s = " / ".join(env)
    extra = row.get("extra_env") if row else ()
    missing = [k for k in (extra or ()) if not os.environ.get(k)]
    missing_key = not any(os.environ.get(k) for k in env)
    if missing_key:
        missing = list(env) + missing
    extra_s = f" Dodatkowo: {', '.join(extra)}." if extra else ""
    text = (
        f"BeHive pominął {name}: brak konfiguracji ({', '.join(missing) or env_s}). "
        f"Temat: {topic or '(brak)'}. {how}{extra_s} "
        f"Bez klucza skip. BeHive nie loguje się na portal i nie zdobywa tokenu sam."
    )
    doc = {
        "source": f"api:{name}",
        "url": api.get("url") or "",
        "api_name": name,
        "category": api.get("category") or "company_data",
        "query_type": api.get("query_type") or "company_data",
        "endpoint_returns": "BYOK gap notice",
        "data": {
            "skipped": True,
            "reason": "missing_api_key" if missing_key else "missing_api_configuration",
            "missing": missing,
            "needed": list(env),
            "how": how,
        },
        "raw_text": text[:8000],
    }
    if os.environ.get("BEHIVE_BYOK_NOTIFICATIONS", "").lower() in {"1", "true", "yes"}:
        queue_discord(text, api_name=name)
        notify_discord(text, api_name=name)
    return doc


_NOTIFY_STATE = Path("/root/behive/data/byok_discord_notified.json")
_DEFAULT_CHANNEL = ""  # Notification destinations must be explicitly configured.
_COOLDOWN_S = 24 * 3600


def _discord_token() -> str:
    """Use explicitly supplied credentials, never another application's files."""
    return os.environ.get("BEHIVE_DISCORD_BOT_TOKEN") or os.environ.get("DISCORD_BOT_TOKEN") or ""


def _channel_id() -> str:
    return (
        os.environ.get("BEHIVE_DISCORD_CHANNEL_ID")
        or os.environ.get("DISCORD_HOME_CHANNEL")
        or _DEFAULT_CHANNEL
    )


def notify_discord(text: str, api_name: str = "") -> bool:
    """Post gap notice to Discord. Best-effort. Cooldown 24h per API. Never send secrets."""
    token = _discord_token()
    channel = _channel_id()
    if not token or not channel or not text:
        return False
    now = time.time()
    state = {}
    if _NOTIFY_STATE.exists():
        try:
            state = json.loads(_NOTIFY_STATE.read_text())
        except Exception:
            state = {}
    key = api_name or "generic"
    last = float(state.get(key) or 0)
    if now - last < _COOLDOWN_S:
        return False
    body = json.dumps({"content": text[:1800]}).encode()
    req = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{channel}/messages",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            ok = 200 <= r.status < 300
    except Exception:
        return False
    if ok:
        _NOTIFY_STATE.parent.mkdir(parents=True, exist_ok=True)
        state[key] = now
        _NOTIFY_STATE.write_text(json.dumps(state))
    return ok


_QUEUE = Path("/root/behive/data/byok_discord_queue.jsonl")


def queue_discord(text: str, api_name: str = "") -> None:
    """Hermes cron drains this to the Discord thread. REST from this host is CF 1010."""
    if not text:
        return
    _QUEUE.parent.mkdir(parents=True, exist_ok=True)
    rec = {"api": api_name, "text": text[:1800], "ts": time.time()}
    with _QUEUE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def drain_discord_queue() -> str:
    """Return queued notices (dedupe by api). Empty string if nothing."""
    if not _QUEUE.exists():
        return ""
    lines = _QUEUE.read_text(encoding="utf-8").splitlines()
    _QUEUE.write_text("")
    seen = set()
    out = []
    for line in lines:
        try:
            rec = json.loads(line)
        except Exception:
            continue
        api = rec.get("api") or ""
        if api in seen:
            continue
        seen.add(api)
        t = (rec.get("text") or "").strip()
        if t:
            out.append(t)
    return "\n\n".join(out)
