"""Measured uk/en judge policy over an explicitly configured OpenRouter model."""
import json
import time

import httpx2 as httpx

from . import Verdict, Judgement, turn_message

SYSTEM = """You judge one learner turn in a spoken Ukrainian lesson. The learner is
an adult reactivating Ukrainian learnt earlier (about A2). The learner's words
come from speech recognition: ignore capital letters, punctuation and missing
stress marks.

Given the step's task, the expected target sentence(s) and the learner's turn,
return:

- verdict:
  - "accept": correct Ukrainian that does the task. A different correct
    sentence is fine, and so is a missing «а» or a small word-order change. A
    question that asks for the same information in other words does the task
    (asking whether it is a direct line does the task "ask whether he has to
    change"). When the step is an open answer, any correct sentence of the
    right kind is fine.
  - "error": the learner tried the task but the Ukrainian is wrong: a Russian
    word or form (где, как, нет, потом, можно, спасибо …), a wrong ending or
    case, a wrong word, a missing key word; or the learner did something else
    than the task.
  - "unclear": you cannot tell what the learner meant (a few syllables,
    hesitation only, noise).
  - "question": the learner asks what a word means or asks for help.
  - "social": a normal social reply that is not the task, such as returning
    the teacher's greeting. The learner will do the task next.
  - "later_step": correct Ukrainian that does the task of one of the
    later_steps instead of this one (the learner ran ahead in the dialogue),
    also when it does that task in other words (asking whether it is a direct
    line does a later "ask whether he has to change"). Put that step's number
    in step.
- on_task: true when the learner tried to do the step's task.
- chunk: for "error" only, the correct Ukrainian for the single most important
  mistake, one to four words, with stress marks (combining acute after the
  stressed vowel) where you are sure. Not the whole sentence unless it is that
  short. "" otherwise.
- reply: for "question" only, one short Ukrainian sentence that answers it. ""
  otherwise.
- step: for "later_step" only, the number of the later step; 0 otherwise.
- note: a few English words on what was wrong, for the log. "" when accepted.

Judge strictly on Russian: a Russian word is an error even when understandable.
Judge generously on everything else a Ukrainian listener would let pass."""


class OpenRouterJudge:
    def __init__(self, key, model, *, client=None, timeout=30):
        if not isinstance(key, str) or not key or not isinstance(model, str) or not model.strip():
            raise ValueError("explicit judge credential and model are required")
        if type(timeout) not in {int,float} or not 0 < timeout <= 120:
            raise ValueError("invalid judge timeout")
        self._key, self.model, self.timeout = key, model, timeout
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=False)

    def __call__(self, item, learner):
        properties = {k:{"type":"string"} for k in ("verdict","chunk","reply","note")}
        properties["verdict"]["enum"] = ["accept","error","unclear","question","social","later_step"]
        properties.update(on_task={"type":"boolean"},step={"type":"integer","minimum":0})
        started = time.monotonic()
        try:
            with self.client.stream("POST", "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization":"Bearer "+self._key}, timeout=self.timeout, follow_redirects=False,
                    json={"model":self.model,"messages":[{"role":"system","content":SYSTEM},{"role":"user","content":turn_message(item,learner)}],
                          "response_format":{"type":"json_schema","json_schema":{"name":"verdict","strict":True,
                              "schema":{"type":"object","properties":properties,"required":list(properties),"additionalProperties":False}}},
                          "max_tokens":2000,"provider":{"require_parameters":True,"sort":"latency"},
                          "reasoning":{"effort":"minimal"},"usage":{"include":True}}) as response:
                if response.status_code != 200: raise ValueError()
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 1024*1024: raise ValueError()
            raw = json.loads(body)
            choice = raw["choices"][0]
            if choice["finish_reason"] != "stop": raise ValueError()
            data = json.loads(choice["message"]["content"])
            if set(data) != set(properties): raise ValueError()
            verdict = Verdict(**data)
            usage = raw.get("usage") or {}
            # Retain only numeric usage, never arbitrary provider response fields.
            safe = {k:usage[k] for k in ("prompt_tokens","completion_tokens","cost") if type(usage.get(k)) in {int,float}}
            return Judgement(verdict, round(time.monotonic()-started,3), safe)
        except Exception:
            raise RuntimeError("judge provider operation failed; retry the same request") from None
