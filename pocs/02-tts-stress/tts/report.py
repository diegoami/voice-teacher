"""Summarise the listener's verdicts per variant and per item."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from .items import VARIANTS


def report(out: Path) -> str:
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    path = out / "verdicts.json"
    verdicts = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    items = {i["number"]: i for i in manifest["items"]}
    clips = manifest["clips"]
    names = [v.name for v in VARIANTS if any(c["variant"] == v.name for c in clips.values())]

    rows = []
    per_item: dict[int, dict[str, str]] = defaultdict(dict)
    for name in names:
        mine = [c for c in clips.values() if c["variant"] == name]
        counts = {"right": 0, "wrong": 0, "unclear": 0}
        targets = wrong_targets = other = 0
        for clip in mine:
            v = verdicts.get(f"{clip['item']}/{name}")
            if not v:
                per_item[clip["item"]][name] = "–"
                continue
            counts[v["verdict"]] += 1
            item_targets = items[clip["item"]]["targets"]
            if v["verdict"] != "unclear":
                targets += len(item_targets)
            if v["verdict"] == "wrong":
                wrong_targets += len(v.get("wrong", []))
                other += bool(v.get("other"))
                per_item[clip["item"]][name] = "✗ " + ", ".join(v.get("wrong", []) + (["other"] if v.get("other") else []))
            else:
                per_item[clip["item"]][name] = "✓" if v["verdict"] == "right" else "?"
        judged = sum(counts.values())
        seconds = sorted(c["seconds"] for c in mine)
        rows.append(
            f"| {name} | {mine[0]['model']} | {counts['right']}/{judged} | {counts['wrong']} | "
            f"{counts['unclear']} | {wrong_targets}/{targets} | {other} | "
            f"{seconds[len(seconds) // 2]} s | {sum(c['characters'] for c in mine)} |")

    judged_all = sum(1 for k in clips if k in verdicts)
    lines = [
        "# TTS stress — listening report",
        "",
        f"{judged_all} of {len(clips)} clips judged, blind (variants in random order per item).",
        "",
        "| Variant | Model | Clips all right | Wrong | Unclear | Target words wrong | Other word wrong "
        "| Median request time | Characters |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        *rows,
        "",
        "## Per item",
        "",
        "| # | Sentence | " + " | ".join(names) + " |",
        "| --- | --- |" + " --- |" * len(names),
    ]
    for number in sorted(items):
        lines.append(f"| {number} | {items[number]['marked']} | "
                     + " | ".join(per_item[number].get(n, "–") for n in names) + " |")
    notes = [(k, v["note"]) for k, v in verdicts.items() if v.get("note")]
    if notes:
        lines += ["", "## Notes", ""] + [f"- {k}: {note}" for k, note in sorted(notes)]
    return "\n".join(lines) + "\n"
