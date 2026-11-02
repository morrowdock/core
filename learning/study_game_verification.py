"""Explicit trusted evidence injection; never deserialize authority from a request.

These types are not authentication. A future reviewed adapter must construct them
only from independently checked storage/source records, outside user control.
"""

from dataclasses import dataclass
import hashlib
import json


UNIT_RULE_VERSION = "unit-aliases-v2"
# A finite notation table, not dimensional algebra or a unit conversion parser.
UNIT_ALIASES = {unit: unit for unit in ("", "m", "cm", "km", "s", "min", "kg", "g", "N", "J", "W", "Pa", "Hz", "K", "A", "mol", "rad", "m/s", "cm/s", "km/h", "m/s^2", "cm/s^2", "m^2", "m^3", "s^-1", "N*m", "N/m", "N/m^2", "rad/s", "kg*m/s", "kg/m^3")}
UNIT_ALIASES.update({"1": "", "m/s²": "m/s^2", "m/s2": "m/s^2", "m s^-2": "m/s^2",
                     "m s⁻²": "m/s^2", "m*s^-2": "m/s^2", "m·s^-2": "m/s^2",
                     "m·s⁻²": "m/s^2", "cm/s²": "cm/s^2", "m²": "m^2", "m³": "m^3", "s⁻¹": "s^-1",
                     "N·m": "N*m", "N m": "N*m", "N⋅m": "N*m", "N/m^2": "Pa", "N/m²": "Pa", "kg/m³": "kg/m^3"})
SUPPORTED_UNITS = tuple(sorted(set(UNIT_ALIASES.values())))


def normalized_unit(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        return None
    return UNIT_ALIASES.get(" ".join(value.strip().split()))


def evidence_binding(event):
    """Bind extent, outcome, taxonomy, exact item/work revision and partition."""
    check = {k: v for k, v in (event.get("check") or {}).items() if k != "errorTypes"}
    return json.dumps({"scope": event["scope"], "sourceAttempt": event["sourceAttempt"],
                       "family": event["item"]["canonicalFamilyId"], "skill": event["item"]["skillId"],
                       "responseFormat": event["item"].get("responseFormat", "show_work"),
                       "conditions": {key: event.get(key) for key in ("occurredAt", "sessionId", "mode", "confidence",
                           "assistance", "context", "frozen", "savedWorkNonempty", "workHash")},
                       "check": check}, sort_keys=True, separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True)
class CheckAttestation:
    binding: str
    extent: str
    origin: str
    verification_reference: str
    response_format: str = "show_work"

    def __post_init__(self):
        if self.response_format not in {"choice", "value_only", "show_work"}:
            raise ValueError("unsupported trusted response format")
        if self.extent not in {"final_answer", "whole_solution"}:
            raise ValueError("attestation must distinguish final answer and whole solution")
        if self.origin not in {"source_verified", "generated_independently_checked"}:
            raise ValueError("generated or user-labeled evidence is not verified")
        if not self.verification_reference.strip():
            raise ValueError("independent verification reference required")


@dataclass(frozen=True)
class VerificationAuthority:
    checks: tuple = ()

    def __post_init__(self):
        if not isinstance(self.checks, tuple) or not all(isinstance(c, CheckAttestation) for c in self.checks):
            raise ValueError("authority requires immutable independent attestations")
        bindings = [c.binding for c in self.checks]
        if len(bindings) != len(set(bindings)):
            raise ValueError("duplicate or conflicting trusted check binding")

    def index(self):
        return {c.binding: c for c in self.checks}


@dataclass(frozen=True)
class KeyAttestation:
    """A source-checked key, or a generated key checked independently of its author."""
    item_id: str
    item_version: int
    item_content_hash: str
    key_hash: str
    origin: str
    verification_reference: str
    response_format: str = "show_work"

    def __post_init__(self):
        if self.response_format not in {"choice", "value_only", "show_work"}:
            raise ValueError("unsupported trusted response format")
        if self.origin not in {"source_verified", "generated_independently_checked"}:
            raise ValueError("a generated key needs independent checking")
        if not self.verification_reference.strip():
            raise ValueError("key provenance reference required")


def prepare_answer_key(key):
    """Creation boundary: refuse unsupported numeric key units, never score them.

    Returns a detached JSON key; callers store/hash this validated version.
    Validation is repeated by key_hash/check_final_answer for older callers.
    """
    if not isinstance(key, dict) or key.get("kind") not in ("numeric", "choice"):
        raise ValueError("unsupported key kind")
    if key["kind"] == "numeric" and normalized_unit(key.get("unit")) is None:
        raise ValueError("unsupported answer-key unit")
    return json.loads(json.dumps(key, sort_keys=True, allow_nan=False))


def key_hash(key):
    key = prepare_answer_key(key)
    return hashlib.sha256(json.dumps(key, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("utf-8")).hexdigest()


def check_final_answer(source, answer, key, *, attestation=None):
    """Offline numeric/choice comparison; never asserts whole-solution correctness.

    Keys and answers stay in the caller's memory. This returns no key/solution.
    A bare keySource or verification label does not create trusted evidence.
    Numeric comparisons use only the documented finite notation aliases.
    """
    from decimal import Decimal, InvalidOperation

    hashed = key_hash(key)
    trusted = isinstance(attestation, KeyAttestation) and (
        attestation.item_id, attestation.item_version, attestation.item_content_hash, attestation.key_hash
    ) == (source["itemId"], source["itemVersion"], source["itemContentHash"], hashed)
    trusted = trusted and (attestation.response_format == "show_work" or
        (attestation.response_format == "choice" and key.get("kind") == "choice") or
        (attestation.response_format == "value_only" and key.get("kind") == "numeric"))
    result = {"extent": "final_answer", "outcome": "uncertain", "keyHash": hashed,
              "keyVerified": trusted, "wholeSolutionCorrectness": "not_established", "errorTypes": [],
              "verificationReference": attestation.verification_reference if trusted else None,
              "responseFormat": attestation.response_format if trusted else "not_verified",
              "completeResponseCorrectness": "not_established", "unitRuleVersion": UNIT_RULE_VERSION}
    if key.get("kind") == "choice":
        choices = key.get("choices", [])
        if not choices or len(choices) != len(set(choices)) or key.get("correct") not in choices:
            raise ValueError("invalid choice key")
        result["outcome"] = "correct" if answer.get("choice") == key["correct"] else "needs_review"
    elif key.get("kind") == "numeric":
        try:
            numbers = [Decimal(str(v)) for v in (answer.get("value"), key.get("value"), key.get("relTol", "0.02"), key.get("absTol", "0"))]
        except (InvalidOperation, ValueError):
            return result
        if not all(n.is_finite() for n in numbers) or not 0 <= numbers[2] <= Decimal("0.02") or numbers[3] < 0:
            raise ValueError("finite numeric values and conservative tolerances required")
        answer_unit, expected_unit = normalized_unit(answer.get("unit")), normalized_unit(key.get("unit"))
        if answer_unit is None or expected_unit is None:
            result["reason"] = "unit_notation_unrecognized"
        elif answer_unit != expected_unit:
            result.update(outcome="needs_review", errorTypes=["units"], reason="exact_units_required_no_conversion")
        else:
            tolerance = max(abs(numbers[1]) * numbers[2], numbers[3])
            result["outcome"] = "correct" if abs(numbers[0] - numbers[1]) <= tolerance else "needs_review"
    else:
        raise ValueError("unsupported key kind")
    if trusted and attestation.response_format in {"choice", "value_only"}:
        result["completeResponseCorrectness"] = result["outcome"]
    return result
