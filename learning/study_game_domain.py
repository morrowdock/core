"""Pure study rules, consumed by the practice ledger projection.

The ledger adapter supplies saved evidence; independent verification requires authority.
Hashes bind identities; this module does not authenticate or verify those hashes.
No IO, clock, random source, scheduler, provider, persistence or legacy imports.
"""

from copy import deepcopy
from datetime import datetime, timedelta
import json
import re

from study_game_practice import day_plan_limit, missions as practice_missions, practice_xp, weekly_goal
from study_game_verification import VerificationAuthority, evidence_binding


RULE_VERSION = "study-game-rules-v3.1"
INPUT_FORMAT = "morrowdock-study-game-input-v1"
INTEGRATION_ENABLED = False
RECALL_DELAY = timedelta(hours=24)
MIXED_DELAY = timedelta(days=7)
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z\Z")
_ASSISTANCE = {"notes", "hint", "worked_answer", "external_feedback"}


class DomainInputError(ValueError):
    """Unsupported, ambiguous or conflicting evidence; no partial result."""


def _object(value, name):
    if not isinstance(value, dict):
        raise DomainInputError(f"{name} must be an object")
    return value


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise DomainInputError(f"{name} must be nonempty text, at most 2000 characters")
    return value


def _integer(value, name, minimum=1, maximum=1000000):
    if type(value) is not int or not minimum <= value <= maximum:
        raise DomainInputError(f"{name} must be an integer in {minimum}..{maximum}")
    return value


def _boolean(value, name):
    if type(value) is not bool:
        raise DomainInputError(f"{name} must be boolean")
    return value


def _choice(value, choices, name):
    if not isinstance(value, str) or value not in choices:
        raise DomainInputError(f"unsupported {name}")
    return value


def _time(value):
    if not isinstance(value, str) or not _UTC.fullmatch(value):
        raise DomainInputError("timestamps must be UTC with optional microseconds")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ" if "." in value else "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise DomainInputError("invalid UTC date") from error


def _hash(value):
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise DomainInputError("expected lowercase SHA256")
    return value


def _scope(value):
    obj = _object(value, "scope")
    if set(obj) != {"namespaceId", "course", "assignment", "examScope"}:
        raise DomainInputError("scope requires namespaceId, course, assignment, examScope")
    for name in ("namespaceId", "course", "assignment"):
        _text(obj[name], name)
    exam = obj["examScope"]
    if exam is not None:
        _object(exam, "examScope")
        if set(exam) != {"id", "revision", "status", "sourceReference"}:
            raise DomainInputError("examScope requires id/revision/status/sourceReference")
        _text(exam["id"], "exam scope id")
        _integer(exam["revision"], "exam scope revision")
        _choice(exam["status"], {"tentative", "verified"}, "exam scope status")
        _text(exam["sourceReference"], "exam scope source")
    return deepcopy(obj)


def _foreign_scope(candidate, selected):
    if not isinstance(candidate, dict):
        return False  # Unroutable input may belong here; fail closed in validation.
    if any(key in candidate and candidate[key] != selected[key] for key in ("namespaceId", "course", "assignment")):
        return True
    if "examScope" not in candidate:
        return False
    exam, target = candidate["examScope"], selected["examScope"]
    if (exam is None) != (target is None):
        return True
    return isinstance(exam, dict) and isinstance(target, dict) and any(
        key in exam and exam[key] != target[key] for key in ("id", "revision"))


def _source(value):
    obj = _object(value, "sourceAttempt")
    if set(obj) != {"attemptId", "revision", "revisionHash", "itemId", "itemVersion", "itemContentHash"}:
        raise DomainInputError("sourceAttempt requires the full immutable item/revision binding")
    _text(obj["attemptId"], "attemptId")
    _text(obj["itemId"], "itemId")
    _integer(obj["revision"], "attempt revision")
    _integer(obj["itemVersion"], "item version")
    _hash(obj["revisionHash"])
    _hash(obj["itemContentHash"])
    return deepcopy(obj)


def _source_key(source):
    return source["attemptId"], source["revision"]


def _assert_acyclic(links):
    complete = set()
    for start in links:
        path, node = set(), start
        while node in links and node not in complete:
            if node in path:
                raise DomainInputError("cyclic retry/correction identity")
            path.add(node)
            node = links[node]
        complete.update(path)


def _decision(scope, reasons, sources=(), data_needed=(), **values):
    return {"ruleVersion": RULE_VERSION, "scope": deepcopy(scope),
            "reasons": list(reasons), "sourceAttemptRevisions": deepcopy(list(sources)),
            "dataNeeded": sorted(set(data_needed)), **values}


def _normalize(request):
    obj = deepcopy(_object(request, "request"))
    if obj.get("format") != INPUT_FORMAT:
        raise DomainInputError("unsupported input format; no implicit migration")
    now = _time(obj.get("asOf"))
    scope = _scope(obj.get("scope"))
    complete = _boolean(obj.get("historyComplete"), "historyComplete")
    raw = obj.get("events")
    if not isinstance(raw, list) or len(raw) > 10000:
        raise DomainInputError("events must be a list with at most 10000 entries")
    attempts, ignored, by_event, by_source = [], [], {}, {}
    item_versions, families, family_skills, attempt_items = {}, {}, {}, {}
    for raw_event in raw:
        event = deepcopy(_object(raw_event, "event"))
        event.pop("checkHistory", None)
        event.pop("firstCheckedAt", None)
        routed = event.get("scope")
        if _foreign_scope(routed, scope):
            continue  # Provably foreign records do not validate or poison this set.
        event_scope = _scope(event.get("scope"))
        if event_scope != scope:
            continue  # No rollup across namespace/course/assignment/exam scope/version.
        event_id = _text(event.get("eventId"), "eventId")
        if event_id in by_event:
            if event != by_event[event_id]:
                raise DomainInputError("eventId reused with different evidence")
            continue
        by_event[event_id] = deepcopy(event)
        kind = _choice(event.get("kind"), {"attempt", "upload", "ai_reply"}, "event kind")
        at = _time(event.get("occurredAt"))
        if at > now:
            raise DomainInputError("future evidence cannot be evaluated")
        if kind != "attempt":
            ignored.append({"eventId": event_id, "reason": "activity_is_not_attempt_evidence"})
            continue
        source = _source(event.get("sourceAttempt"))
        key = _source_key(source)
        # An alias event ID is still the same frozen revision, never another award.
        item = _object(event.get("item"), "item")
        for name in ("canonicalFamilyId", "skillId", "sourceReference"):
            _text(item.get(name), name)
        _choice(item.get("responseFormat", "show_work"), {"choice", "value_only", "show_work"}, "response format")
        _choice(item.get("verification"), {"tentative", "verified"}, "content verification")
        if item["verification"] == "verified":
            _text(item.get("verificationReference"), "content verificationReference")
        content_key = source["itemId"], source["itemVersion"]
        item_identity = source["itemContentHash"], item
        if content_key in item_versions and item_versions[content_key] != item_identity:
            raise DomainInputError("conflicting immutable item version")
        item_versions[content_key] = item_identity
        # Re-labeling identical content as a new family or skill cannot farm credit.
        taxonomy = item["canonicalFamilyId"], item["skillId"]
        if source["itemContentHash"] in families and families[source["itemContentHash"]] != taxonomy:
            raise DomainInputError("identical content has conflicting family/skill identity")
        families[source["itemContentHash"]] = taxonomy
        if taxonomy[0] in family_skills and family_skills[taxonomy[0]] != taxonomy[1]:
            raise DomainInputError("one canonical family cannot earn credit under multiple skills")
        family_skills[taxonomy[0]] = taxonomy[1]
        retry = event.get("retryOf")
        if retry is not None:
            _text(retry, "retryOf")
            if retry == source["attemptId"]:
                raise DomainInputError("attempt cannot retry itself")
        identity = source["itemId"], source["itemVersion"], event.get("mode"), retry
        if source["attemptId"] in attempt_items and attempt_items[source["attemptId"]] != identity:
            raise DomainInputError("attempt item/mode/retry identity changed")
        attempt_items[source["attemptId"]] = identity
        _choice(event.get("mode"), {"practice", "closed_note"}, "attempt mode")
        _text(event.get("sessionId"), "sessionId")
        _boolean(event.get("savedWorkNonempty"), "savedWorkNonempty")
        _boolean(event.get("frozen"), "frozen")
        if "confidence" not in event:
            raise DomainInputError("confidence must be present, with null for not provided")
        if event["confidence"] is not None:
            _choice(event["confidence"], {"unsure", "somewhat", "confident"}, "confidence")
        if event.get("workHash") is not None:
            _hash(event["workHash"])
        _choice(event.get("workKind", "text"), {"text", "scratch", "worksheet"}, "work kind")
        assistance = event.get("assistance")
        if assistance is not None:
            _object(assistance, "assistance")
            _boolean(assistance.get("historyComplete"), "assistance.historyComplete")
            _boolean(assistance.get("revealed"), "assistance.revealed")
            used = assistance.get("used")
            if not isinstance(used, list) or len(used) > 4 or len(set(map(str, used))) != len(used):
                raise DomainInputError("assistance.used must list distinct assistance types")
            for help_type in used:
                _choice(help_type, _ASSISTANCE, "assistance type")
        context = _object(event.get("context"), "context")
        _choice(context.get("kind"), {"single", "mixed", "transfer"}, "context kind")
        skills = context.get("skillIds")
        if not isinstance(skills, list) or not 1 <= len(skills) <= 100:
            raise DomainInputError("context.skillIds must list 1..100 skills")
        for skill in skills:
            _text(skill, "context skill")
        if item["skillId"] not in skills:
            raise DomainInputError("context must include the item's skill")
        check = event.get("check")
        if check is not None:
            _object(check, "check")
            _choice(check.get("method"), {"owner_self_check", "deterministic", "rubric_review"}, "check method")
            _choice(check.get("outcome"), {"correct", "needs_review", "uncertain"}, "check outcome")
            _choice(check.get("extent", "unspecified"), {"unspecified", "final_answer", "whole_solution"}, "check extent")
            error_types = check.get("errorTypes", [])
            if not isinstance(error_types, list) or len(error_types) > 5:
                raise DomainInputError("errorTypes must be a bounded list")
            for error_type in error_types:
                _choice(error_type, {"concept", "setup", "algebra", "units", "reading"}, "error type")
            if _source(check.get("sourceAttempt")) != source:
                raise DomainInputError("check does not match the exact frozen revision")
            _text(check.get("reference"), "check reference")
            if _time(check.get("checkedAt")) < at or _time(check["checkedAt"]) > now:
                raise DomainInputError("check timestamp outside saved revision/asOf range")
        correction = event.get("correctionOf")
        if correction is not None:
            _source(correction)
        comparable = {k: v for k, v in event.items() if k not in {"eventId", "check"}}
        if key in by_source:
            previous, immutable = by_source[key]
            if comparable != immutable:
                raise DomainInputError("conflicting immutable attempt revision")
            old_check = previous.get("check")
            if check == old_check:
                continue
            if not (check and old_check and check["method"] == old_check["method"] == "owner_self_check"):
                raise DomainInputError("conflicting independent checks on one immutable revision")
            # Owner checks are mutable assessments of immutable work. Re-checking
            # that work is legal and must not become a storage-identity error.
            history = previous.get("checkHistory", [old_check]) + [check]
            unique = {json.dumps(c, sort_keys=True): c for c in history}
            history = sorted(unique.values(), key=lambda c: (_time(c["checkedAt"]),
                {"correct": 0, "needs_review": 1, "uncertain": 2}[c["outcome"]], c["reference"]))
            previous["checkHistory"] = history
            previous["check"] = history[-1]
            previous["firstCheckedAt"] = history[0]["checkedAt"]
            continue
        event["firstCheckedAt"] = check["checkedAt"] if check else None
        by_source[key] = event, comparable
        attempts.append(event)
    attempts.sort(key=lambda e: (_time(e["occurredAt"]), e["sourceAttempt"]["attemptId"], e["sourceAttempt"]["revision"]))
    indexed = {_source_key(e["sourceAttempt"]): e for e in attempts}
    first_by_attempt = {}
    for event in attempts:
        first_by_attempt.setdefault(event["sourceAttempt"]["attemptId"], event)
    previous_revisions = {}
    for event in attempts:
        attempt_id = event["sourceAttempt"]["attemptId"]
        previous_revision = previous_revisions.get(attempt_id)
        if previous_revision is not None and event["sourceAttempt"]["revision"] <= previous_revision:
            raise DomainInputError("attempt revisions must increase with saved time")
        previous_revisions[attempt_id] = event["sourceAttempt"]["revision"]
        parent = event.get("correctionOf")
        if parent is not None:
            previous = indexed.get(_source_key(parent))
            if previous is None:
                if complete:
                    raise DomainInputError("complete history has a missing correction source")
                continue
            same_family = previous["item"]["canonicalFamilyId"] == event["item"]["canonicalFamilyId"]
            parent_checks = previous.get("checkHistory", [previous.get("check")])
            prior_error = any(c and c["outcome"] in {"needs_review", "uncertain"}
                              and _time(c["checkedAt"]) <= _time(event["occurredAt"]) for c in parent_checks)
            if (previous["sourceAttempt"] != parent or not same_family or
                    _source_key(parent) == _source_key(event["sourceAttempt"]) or
                    (parent["attemptId"] == event["sourceAttempt"]["attemptId"] and parent["revision"] >= event["sourceAttempt"]["revision"]) or
                    _time(previous["occurredAt"]) > _time(event["occurredAt"]) or
                    not prior_error):
                raise DomainInputError("correction must bind an earlier checked error in the same family")
        retry = event.get("retryOf")
        if retry is not None:
            parent_attempt = first_by_attempt.get(retry)
            if parent_attempt is None and complete:
                raise DomainInputError("complete history has a missing retry source")
            if parent_attempt and (_time(parent_attempt["occurredAt"]) > _time(event["occurredAt"]) or
                            parent_attempt["item"]["canonicalFamilyId"] != event["item"]["canonicalFamilyId"]):
                raise DomainInputError("retry must follow an attempt in the same family")
    _assert_acyclic({key: e["retryOf"] for key, e in first_by_attempt.items() if e.get("retryOf")})
    _assert_acyclic({_source_key(e["sourceAttempt"]): _source_key(e["correctionOf"]) for e in attempts if e.get("correctionOf")})
    return obj, scope, now, complete, attempts, sorted(ignored, key=lambda e: e["eventId"])


def _verified(event, trusted, extent="whole_solution"):
    check = event.get("check")
    attestation = trusted.get(evidence_binding(event)) if check is not None else None
    return bool(event["frozen"] and event["savedWorkNonempty"] and check is not None and
            check["method"] in {"deterministic", "rubric_review"} and
            check.get("extent") == extent and attestation is not None and attestation.extent == extent
            and attestation.response_format == event["item"].get("responseFormat", "show_work"))


def _response_verified(event, trusted):
    if _verified(event, trusted):
        return True
    return (_verified(event, trusted, "final_answer") and
            trusted[evidence_binding(event)].response_format in {"choice", "value_only"})


def _assistance_by_revision(events):
    """Sticky help up to each revision; later help cannot rewrite earlier evidence."""
    result, seen = {}, {}
    for event in sorted(events, key=lambda e: (e["sourceAttempt"]["attemptId"], e["sourceAttempt"]["revision"])):
        key = event["sourceAttempt"]["attemptId"]
        used, revealed, complete = seen.get(key, (set(), False, True))
        help_state = event.get("assistance")
        if help_state is None:
            complete = False
        else:
            used = used | set(help_state["used"])
            revealed = revealed or help_state["revealed"]
            complete = complete and help_state["historyComplete"]
        seen[key] = used, revealed, complete
        result[_source_key(event["sourceAttempt"])] = seen[key]
    return result


def _practice_rows(events):
    help_states = _assistance_by_revision(events)
    rows = []
    for event in events:
        used, revealed, complete = help_states[_source_key(event["sourceAttempt"])]
        rows.append({**event, "assistance": {"used": sorted(used), "revealed": revealed, "historyComplete": complete}})
    return rows


def _recent_exposure(events):
    """Bounded work per event, even for a long history of repeated attempts."""
    blocked, latest_two, sessions = set(), {}, {}
    for event in events:
        if not event["savedWorkNonempty"]:
            continue
        source, family = event["sourceAttempt"], event["item"]["canonicalFamilyId"]
        at, attempt_id = _time(event["occurredAt"]), source["attemptId"]
        previous = latest_two.get(family, [])
        session_key = family, event["sessionId"]
        seen_attempts = sessions.setdefault(session_key, set())
        if (any(other != attempt_id and at - when < RECALL_DELAY for other, when in previous) or
                len(seen_attempts) > 1 or (seen_attempts and attempt_id not in seen_attempts)):
            blocked.add(_source_key(source))
        seen_attempts.add(attempt_id)
        latest_two[family] = [(attempt_id, at)] + [(other, when) for other, when in previous if other != attempt_id][:1]
    return blocked


def evaluate(request, *, authority=None, confidence_checks=frozenset()):
    """Return a replayable proposal. Actual XP is always zero; activation is absent.

    Full input shape, trust boundaries, thresholds and missing MVP data are in
    docs/STUDY-GAME-DOMAIN.md. Malformed/conflicting evidence raises atomically.
    """
    obj, scope, now, complete, events, ignored = _normalize(request)
    if authority is not None and not isinstance(authority, VerificationAuthority):
        raise DomainInputError("authority must come from a trusted adapter, never request JSON")
    if not isinstance(confidence_checks, frozenset) or any(type(check) is not str for check in confidence_checks):
        raise DomainInputError("confidence policy must come from the persisted check adapter")
    trusted = authority.index() if authority is not None else {}
    help_by_revision = _assistance_by_revision(events)
    recent_exposure = _recent_exposure(events)
    available_sources = {_source_key(e["sourceAttempt"]) for e in events}
    preferences = _object(obj.get("preferences", {}), "preferences")
    if set(preferences) - {"levels", "missions", "challenges", "restDay", "dailyItemLimit", "practiceXp", "dailyPracticeXpCap", "weeklyGoalDays", "recallConfidencePolicy"}:
        raise DomainInputError("unsupported preference; no hidden reward options")
    opts = {key: _boolean(preferences.get(key, False), key)
            for key in ("levels", "missions", "challenges", "restDay")}
    cap = _integer(preferences.get("dailyItemLimit", 3), "dailyItemLimit", 1, 10)
    confidence_policy = _choice(preferences.get("recallConfidencePolicy", "exclude_unsure"),
                                {"exclude_unsure", "ignore"}, "recall confidence policy")
    exam_verified = scope["examScope"] is None or scope["examScope"]["status"] == "verified"
    all_needed, skill_results, preview_awards = set(), [], []
    if not complete:
        all_needed.add("complete_scope_attempt_history")
    if not exam_verified:
        all_needed.add("verified_exam_scope_revision")
    by_skill = {}
    for event in events:
        by_skill.setdefault(event["item"]["skillId"], []).append(event)
    for skill, rows in sorted(by_skill.items()):
        work = [e for e in rows if e["savedWorkNonempty"]]
        needed, reasons = set(), []
        if not complete:
            needed.add("complete_scope_attempt_history")
            reasons.append("incomplete_history_prevents_mastery_and_awards")
        if not exam_verified:
            needed.add("verified_exam_scope_revision")
            reasons.append("tentative_exam_scope_prevents_mastery")
        qualified, corrections, independent, mixed = [], [], [], []
        for event in work:
            source = event["sourceAttempt"]
            help_used, revealed, help_complete = help_by_revision[_source_key(source)]
            if not (_verified(event, trusted) or _verified(event, trusted, "final_answer")):
                needed.add("verified_content_and_source_reference")
                reasons.append("unattested_content_and_user_labels_cannot_verify_learning")
            check = event.get("check")
            if not _response_verified(event, trusted):
                needed.add("independent_check_bound_to_frozen_revision")
                reasons.append("missing_independent_check_cannot_verify_learning")
                needed.add("trusted_whole_solution_attestation_not_only_final_answer" if
                    event["item"].get("responseFormat", "show_work") == "show_work" else "trusted_complete_response_attestation")
            if not event["frozen"]:
                needed.add("frozen_saved_revision")
            if not help_complete:
                needed.add("complete_assistance_and_reveal_history")
            if help_used or revealed:
                reasons.append("assistance_recorded_not_independent_recall")
            if (event.get("correctionOf") is not None and help_complete and
                    _source_key(event["correctionOf"]) in available_sources and event["frozen"] and check is not None):
                corrections.append(event)
            if not (_response_verified(event, trusted) and check["outcome"] == "correct"):
                continue
            # Normalized ties have no trusted ledger sequence. Any older-policy
            # assessment on this immutable revision keeps its original policy.
            confidence_independent = all(row['reference'] in confidence_checks
                                         for row in event.get('checkHistory', [check]))
            if event["confidence"] is None and not confidence_independent:
                reasons.append("learner_confidence_not_provided")
                needed.add("learner_confidence_report_for_independent_recall")
            clean = (help_complete and not help_used and not revealed and
                     event["mode"] == "closed_note" and
                     ((event["confidence"] is None and confidence_independent) or
                      (event["confidence"] is not None and (confidence_policy == "ignore" or event["confidence"] != "unsure"))) and
                     event.get("correctionOf") is None and _source_key(source) not in recent_exposure)
            # A fresh ID cannot turn a same-session retry/correction into recall.
            if clean and complete and exam_verified:
                qualified.append(event)
        # One frozen revision per attempt/session/day/family in the mastery chain.
        # Revisions, same-day drills and renamed copies cannot advance the chain.
        used_attempts, used_sessions, used_days, used_families = set(), set(), set(), set()
        for event in qualified:
            source = event["sourceAttempt"]
            family = event["item"]["canonicalFamilyId"]
            day = event["occurredAt"][:10]
            if (source["attemptId"] in used_attempts or event["sessionId"] in used_sessions or
                    day in used_days or family in used_families):
                continue
            if independent and _time(event["occurredAt"]) - _time(independent[-1]["occurredAt"]) < RECALL_DELAY:
                continue
            independent.append(event)
            used_attempts.add(source["attemptId"])
            used_sessions.add(event["sessionId"])
            used_days.add(day)
            used_families.add(family)
        # The third qualifying distinct family must be mixed/transfer, cover at
        # least two skills, and occur >=7 days after the retention checkpoint.
        if len(independent) >= 2:
            retained_at = _time(independent[1]["occurredAt"])
            baseline_families = {e["item"]["canonicalFamilyId"] for e in independent[:2]}
            baseline_attempts = {e["sourceAttempt"]["attemptId"] for e in independent[:2]}
            baseline_sessions = {e["sessionId"] for e in independent[:2]}
            mixed = [e for e in qualified if e["context"]["kind"] in {"mixed", "transfer"}
                     and len(set(e["context"]["skillIds"])) >= 2
                     and e["item"]["canonicalFamilyId"] not in baseline_families
                     and e["sourceAttempt"]["attemptId"] not in baseline_attempts
                     and e["sessionId"] not in baseline_sessions
                     and _time(e["occurredAt"]) - retained_at >= MIXED_DELAY]
        # Current errors are a repair suggestion, never a deduction from awards.
        latest_by_family = {}
        for event in work:
            if event.get("check"):
                latest_by_family[event["item"]["canonicalFamilyId"]] = event
        unresolved = [e for e in latest_by_family.values()
                      if e.get("check") and e["check"]["outcome"] in {"needs_review", "uncertain"}]
        stage = "new" if not work else "practiced"
        if independent:
            stage = "building"
            reasons.append("closed_note_attested_recall_without_help")
        if len(independent) >= 2:
            stage = "retained"
            reasons.append("two_distinct_families_sessions_days_at_least_24h_apart")
        if mixed:
            stage = "mastered"
            reasons.append("third_family_mixed_transfer_at_least_7d_after_retention")
        if unresolved:
            reasons.append("latest_family_check_requires_review")
        if len(independent) < 2:
            needed.add("two_unassisted_attested_families_at_least_24h_apart")
        if not mixed:
            needed.add("later_mixed_or_transfer_evidence_7d_after_retention")
        # Milestone XP is retired. The evidence map and Practice XP have separate
        # purposes; no tag/set/claimed-confidence multiplier remains.
        evidence = {"firstAttempt": [work[0]["sourceAttempt"]] if work and complete else [],
                    "corrections": [e["sourceAttempt"] for e in corrections],
                    "independentRecall": [e["sourceAttempt"] for e in independent],
                    "laterMixedPractice": [e["sourceAttempt"] for e in mixed]}
        reasons.extend(["practice_is_not_official_submission", "readiness_not_established"])
        skill_results.append(_decision(scope, sorted(set(reasons)), [e["sourceAttempt"] for e in rows], needed,
            skillId=skill, candidateStage=stage, evidence=evidence,
            needsReview=bool(unresolved),
            openRepairs=[{"canonicalFamilyId": e["item"]["canonicalFamilyId"], "sourceAttempt": e["sourceAttempt"],
                          "since": e["check"]["checkedAt"], "confidentError": e["confidence"] == "confident",
                          "outcome": e["check"]["outcome"], "errorTypes": e["check"].get("errorTypes", [])} for e in unresolved],
            calibration={"confidentAnswers": sum(e["confidence"] == "confident" and e.get("check") is not None for e in rows),
                         "confidentCorrect": sum(e["confidence"] == "confident" and _response_verified(e, trusted) and e["check"]["outcome"] == "correct" for e in rows),
                         "basis": "trusted_complete_response_correctness"},
            checkCoverage={"finalAnswerChecked": [_source_key(e["sourceAttempt"]) for e in rows if _verified(e, trusted, "final_answer")],
                           "wholeSolutionChecked": [_source_key(e["sourceAttempt"]) for e in rows if _verified(e, trusted)],
                           "completeResponseChecked": [_source_key(e["sourceAttempt"]) for e in rows if _response_verified(e, trusted)]},
            evidenceTimeline=[{"sourceAttempt": e["sourceAttempt"], "savedAt": e["occurredAt"],
                               "sessionId": e["sessionId"], "mode": e["mode"], "confidence": e["confidence"],
                               "context": e["context"], "checkMethod": e["check"]["method"] if e.get("check") else None,
                               "outcome": e["check"]["outcome"] if e.get("check") else None,
                               "checkedAt": e["check"]["checkedAt"] if e.get("check") else None} for e in rows],
            contentVerification=[{"sourceAttempt": e["sourceAttempt"],
                                  "claimedStatus": e["item"]["verification"],
                                  "status": "attested" if _verified(e, trusted) or _verified(e, trusted, "final_answer") else "not_established",
                                  "sourceReference": e["item"]["sourceReference"],
                                  "claimedVerificationReference": e["item"].get("verificationReference"),
                                  "responseFormat": e["item"].get("responseFormat", "show_work"),
                                  "verificationReference": trusted[evidence_binding(e)].verification_reference if
                                      _verified(e, trusted) or _verified(e, trusted, "final_answer") else None} for e in rows],
            assistanceRecorded=[{"sourceAttempt": e["sourceAttempt"],
                                 "used": sorted(help_by_revision[_source_key(e["sourceAttempt"])][0]),
                                 "revealed": help_by_revision[_source_key(e["sourceAttempt"])][1],
                                 "historyComplete": help_by_revision[_source_key(e["sourceAttempt"])][2]} for e in rows],
            evaluatedAt=obj["asOf"], masteryMeaning="historical_evidence_only", retentionForecast="not_established"))
        all_needed.update(needed)
    work = [e for e in events if e["savedWorkNonempty"]]
    if not work:
        all_needed.add("saved_nonempty_attempt_revision")
    zone = _text(obj.get("timeZone", "UTC"), "timeZone")
    try:
        cap, returning = day_plan_limit(events, obj["asOf"], cap, zone)
        missions = practice_missions(_practice_rows(events), scope, obj["asOf"], enabled=opts["missions"],
                                     rest=opts["restDay"], limit=cap, zone=zone)
    except ValueError as error:
        raise DomainInputError(str(error)) from error
    return_plan = _decision(scope, ["no_streak_reset_no_debt_no_xp_loss"],
        [work[-1]["sourceAttempt"]] if work else [], state="rest" if opts["restDay"] else "welcome_back" if returning else "ready",
        suggestedItemLimit=0 if opts["restDay"] else cap,
        message="Rest is welcome. Your saved evidence stays here." if opts["restDay"] else
                "Welcome back. One small practice item is enough; choose when to continue." if returning else
                "Choose a small practice goal when it suits you.", xpPenalty=0)
    global_complete = _boolean(obj.get("practiceHistoryComplete", False), "practiceHistoryComplete")
    practice_enabled = _boolean(preferences.get("practiceXp", opts["levels"]), "practiceXp")
    daily_cap = _integer(preferences.get("dailyPracticeXpCap", 25), "dailyPracticeXpCap", 1, 25)
    weekly_target = _integer(preferences.get("weeklyGoalDays", 0), "weeklyGoalDays", 0, 7)
    namespace_requested = practice_enabled or weekly_target > 0
    invalid_history = False
    practice_events = []
    if namespace_requested:
        try:
            practice_events = _namespace_events(obj, scope["namespaceId"], global_complete)
        except DomainInputError:
            invalid_history = True
    effective_complete = global_complete and not invalid_history and namespace_requested
    try:
        practice = practice_xp(practice_events, scope["namespaceId"], obj["asOf"], complete=effective_complete,
            enabled=practice_enabled, zone=zone, daily_cap=daily_cap, confidence_checks=confidence_checks)
        if invalid_history or not namespace_requested:
            practice.update(status="history_invalid" if invalid_history else "not_requested", daily=None,
                dataNeeded=["practice_history_invalid"] if invalid_history else ["namespace_view_not_requested"])
        weekly_payload = weekly_goal(practice_events, obj["asOf"], target=weekly_target, zone=zone)
        if not effective_complete:
            weekly_payload["completedDays"] = None
        weekly = _decision({"namespaceId": scope["namespaceId"]}, ["optional_study_days_goal_no_carryover"],
            practice["sourceAttemptRevisions"], practice["dataNeeded"], observedOnly=not effective_complete, **weekly_payload)
    except ValueError as error:
        raise DomainInputError(str(error)) from error
    levels = _decision({"namespaceId": scope["namespaceId"]}, ["practice_level_separate_from_mastery"],
        practice["sourceAttemptRevisions"], practice["dataNeeded"], enabled=opts["levels"] and practice_enabled,
        previewStudyXp=practice["previewPracticeXp"] if opts["levels"] and practice_enabled else None,
        candidateLevel=practice["candidateLevel"] if opts["levels"] and practice_enabled else None,
        thresholds=practice["thresholds"], nextLevelAt=practice["nextLevelAt"], levelStep=practice["levelStep"], sharedFlightLabTotal=None)
    challenge = _challenge(obj.get("challenge"), opts["challenges"], scope, events, help_by_revision, complete, exam_verified, trusted)
    return {"format": "morrowdock-study-game-decision-v3", "ruleVersion": RULE_VERSION,
            "integrationEnabled": INTEGRATION_ENABLED, "asOf": obj["asOf"], "scope": scope,
            "skills": skill_results, "previewAwards": preview_awards, "xpAwarded": 0,
            "levels": levels, "missions": missions, "challenge": challenge, "returnPlan": return_plan,
            "practiceXp": practice, "weeklyGoal": weekly,
            "ignoredActivities": ignored, "dataNeeded": sorted(all_needed),
            "readiness": "not_established", "officialCourseworkSubmitted": False}


def _namespace_events(obj, namespace_id, complete):
    groups = {}
    for event in obj["events"]:
        routed = event.get("scope")
        if isinstance(routed, dict) and "namespaceId" in routed and routed["namespaceId"] != namespace_id:
            continue
        candidate = _scope(event.get("scope"))
        if candidate["namespaceId"] == namespace_id:
            key = json.dumps(candidate, sort_keys=True)
            groups.setdefault(key, (candidate, []))[1].append(event)
    events = []
    for candidate, rows in groups.values():
        normalized = _normalize({**obj, "scope": candidate, "events": rows, "historyComplete": complete})
        events.extend(_practice_rows(normalized[4]))
    return sorted(events, key=lambda e: (_time(e["occurredAt"]), json.dumps(e["scope"], sort_keys=True), e["sourceAttempt"]["attemptId"], e["sourceAttempt"]["revision"]))


def _challenge(spec, enabled, scope, events, help_by_revision, complete, exam_verified, trusted):
    if spec is None:
        return _decision(scope, ["challenges_are_opt_in"], enabled=enabled, status="not_selected", bonusXp=0)
    _object(spec, "challenge")
    _text(spec.get("id"), "challenge id")
    _text(spec.get("sessionId"), "challenge session")
    kind = _choice(spec.get("kind"), {"no_hint_set", "open_note_sprint", "transfer"}, "challenge kind")
    rows = [e for e in events if e["sessionId"] == spec["sessionId"]]
    required = _integer(spec.get("requiredFamilies", 10 if spec.get("preset") == "quiz_eve" else 2), "requiredFamilies", 1, 50)
    qualified, independently_checked, final_checked, owner_families = [], [], [], set()
    complete_responses, correct_responses, method_unverified = [], [], []
    # A finish before help remains a historical accomplishment. Help before
    # finishing cannot be erased by starting another attempt on that family.
    finished, family_help, latest = set(), {}, {}
    for event in rows:
        family = event["item"]["canonicalFamilyId"]
        latest[family] = event
        used, revealed, help_complete = help_by_revision[_source_key(event["sourceAttempt"])]
        old_used, old_revealed, old_complete = family_help.get(family, (set(), False, True))
        family_help[family] = old_used | used, old_revealed or revealed, old_complete and help_complete
        used, revealed, help_complete = family_help[family]
        allowed = {"notes"} if kind == "open_note_sprint" else set()
        if not (event["frozen"] and event["savedWorkNonempty"] and event.get("check") is not None and help_complete
                and not revealed and used <= allowed):
            continue
        if kind == "no_hint_set" and event["mode"] != "closed_note":
            continue
        if kind == "transfer" and not (event["context"]["kind"] in {"mixed", "transfer"}
                and len(set(event["context"]["skillIds"])) >= 2 and event["mode"] == "closed_note"):
            continue
        if family not in finished:
            qualified.append(event["sourceAttempt"])
            finished.add(family)
        if event["check"]["method"] == "owner_self_check":
            owner_families.add(family)
        if _verified(event, trusted) and event["check"]["outcome"] == "correct":
            independently_checked.append(event["sourceAttempt"])
        if _verified(event, trusted, "final_answer"):
            final_checked.append(event["sourceAttempt"])
            if event["item"].get("responseFormat", "show_work") == "show_work":
                method_unverified.append(event["sourceAttempt"])
        if _response_verified(event, trusted):
            complete_responses.append(event["sourceAttempt"])
            if event["check"]["outcome"] == "correct":
                correct_responses.append(event["sourceAttempt"])
    passed = enabled and complete and len(finished) >= required
    verified_families = {e["item"]["canonicalFamilyId"] for e in rows if e["sourceAttempt"] in independently_checked}
    final_families = {e["item"]["canonicalFamilyId"] for e in rows if e["sourceAttempt"] in final_checked}
    whole_verified = complete and exam_verified and len(verified_families) >= required
    complete_families = {e["item"]["canonicalFamilyId"] for e in rows if e["sourceAttempt"] in complete_responses}
    correct_families = {e["item"]["canonicalFamilyId"] for e in rows if e["sourceAttempt"] in correct_responses}
    response_verified = complete and exam_verified and len(correct_families) >= required
    tier = ("whole_solution_verified" if whole_verified else "complete_response_checked" if len(complete_families) >= required
            else "final_answer_checked" if len(final_families) >= required
            else "self_checked" if len(owner_families) >= required else "check_recorded") if passed else None
    needed = [] if passed else ["distinct_self_checked_families_matching_challenge_conditions"]
    if not complete:
        needed.append("complete_scope_attempt_history")
    if not exam_verified:
        needed.append("verified_exam_scope_revision")
    repairs = [e["sourceAttempt"] for e in latest.values() if e.get("check") and e["check"]["outcome"] in {"needs_review", "uncertain"}]
    return _decision(scope, ["optional_fixed_conditions_no_time_pressure_no_bonus_xp", "self_check_completion_does_not_verify_correctness"],
        [e["sourceAttempt"] for e in rows], needed, enabled=enabled, challengeId=spec["id"], kind=kind,
        status="complete" if passed else "in_progress" if enabled else "disabled",
        qualifyingSources=qualified, requiredFamilies=required, bonusXp=0,
        completionTier=tier,
        label={"self_checked": "Done under practice conditions · self-checked", "check_recorded": "Done under practice conditions · check recorded",
               "final_answer_checked": "Show-work final answers checked; methods not verified" if method_unverified else "Final-answer checks recorded",
               "complete_response_checked": "Complete responses independently checked",
               "whole_solution_verified": "Whole-solution evidence recorded"}.get(tier, "Practice at your pace"),
        wholeSolutionVerified=whole_verified,
        completeResponseVerified=response_verified, completeResponseCheckedSources=complete_responses,
        methodUnverifiedSources=method_unverified,
        finalAnswerCheckedSources=final_checked, independentlyCheckedSources=independently_checked,
        openRepairs=repairs, tomorrowRetrySuggested=bool(repairs) and spec.get("preset") == "quiz_eve")
