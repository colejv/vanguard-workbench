"""
Deterministic safety-timeline contract.

The review found a safety-critical defect our own overlay CAUSED: the
Stage 4 Phase 0 prose required active RF signals to cease within 15
seconds, while the structured safety gate allowed a 900-second maximum
termination time. Our overlay read one labeled value ("15 minutes" ->
900s) and propagated it, blind to the conflicting 15-second requirement.
No operator can execute against two authoritative abort timelines.

This module treats a timeline conflict as a HARD SAFETY-CONTRACT
VIOLATION, never a repair target. The compiler must never choose between
conflicting timelines or normalize one into the other.

Timelines are modeled by the EVENT they bound, not by generic keyword
matching. 15 seconds to stop RF emission and 900 seconds to complete
restoration can be valid together — they bound different controls. 15 and
900 seconds both claiming to bound signal cessation are contradictory.

Control types:
  ACTIVE_SIGNAL_CESSATION  — active emissions (RF/GPS/jamming) must stop
  TEST_TERMINATION         — the test/effect chain must be halted
  ROLLBACK_COMPLETION      — restoration/recovery must finish

Failure modes (both stop the pipeline; neither is feedback the repair loop
can rewrite):
  SAFETY_TIMELINE_CONTRADICTION — two different maxima for the SAME control
  SAFETY_TIMELINE_AMBIGUOUS     — a timeline whose control cannot be
                                  determined (never guessed)
"""
import re
from collections.abc import Iterable


class SafetyTimelineContradiction(RuntimeError):
    """Two different maximum values bind the same control. Hard stop."""


class SafetyTimelineAmbiguous(RuntimeError):
    """A timeline's control type cannot be determined. Hard stop — never guess."""


# ---- unit normalization ----

_DURATION_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h)\b",
    re.IGNORECASE,
)


def duration_to_seconds(value: str) -> int:
    """Convert a single duration expression to an integer number of seconds.
    Raises ValueError if it cannot be parsed — never guesses."""
    m = _DURATION_RE.search(value.strip())
    if not m:
        raise ValueError(f"Cannot parse duration to seconds: {value!r}")
    n = float(m.group(1))
    unit = m.group(2).lower()
    if unit.startswith("s"):
        secs = n
    elif unit.startswith("m") and not unit.startswith("h"):
        secs = n * 60
    elif unit.startswith("h"):
        secs = n * 3600
    else:
        raise ValueError(f"Unrecognized duration unit in {value!r}")
    if secs != int(secs):
        # sub-second precision is not meaningful for these controls
        secs = round(secs)
    return int(secs)


# ---- control classification ----

# Event keywords that unambiguously identify a control. Deterministic —
# a timeline is classified only if its surrounding context contains the
# distinctive event language for exactly one control.
_CONTROL_KEYWORDS = {
    "ACTIVE_SIGNAL_CESSATION": (
        "active signal", "signal cessation", "signals must cease", "signal must cease",
        "cease transmission", "cease emission", "rf emission", "emissions must",
        "spoofing signal", "stop transmitting", "transmission must cease",
        "jamming must", "radiate",
    ),
    "ROLLBACK_COMPLETION": (
        "rollback", "roll back", "recovery", "restoration", "restore", "revert",
        "recover to", "return to baseline",
    ),
    "TEST_TERMINATION": (
        "test termination", "terminate the test", "test must terminate",
        "halt the test", "abort the test", "effect chain", "terminate execution",
        "cease the test", "end the test",
    ),
}


def classify_control(context_text: str) -> str:
    """Return the single control type the surrounding context identifies, or
    raise SafetyTimelineAmbiguous if zero or more than one control's event
    language is present. Never guesses."""
    ctx = (context_text or "").lower()
    matched = set()
    for control, keywords in _CONTROL_KEYWORDS.items():
        if any(kw in ctx for kw in keywords):
            matched.add(control)
    if len(matched) == 1:
        return next(iter(matched))
    # Zero or multiple -> we cannot determine the control deterministically.
    raise SafetyTimelineAmbiguous(
        "SAFETY_TIMELINE_AMBIGUOUS\n"
        f"A timeline could not be attributed to exactly one control "
        f"(matched: {sorted(matched) or 'none'}).\n"
        f"Context: {context_text.strip()[:160]!r}\n"
        "The control type must be explicit (signal cessation, test "
        "termination, or rollback completion). Do not guess."
    )


class SafetyTimeline:
    """One control-bounded timeline extracted from an artifact."""

    def __init__(self, *, control: str, maximum_seconds: int,
                 source_artifact: str, source_path: str, source_text: str):
        self.control = control
        self.maximum_seconds = maximum_seconds
        self.source_artifact = source_artifact
        self.source_path = source_path
        self.source_text = source_text

    def as_dict(self) -> dict:
        return {
            "control": self.control,
            "maximum_seconds": self.maximum_seconds,
            "source_artifact": self.source_artifact,
            "source_path": self.source_path,
            "source_text": self.source_text,
        }


class SafetyTimelineContract:
    """The set of authoritative per-control timelines for a run. Consistent
    iff every control resolves to exactly one maximum value across all
    artifacts."""

    def __init__(self, timelines: list):
        self.timelines = list(timelines)

    def by_control(self) -> dict:
        grouped: dict = {}
        for t in self.timelines:
            grouped.setdefault(t.control, []).append(t)
        return grouped

    def require_consistent(self) -> None:
        """Raise SafetyTimelineContradiction if any control has more than one
        distinct maximum value. No value is selected or normalized."""
        for control, entries in self.by_control().items():
            distinct = sorted({e.maximum_seconds for e in entries})
            if len(distinct) > 1:
                lines = [
                    "SAFETY_TIMELINE_CONTRADICTION",
                    "",
                    f"Control: {control}",
                    "",
                ]
                for e in entries:
                    lines.append(
                        f"{e.source_artifact} ({e.source_path}):\n"
                        f"  maximum: {e.maximum_seconds} seconds "
                        f"[{e.source_text.strip()[:80]!r}]"
                    )
                lines += [
                    "",
                    "No value was selected or propagated.",
                    "Analyst resolution is required.",
                ]
                raise SafetyTimelineContradiction("\n".join(lines))

    def canonical_seconds(self, control: str) -> int:
        """Return the single authoritative maximum for a control. Only valid
        after require_consistent() has passed."""
        entries = self.by_control().get(control, [])
        if not entries:
            raise KeyError(f"No timeline for control {control!r}")
        return entries[0].maximum_seconds


# ---- extraction ----

# A prose sentence that pairs a control's event language with a duration.
_SENTENCE_SPLIT = re.compile(r"(?<=[.\n])")


def _extract_prose_timelines(prose: str, *, source_artifact: str) -> list:
    """Extract control-bounded timelines from prose. Each sentence (or line)
    that contains BOTH a duration and exactly one control's event language
    becomes a SafetyTimeline. A sentence with a duration but NO resolvable
    control raises SafetyTimelineAmbiguous — the control must be explicit."""
    timelines = []
    text = prose or ""
    # Split into sentence-ish units so a duration is classified by its own
    # local context, not the whole document.
    units = [u.strip() for u in re.split(r"(?<=[.!?])\s+|\n", text) if u.strip()]
    for unit in units:
        if not _DURATION_RE.search(unit):
            continue
        # A unit may bound a control. If it names a duration but we cannot
        # attribute a control, that's ambiguous and must fail — but only for
        # units that are clearly making a timing claim (contain "within",
        # "cease", "complete", "terminate", "maximum", etc.), to avoid
        # flagging incidental durations.
        timing_claim = any(w in unit.lower() for w in (
            "within", "cease", "complete", "terminat", "maximum", "no later",
            "must stop", "must halt", "abort within", "less than",
        ))
        if not timing_claim:
            continue
        control = classify_control(unit)  # raises SafetyTimelineAmbiguous if unclear
        seconds = duration_to_seconds(unit)
        timelines.append(SafetyTimeline(
            control=control, maximum_seconds=seconds,
            source_artifact=source_artifact, source_path="prose",
            source_text=unit,
        ))
    return timelines


def _extract_structured_signal_cessation(plan: dict, *, source_artifact: str) -> list:
    """The structured safety gate's maximum_termination_seconds is, by this
    framework's convention, the ACTIVE_SIGNAL_CESSATION bound for a
    Category 2/3 payload (it governs how fast an active effect must stop).
    It is only extracted when a value is present; classification is fixed by
    the field's defined meaning, not guessed from text."""
    data = plan.get("data", plan) if isinstance(plan, dict) else {}
    review = data.get("assessment_safety_review") or {}
    secs = review.get("maximum_termination_seconds")
    if secs is None:
        return []
    return [SafetyTimeline(
        control="ACTIVE_SIGNAL_CESSATION", maximum_seconds=int(secs),
        source_artifact=source_artifact,
        source_path="assessment_safety_review.maximum_termination_seconds",
        source_text=f"maximum_termination_seconds={secs}",
    )]


def build_safety_timeline_contract(*, stage3_prose: str = "", stage3_plan: dict = None,
                                   stage4_prose: str = "") -> SafetyTimelineContract:
    """Assemble the authoritative safety-timeline contract from all supplied
    artifacts. Extracts and classifies every control-bounded timeline; the
    caller then calls require_consistent() to enforce one value per control.

    This replaces the old "read one value -> propagate it" overlay behavior:
    the overlay now receives a VALIDATED contract, never raw prose.
    """
    timelines = []
    if stage3_prose:
        timelines += _extract_prose_timelines(stage3_prose, source_artifact="stage3_prose")
    if stage3_plan:
        timelines += _extract_structured_signal_cessation(stage3_plan, source_artifact="stage3_json")
    if stage4_prose:
        timelines += _extract_prose_timelines(stage4_prose, source_artifact="stage4_prose")
    return SafetyTimelineContract(timelines)