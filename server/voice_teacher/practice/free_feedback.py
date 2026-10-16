"""Post-attempt claim validation. Model wording never creates a turn or mastery."""
from copy import deepcopy
import unicodedata

from schemas.validate import canonical_json
from ..providers.dialogue import provider_identity
from ..storage.sqlite import _id


def _text(value, limit):
    return isinstance(value,str) and bool(value.strip()) and len(value)<=limit


def validate_context(context):
    if not isinstance(context,dict) or set(context)!={"language","instruction_language","turn","items","recognition_uncertain"}:
        raise ValueError("invalid feedback context")
    turn=context["turn"]
    if not isinstance(turn,dict) or set(turn)!={"turn_id","text"}:raise ValueError("invalid feedback turn")
    _id(turn["turn_id"])
    if not _text(turn["text"],8000) or type(context["recognition_uncertain"]) is not bool:raise ValueError("invalid feedback input")
    if not all(_text(context[k],32) for k in ("language","instruction_language")):raise ValueError("invalid feedback language")
    if not isinstance(context["items"],list) or len(context["items"])>6:raise ValueError("feedback item budget exceeded")
    seen=set()
    for item in context["items"]:
        if not isinstance(item,dict) or set(item)!={"item_id","display","speech","meaning"}:raise ValueError("invalid feedback item")
        _id(item["item_id"])
        if item["item_id"] in seen or not all(_text(item[k],1200) for k in ("display","speech","meaning")):raise ValueError("invalid feedback item text")
        seen.add(item["item_id"])
    if len(canonical_json(context).encode())>64*1024:raise ValueError("feedback context budget exceeded")


def _plain(value):
    return " ".join(unicodedata.normalize("NFC",value.replace("\u0301","")).casefold().split())


def validate_response(context,value):
    validate_context(context)
    if not isinstance(value,dict) or set(value)!={"observations"} or not isinstance(value["observations"],list) or len(value["observations"])>3:
        raise ValueError("invalid feedback response")
    items={i["item_id"]:i for i in context["items"]};seen=set()
    for row in value["observations"]:
        if not isinstance(row,dict) or set(row)!={"turn_id","original","preferred","reason","item_id"}:
            raise ValueError("invalid feedback claim fields")
        if row["turn_id"]!=context["turn"]["turn_id"] or not _text(row["original"],8000) or row["original"] not in context["turn"]["text"]:
            raise ValueError("feedback must quote the actual accepted learner turn")
        if (row["preferred"] is None)!=(row["reason"] is None):raise ValueError("corrections need both preferred wording and a reason")
        if row["preferred"] is not None:
            if not _text(row["preferred"],500) or not _text(row["reason"],500) or _plain(row["preferred"])==_plain(row["original"]):
                raise ValueError("unsupported correction shape")
        item_id=row["item_id"]
        if item_id is not None:
            if not isinstance(item_id,str) or item_id not in items:raise ValueError("unknown feedback item")
            renderings={_plain(items[item_id][k]) for k in ("display","speech")}
            if not any(_plain(text) in renderings for text in (row["original"],row["preferred"]) if text is not None):
                raise ValueError("item attribution has no explicit matching rendering")
            matches={i["item_id"] for i in items.values() if any(_plain(text)==_plain(i[k]) for k in ("display","speech") for text in (row["original"],row["preferred"]) if text is not None)}
            if matches!={item_id}:raise ValueError("ambiguous feedback item attribution")
        identity=canonical_json(row)
        if identity in seen:raise ValueError("duplicate feedback claim")
        seen.add(identity)
    return deepcopy(value)


def new_state(identity):
    return {"format_version":1,"provider":provider_identity(identity),"observations":[],"published":[],"review_targets":[]}


def context_for(snapshot,turn):
    items=[]
    if snapshot["source"] is not None:
        course=next(c for c in snapshot["curriculum_snapshot"]["courses"] if c["course_id"]==snapshot["source"]["course_id"])
        lesson=next(l for l in course["lessons"] if l["lesson_id"]==snapshot["source"]["lesson_id"])
        selected=set(lesson["repetition_item_ids"])
        for step in lesson["guided_steps"]:selected.update(step["target_item_ids"])
        for item in course["items"]:
            if selected and item["item_id"] not in selected:continue
            value={"item_id":item["item_id"],"display":item["text"]["display"],"speech":item["text"]["speech"],"meaning":item["meaning"]}
            if all(_text(value[k],1200) for k in ("display","speech","meaning")):items.append(value)
            if len(items)==6:break
    reports=snapshot["engine_state"]["data"].get("recognition_reports",{})
    uncertain=any(r.get("origin_turn_id")==turn["turn_id"] for r in reports.values())
    value={"language":snapshot["language"],"instruction_language":snapshot["instruction_language"],"turn":{"turn_id":turn["turn_id"],"text":turn["text"]},"items":items,"recognition_uncertain":uncertain}
    validate_context(value);return value


def checked_state(value,snapshot,turns):
    if not isinstance(value,dict) or set(value)!={"format_version","provider","observations","published","review_targets"} or type(value["format_version"]) is not int or value["format_version"]!=1:
        raise ValueError("unsupported free feedback state")
    provider_identity(value["provider"])
    if not isinstance(value["observations"],list) or len(value["observations"])>90:raise ValueError("feedback ledger budget exceeded")
    seen=set();accepted={t["turn_id"]:t for t in turns if t["role"]=="learner"}
    for row in value["observations"]:
        if not isinstance(row,dict) or set(row)!={"event_id","turn","assistance","claim","uncertain"}:raise ValueError("invalid saved feedback observation")
        _id(row["event_id"])
        if row["event_id"] in seen or row["turn"]!=accepted.get(row["turn"]["turn_id"]):raise ValueError("saved feedback has no matching accepted turn")
        if row["assistance"]!={"kind":"none","help_level":0,"target_exposed":False} or type(row["uncertain"]) is not bool:raise ValueError("invalid free observation assistance")
        validate_response(context_for(snapshot,row["turn"]),{"observations":[row["claim"]]})
        seen.add(row["event_id"])
    if not isinstance(value["published"],list) or any(not isinstance(k,str) or k not in seen for k in value["published"]) or len(set(value["published"]))!=len(value["published"]):raise ValueError("invalid published feedback IDs")
    if not isinstance(value["review_targets"],list) or len(value["review_targets"])>90:raise ValueError("invalid personal review queue")
    from .personal_review import validate_targets
    validate_targets(value,snapshot)
    return deepcopy(value)
