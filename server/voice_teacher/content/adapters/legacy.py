"""Deterministic adapter for the retained /voice-prepare package format.

The parsing conventions come from POC5's engine/package.py. Identity comes
from an explicit mapping; reviewed POC lesson JSON supplies targets. Neither
source nor preparation code is executed, and private context has its own output.
"""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

from schemas.validate import canonical_json, validate_curriculum
from ...practice.models import Lesson
from ...practice.text import plain


class LegacyError(ValueError):
    pass


def _fail(where, message):
    raise LegacyError(f"{where}: {message}")


def _keys(value, names, where):
    if not isinstance(value, dict) or set(value) != set(names.split()):
        _fail(where, "unexpected or missing mapping fields")


def _id(value, where):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", value):
        _fail(where, "invalid stable identity")
    return value


def _text(value, where):
    if not isinstance(value, str) or not value.strip():
        _fail(where, "nonempty text required")
    return value


def _list(value, where, *, nonempty=False):
    if not isinstance(value, list) or (nonempty and not value):
        _fail(where, "expected a nonempty list" if nonempty else "expected a list")
    return value


def _field(text, name):
    matches = re.findall(rf"^{re.escape(name)}:[ \t]*(.*)$", text, re.M)
    if len(matches) != 1:
        _fail("package.md", f"expected one {name}: field")
    return matches[0].strip()


def _block(text, start, end):
    match = re.search(rf"^{re.escape(start)}[^\n]*\n(.*?)^{re.escape(end)}", text, re.M | re.S)
    if not match:
        _fail("package.md", f"missing {start} ... {end} section")
    return match.group(1)


def _numbered(text, where, *, wrapped=True):
    rows, numbers = [], []
    for line in text.splitlines():
        match = re.match(r"^(\d+)\.\s+(.*)", line)
        if match:
            numbers.append(int(match[1])); rows.append(match[2].strip())
        elif wrapped and rows and line.strip():
            rows[-1] += " " + line.strip()
    if numbers != list(range(1, len(rows) + 1)) or not rows:
        _fail(where, "numbered rows must be contiguous from one")
    return rows


def _parse(text, folder):
    markers = list(re.finditer(r"^SESSION_BRIEF[ \t]*$", text, re.M))
    if len(markers) != 1:
        _fail("package.md", "expected one SESSION_BRIEF marker")
    brief = text[markers[0].end():]
    declared = re.search(r"^Opening review \((\d+) lines\):", brief, re.M)
    opening = _numbered(_block(brief, "Opening review", "Active phrase set:"), "opening", wrapped=False)
    if not declared or int(declared[1]) != len(opening):
        _fail("opening", "declared line count does not match numbered lines")
    guided = _block(brief, "Guided sequence:", "Delayed recall:")
    first = re.search(r"^\d+\.\s", guided, re.M)
    if first is None:
        _fail("guided", "at least one numbered step is required")
    steps = []
    for number, row in enumerate(_numbered(guided[first.start():], "guided"), 1):
        match = re.match(r"^(.*?)\b(?:[Ss]ay|[Aa]sk) «([^»]+)»\s*(.*)$", row, re.S)
        if match is None:
            _fail(f"guided[{number}]", "missing Say/Ask «teacher line»")
        wait = re.search(r"\bWait for (?:the learner|him|her) to\s+|\bThe learner\s+", match[3])
        if wait is None:
            _fail(f"guided[{number}]", "missing expected learner action")
        setting = " ".join(p for p in [match[1].strip().rstrip(":").strip(), match[3][:wait.start()].strip()] if p)
        steps.append({"number": number, "teacher_line": match[2].strip(),
                      "expected": match[3][wait.end():].strip().rstrip("."), "setting": setting})
    recalls = [m[1].strip() for m in re.finditer(r"^-\s+(.*)$", _block(brief, "Delayed recall:", "Earlier weak expressions included:"), re.M)]
    if not recalls or any(not p for p in recalls):
        _fail("recall", "at least one nonempty prompt is required")
    part, sep, title = _field(brief, "Lesson part").partition("—")
    if not sep or not part.strip() or not title.strip():
        _fail("Lesson part", "expected part — title")
    return {"source": folder, "part": part.strip(), "title": title.strip(), "learner": _field(brief, "Learner"),
            "main_goal": _field(brief, "Main goal"),
            "introduction": " ".join(_block(brief, "Teacher introduction:", "Opening review").split()),
            "opening": opening, "active_phrases": [m[1].strip() for m in re.finditer(r"^-\s+(.*)$", _block(brief, "Active phrase set:", "Guided sequence:"), re.M)],
            "weak_expressions": [m[1].strip() for m in re.finditer(r"^-\s+(.*)$", _block(brief, "Earlier weak expressions included:", "Source:"), re.M)],
            "scenario": " ".join(guided[:first.start()].split()), "steps": steps,
            "recall": [{"number": n, "prompt": p} for n, p in enumerate(recalls, 1)]}


@dataclass
class AdaptedCatalogue:
    curriculum: dict
    session_inputs: dict
    input_hashes: dict

    def prepared_lesson(self, course_id, lesson_id):
        """Private runtime input, not a public catalogue response."""
        try:
            return Lesson.from_dict(deepcopy(self.session_inputs[(course_id, lesson_id)]["lesson"]))
        except KeyError:
            raise LegacyError("unknown course/lesson mapping") from None


class LegacyAdapter:
    def __init__(self, mapping, *, max_bytes=4 * 1024 * 1024):
        self.mapping = json.loads(canonical_json(mapping))
        _keys(self.mapping, "format_version source_id title courses", "mapping")
        if type(self.mapping["format_version"]) is not int or self.mapping["format_version"] != 1:
            _fail("mapping", "unsupported mapping version")
        _id(self.mapping["source_id"], "source_id")
        _text(self.mapping["title"], "title")
        _list(self.mapping["courses"], "courses", nonempty=True)
        if type(max_bytes) is not int or max_bytes < 1:
            _fail("max_bytes", "positive byte limit required")
        self.max_bytes = max_bytes

    def _read(self, root, relative, expected, hashes):
        if not isinstance(relative, str) or not relative or "\0" in relative or "\\" in relative or PurePosixPath(relative).is_absolute() or ".." in PurePosixPath(relative).parts:
            _fail("path", "expected a relative path inside the configured source root")
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            _fail("path", "missing source file or path escapes configured root")
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            _fail("mapping", "explicit reviewed SHA-256 required for every input")
        try:
            with path.open("rb") as f:
                value = f.read(self.max_bytes + 1)
            if len(value) > self.max_bytes:
                _fail("input", "file exceeds configured byte limit")
            actual = hashlib.sha256(value).hexdigest()
            if actual != expected:
                _fail("preparation", "input hash changed; explicitly prepare/review targets and update the mapping before activation")
            hashes[relative] = actual
            return value.decode("utf-8").replace("\r\n", "\n")
        except (OSError, UnicodeError):
            _fail("input", "cannot read UTF-8 source material")

    def load(self, root, *, source_id):
        root = Path(root).resolve()
        if source_id != self.mapping["source_id"]:
            _fail("source_id", "unknown source mapping; register an explicit namespace")
        result = AdaptedCatalogue({"schema_version": 1, "kind": "curriculum", "source_id": source_id,
                                   "title": self.mapping["title"], "courses": []}, {}, {})
        private_learners = set()
        for course in self.mapping["courses"]:
            _keys(course, "course_id title language instruction_language items lessons", "course")
            cid = _id(course["course_id"], "course_id")
            if (course["language"], course["instruction_language"]) != ("uk", "en"):
                _fail("course", "this legacy format is uk/en; use a reviewed language adapter for another pair")
            definitions = {}
            for item in _list(course["items"], "items", nonempty=True):
                _keys(item, "item_id item_revision meaning speech_sha256", "item")
                identity = _id(item["item_id"], "item_id")
                if identity in definitions: _fail("items", "duplicate item mapping")
                if type(item["item_revision"]) is not int or item["item_revision"] < 1:
                    _fail("item_revision", "positive revision required")
                _text(item["meaning"], "meaning")
                definitions[identity] = item
            compiled = {k: course[k] for k in ["course_id", "title", "language", "instruction_language"]}
            compiled.update(items=[], lessons=[])
            bound = {}
            def bind(ids, texts, where):
                _list(ids, where)
                if len(ids) != len(texts): _fail(where, "identity count does not match renderings")
                for identity, text in zip(ids, texts):
                    _id(identity, where)
                    _text(text, where)
                    if identity not in definitions: _fail(where, "unknown item mapping")
                    definition = definitions[identity]
                    if hashlib.sha256(text.encode()).hexdigest() != definition["speech_sha256"]:
                        _fail(where, "item rendering hash changed; review its identity/revision mapping")
                    value = {"item_id": identity, "item_revision": definition["item_revision"],
                             "text": {"display": plain(text), "speech": text}, "meaning": definition["meaning"]}
                    if identity in bound and bound[identity] != value:
                        _fail(where, "one item identity cannot name different renderings")
                    bound[identity] = value
            for lesson in _list(course["lessons"], "lessons", nonempty=True):
                _keys(lesson, "lesson_id title legacy_part package prepared package_sha256 prepared_sha256 opening_item_ids steps recall topic", "lesson mapping")
                lid = _id(lesson["lesson_id"], "lesson_id")
                package = PurePosixPath(_text(lesson["package"], "package path"))
                text = self._read(root, str(package / "package.md"), lesson["package_sha256"], result.input_hashes)
                parsed = _parse(text, (root / str(package)).name)
                if parsed["learner"]: private_learners.add(parsed["learner"])
                if parsed["part"] != lesson["legacy_part"]: _fail("legacy_part", "package part does not match explicit lesson mapping")
                prepared_text = self._read(root, lesson["prepared"], lesson["prepared_sha256"], result.input_hashes)
                try:
                    prepared = json.loads(prepared_text)["lesson"]
                except (ValueError, TypeError, KeyError):
                    _fail("prepared", "expected explicitly prepared POC lesson JSON with a lesson object")
                if not isinstance(prepared, dict): _fail("prepared", "expected a lesson object")
                for key in ["source", "part", "title", "learner", "main_goal", "introduction", "opening", "active_phrases", "weak_expressions", "scenario"]:
                    if prepared.get(key) != parsed[key]: _fail("prepared", f"stale {key} field; explicitly prepare and review this package")
                bind(lesson["opening_item_ids"], parsed["opening"], "opening_item_ids")
                native = {"source_id": source_id, "course_id": cid, "lesson_id": lid, "title": lesson["title"],
                          "introduction": parsed["introduction"], "opening": parsed["opening"], "opening_item_ids": lesson["opening_item_ids"], "steps": [], "recall": []}
                public = {"lesson_id": lid, "title": lesson["title"], "modes": ["repetition", "guided_conversation"],
                          "repetition_item_ids": list(dict.fromkeys(lesson["opening_item_ids"])), "guided_steps": [], "recall_goals": [], "topic": lesson["topic"]}
                if lesson["topic"] is not None: public["modes"].append("free_conversation")
                for section, identity_key, public_key in [("steps", "step_id", "guided_steps"), ("recall", "goal_id", "recall_goals")]:
                    rows = _list(prepared.get(section), f"prepared.{section}", nonempty=True)
                    mappings = _list(lesson[section], f"mapping.{section}", nonempty=True)
                    if len(rows) != len(parsed[section]) or len(rows) != len(mappings):
                        _fail(section, "prepared/mapped row counts do not match package")
                    for number, (row, authored, slot) in enumerate(zip(rows, parsed[section], mappings), 1):
                        _keys(slot, f"number {identity_key} target_item_ids", f"mapping.{section}")
                        if not isinstance(row, dict) or type(slot["number"]) is not int or slot["number"] != number or type(row.get("number")) is not int or row["number"] != number:
                            _fail(section, "prepared/mapped numbering must match the package")
                        for key, value in authored.items():
                            if row.get(key) != value: _fail(section, "prepared teacher/task differs from the current package")
                        if not row.get("targets"):
                            _fail(f"prepared.{section}.targets", "reviewed targets missing; explicitly prepare this lesson before activation")
                        targets = _list(row.get("targets"), f"{section}.targets", nonempty=True)
                        if len(targets) > 3: _fail(section, "legacy targets require one to three reviewed renderings")
                        identity = _id(slot[identity_key], identity_key)
                        bind(slot["target_item_ids"], targets, f"{section}.target_item_ids")
                        entry = {**authored, identity_key: identity, "targets": targets, "target_item_ids": slot["target_item_ids"]}
                        if section == "steps":
                            if type(row.get("open_answer")) is not bool: _fail("steps.open_answer", "explicit boolean required")
                            entry["open_answer"] = row["open_answer"]
                            public[public_key].append({"step_id": identity, "teacher": {"speech": authored["teacher_line"], "display": plain(authored["teacher_line"])},
                                "goal": authored["expected"], "target_item_ids": slot["target_item_ids"], "open_answer": row["open_answer"]})
                            for item in slot["target_item_ids"]:
                                if item not in public["repetition_item_ids"]: public["repetition_item_ids"].append(item)
                        else:
                            public[public_key].append({"goal_id": identity, "prompt": {"speech": authored["prompt"], "display": plain(authored["prompt"])}, "target_item_ids": slot["target_item_ids"]})
                        native[section].append(entry)
                prepared_lesson = Lesson.from_dict(native)
                result.session_inputs[(cid, lid)] = {"lesson": prepared_lesson.to_dict(), "legacy_context": {
                    key: parsed[key] for key in ["learner", "main_goal", "active_phrases", "weak_expressions", "scenario"]}}
                compiled["lessons"].append(public)
            if set(bound) != set(definitions): _fail("items", "every mapped item must have a referenced rendering")
            compiled["items"] = [bound[i["item_id"]] for i in course["items"]]
            result.curriculum["courses"].append(compiled)
        validate_curriculum(result.curriculum)
        def strings(value):
            if isinstance(value, str): yield value
            elif isinstance(value, dict):
                for child in value.values(): yield from strings(child)
            elif isinstance(value, list):
                for child in value: yield from strings(child)
        if any(learner in text for text in strings(result.curriculum) for learner in private_learners):
            _fail("privacy", "learner description appears in reusable material; use separately reviewed reusable content")
        return deepcopy(result)
