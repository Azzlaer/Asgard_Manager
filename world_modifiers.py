from __future__ import annotations

import shlex


MODIFIER_KEYS = ["combat", "resources", "portals", "raids", "deathpenalty"]
OFFICIAL_TOGGLE_KEYS = ["nobuildcost", "playerevents", "passivemobs", "nomap"]
ADVANCED_TOGGLE_KEYS = ["fire", "noportals", "nobossportals", "noworkbench", "nocraftcost"]


def _tokens(parameters: str) -> list[str]:
    try:
        return shlex.split(parameters or "", posix=False)
    except ValueError:
        return (parameters or "").split()


def _clean(value: str) -> str:
    return value.strip().strip('"')


def parse_parameters(parameters: str) -> dict:
    tokens = _tokens(parameters)
    result = {
        "preset": "",
        "combat": "",
        "resources": "",
        "portals": "",
        "raids": "",
        "deathpenalty": "",
        "setkeys": [],
    }
    i = 0
    while i < len(tokens):
        token = tokens[i].lower()
        if token == "-preset" and i + 1 < len(tokens):
            result["preset"] = _clean(tokens[i + 1]).lower()
            i += 2
        elif token == "-modifier" and i + 2 < len(tokens):
            key = _clean(tokens[i + 1]).lower()
            value = _clean(tokens[i + 2]).lower()
            if key in MODIFIER_KEYS:
                result[key] = value
            i += 3
        elif token == "-setkey" and i + 1 < len(tokens):
            value = _clean(tokens[i + 1])
            # shlex(posix=False) puede dividir un valor con espacios cuando la
            # configuración antigua no tenía comillas. Conservamos el caso útil
            # de claves parametrizadas, por ejemplo EventRate 100.
            if i + 2 < len(tokens) and not tokens[i + 2].startswith("-") and " " not in value:
                candidate = f"{value} {_clean(tokens[i + 2])}"
                if value.lower() in {
                    "eventrate", "resourcerate", "enemydamagerate", "enemyhealthrate",
                    "enemyspeedsize", "movesstaminarate", "movestaminarate",
                    "staminarate", "staminaregenrate", "skillgainrate",
                    "skillreductionrate", "playerdamage", "worldlevel",
                }:
                    value = candidate
                    i += 1
            result["setkeys"].append(value)
            i += 2
        else:
            i += 1
    return result


def _quote_if_needed(value: str) -> str:
    value = value.strip()
    if not value:
        return value
    if any(ch.isspace() for ch in value) or '"' in value:
        return '"' + value.replace('"', '\\"') + '"'
    return value


def apply_modifiers(parameters: str, values: dict) -> str:
    tokens = _tokens(parameters)
    output: list[str] = []
    i = 0
    while i < len(tokens):
        token = tokens[i].lower()
        if token == "-preset" and i + 1 < len(tokens):
            i += 2
            continue
        if token == "-modifier" and i + 2 < len(tokens):
            if _clean(tokens[i + 1]).lower() in MODIFIER_KEYS:
                i += 3
                continue
        if token == "-setkey" and i + 1 < len(tokens):
            i += 2
            # Descarta el segundo token de claves parametrizadas sin comillas.
            if i < len(tokens) and not tokens[i].startswith("-"):
                previous = _clean(tokens[i - 1]).lower()
                if previous in {"eventrate", "resourcerate", "worldlevel"}:
                    i += 1
            continue
        output.append(tokens[i])
        i += 1

    preset = str(values.get("preset", "")).strip().lower()
    if preset:
        output += ["-preset", preset]

    for key in MODIFIER_KEYS:
        value = str(values.get(key, "")).strip().lower()
        if value:
            output += ["-modifier", key, value]

    seen = set()
    for key in values.get("setkeys", []):
        clean = str(key).strip()
        if not clean:
            continue
        marker = clean.lower()
        if marker in seen:
            continue
        seen.add(marker)
        output += ["-setkey", _quote_if_needed(clean)]

    return " ".join(output)
