"""Pure capped Practice XP and behavior-completable cards, separate from mastery."""

from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import json


PRACTICE_RULE_VERSION = "study-practice-rules-v3"
LEVEL_STEP = 120


def next_ledger_mission(state, decision):
    """An actionable immediate step, alongside the stable daily mission cards."""
    candidates = []
    for skill in decision['skills']:
        by_item = {}
        for row in skill['evidenceTimeline']:
            source = row['sourceAttempt']
            by_item[(source['itemId'], source['itemVersion'])] = row
        for row in by_item.values():
            source = row['sourceAttempt']
            if row['outcome'] in {'needs_review', 'uncertain'}:
                kind, label, action, priority = 'fix_one', 'Fix one: save changed work and check it', 'attempt.create', 0
            elif row['outcome'] is None:
                kind, label, action, priority = 'check_one', 'Check your saved work', 'selfcheck.record', 1
            else:
                kind, label, action, priority = 'retrieve_one', 'Try one again from memory', 'attempt.create', 2
            candidates.append(((priority, row['savedAt'], source['attemptId']), {
                'kind': kind, 'label': label, 'action': action, 'itemId': source['itemId'],
                'itemVersion': source['itemVersion'], 'skillId': skill['skillId'],
                'sourceAttemptRevisions': [source], 'reasons': [
                    'latest_self_check_requires_repair' if priority == 0 else
                    'saved_revision_needs_check' if priority == 1 else 'self_check_is_not_independent_mastery']}))
    if candidates:
        mission = min(candidates, key=lambda candidate: candidate[0])[1]
    else:
        item = state['items'][0] if state['items'] else None
        mission = {'kind': 'practice_one' if item else 'add_problem',
                   'label': 'Save and check one attempt' if item else 'Add a practice problem',
                   'action': 'attempt.create' if item else 'item.save',
                   'itemId': item['itemId'] if item else None, 'itemVersion': item['version'] if item else None,
                   'skillId': item['skill'] if item else None, 'sourceAttemptRevisions': [],
                   'reasons': ['start_with_one_small_step']}
    from study_experience import copy as server_copy
    mission['label'] = server_copy({'fix_one': 'missionFix', 'check_one': 'missionCheck',
                                  'retrieve_one': 'missionRetrieve', 'practice_one': 'missionPractice',
                                  'add_problem': 'missionAdd'}[mission['kind']])
    return {'ruleVersion': PRACTICE_RULE_VERSION, 'scope': decision['scope'],
            'status': 'available', 'optional': True, 'itemLimit': 1, **mission}


def level_progress(total):
    """Preserve earned anchor levels, then continue every 120 XP without a cap."""
    thresholds = [0, 25, 60, 120]
    if total is None:
        return {"candidateLevel": None, "thresholds": thresholds, "nextLevelAt": None, "levelStep": LEVEL_STEP}
    while thresholds[-1] <= total:
        thresholds.append(thresholds[-1] + LEVEL_STEP)
    return {"candidateLevel": sum(total >= t for t in thresholds), "thresholds": thresholds,
            "nextLevelAt": next(t for t in thresholds if t > total), "levelStep": LEVEL_STEP}


def day_of(timestamp, zone="UTC"):
    try:
        tz = timezone.utc if zone == "UTC" else ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as error:
        raise ValueError("unsupported timeZone; supply an installed IANA zone, default UTC") from error
    pattern = "%Y-%m-%dT%H:%M:%S.%fZ" if "." in timestamp else "%Y-%m-%dT%H:%M:%SZ"
    return datetime.strptime(timestamp, pattern).replace(tzinfo=timezone.utc).astimezone(tz).date().isoformat()


def item_identities(events):
    """Union item versions and identical-content aliases across practice sets/tags."""
    parents = {}

    def find(key):
        parents.setdefault(key, key)
        root = key
        while parents[root] != root:
            root = parents[root]
        while parents[key] != key:
            next_key = parents[key]
            parents[key] = root
            key = next_key
        return root

    for event in events:
        course, source = event["scope"]["course"], event["sourceAttempt"]
        a = find((course, "item", source["itemId"]))
        b = find((course, "content", source["itemContentHash"]))
        parents[max(a, b)] = min(a, b)
    return {id(e): find((e["scope"]["course"], "item", e["sourceAttempt"]["itemId"])) for e in events}


def checked(event):
    return event["savedWorkNonempty"] and event["frozen"] and event.get("check") is not None


def clean(event):
    help_state = event.get("assistance")
    return bool(help_state and help_state["historyComplete"] and not help_state["used"] and not help_state["revealed"])


def repair_parent(event, indexed):
    """Both UI repair paths bind an earlier checked error in the same scope."""
    parent = event.get("correctionOf")
    partition = json.dumps(event["scope"], sort_keys=True)
    if parent is not None:
        return indexed.get((partition, parent["attemptId"], parent["revision"], parent["revisionHash"]))
    candidates = indexed.get(("attempt", partition, event.get("retryOf")), [])
    prior = None
    for candidate in candidates:
        if candidate["occurredAt"] > event["occurredAt"]:
            continue
        checks = [c for c in candidate.get("checkHistory", [candidate.get("check")])
                  if c and c["checkedAt"] <= event["occurredAt"]]
        if checks:
            prior = {**candidate, "check": max(checks, key=lambda c: (c["checkedAt"],
                {"correct": 0, "needs_review": 1, "uncertain": 2}[c["outcome"]]))}
    return prior if prior and prior["check"]["outcome"] in {"needs_review", "uncertain"} else None


def changed_correction(event, indexed):
    if not checked(event) or not event.get("workHash"):
        return False
    prior = repair_parent(event, indexed)
    return bool(prior and prior.get("workHash") and prior["workHash"] != event["workHash"]
                and any(c and c["outcome"] in {"needs_review", "uncertain"} for c in prior.get("checkHistory", [prior.get("check")])))


def source_index(events):
    result = {}
    for event in events:
        partition, source = json.dumps(event["scope"], sort_keys=True), event["sourceAttempt"]
        result[(partition, source["attemptId"], source["revision"], source["revisionHash"])] = event
        result.setdefault(("attempt", partition, source["attemptId"]), []).append(event)
    for key, value in result.items():
        if key[0] == "attempt":
            value.sort(key=lambda e: (e["occurredAt"], e["sourceAttempt"]["revision"]))
    return result


def practice_xp(events, namespace_id, as_of, *, complete=False, enabled=False, zone="UTC", daily_cap=25,
                confidence_checks=frozenset()):
    """Recomputed namespace projection. Never sum views or apply these as deltas."""
    today = day_of(as_of, zone)
    ids, indexed = item_identities(events), source_index(events)
    first_help = {}
    for event in events:
        if clean(event):
            continue
        key = ids[id(event)], day_of(event["occurredAt"], zone)
        at, source = event["occurredAt"], event["sourceAttempt"]
        if key not in first_help or at < first_help[key][0]:
            first_help[key] = at, {source["attemptId"]: source["revision"]}
        elif at == first_help[key][0]:
            revisions = first_help[key][1]
            revisions[source["attemptId"]] = min(revisions.get(source["attemptId"], source["revision"]), source["revision"])
    candidates, seen, earlier_days, needed, checked_attempts = [], set(), {}, set(), set()
    ordered = sorted(events, key=lambda e: (e.get("firstCheckedAt") or e["occurredAt"],
        e["scope"]["course"], e["sourceAttempt"]["itemId"], e["sourceAttempt"]["attemptId"], e["sourceAttempt"]["revision"]))

    def add(kind, points, event, day):
        identity = ids[id(event)]
        key = (kind, identity) if kind == "changed_work_rechecked" else (kind, identity, day)
        if key not in seen:
            seen.add(key)
            candidates.append({"kind": kind, "points": points, "day": day,
                "itemIdentity": list(identity), "sourceAttemptRevisions": [event["sourceAttempt"]],
                "sourceScope": event["scope"],
                "earnedAt": event.get("firstCheckedAt") or event["check"]["checkedAt"]})

    for event in ordered:
        if not checked(event):
            continue
        day, identity = day_of(event.get("firstCheckedAt") or event["check"]["checkedAt"], zone), ids[id(event)]
        attempt_key = event["scope"]["course"], event["sourceAttempt"]["attemptId"]
        first_check = attempt_key not in checked_attempts
        checked_attempts.add(attempt_key)
        checks = event.get("checkHistory", [event["check"]])
        first_policy = all(check["reference"] in confidence_checks for check in checks)
        if event["confidence"] is None and not first_policy:
            continue
        if first_check:
            add("worked_and_checked", 3, event, day)
            help_before = first_help.get((identity, day))
            first_check_at = event.get("firstCheckedAt") or event["check"]["checkedAt"]
            source = event["sourceAttempt"]
            earlier_help = help_before and (help_before[0] < first_check_at or
                (help_before[0] == first_check_at and (len(help_before[1]) > 1 or
                 source["attemptId"] not in help_before[1] or help_before[1][source["attemptId"]] <= source["revision"])))
            if event["mode"] == "closed_note" and clean(event) and not earlier_help:
                add("closed_note_discipline", 2, event, day)
        if changed_correction(event, indexed):
            add("changed_work_rechecked", 4, event, day)
        elif (event.get("correctionOf") or event.get("retryOf")) and not event.get("workHash"):
            needed.add("content_only_work_hashes_for_changed_correction")
        previous = earlier_days.get(identity, set())
        if first_check and day_of(event["occurredAt"], zone) == day and any(prior < day for prior in previous):
            add("later_day_return", 2, event, day)
        if first_check:
            earlier_days.setdefault(identity, set()).add(day)
    daily, receipts = {}, []
    for candidate in sorted(candidates, key=lambda c: (c["earnedAt"], c["itemIdentity"], c["kind"])):
        day = candidate["day"]
        award = min(candidate["points"], daily_cap - daily.get(day, 0))
        daily[day] = daily.get(day, 0) + award
        receipts.append({**candidate, "previewPracticeXp": award, "capped": award < candidate["points"],
                         "ruleVersion": PRACTICE_RULE_VERSION})
    if not complete:
        needed.add("complete_namespace_practice_history_across_all_courses_sets_and_exams")
    total = sum(daily.values()) if complete else None
    return {"ruleVersion": PRACTICE_RULE_VERSION, "scope": {"namespaceId": namespace_id},
        "enabled": enabled, "status": "preview" if complete else "history_incomplete",
        "previewPracticeXp": total, **level_progress(total), "dailyCap": daily_cap, "timeZone": zone,
        "daily": [{"day": day, "previewPracticeXp": points} for day, points in sorted(daily.items())] if complete else [],
        "receipts": receipts if complete else [], "dataNeeded": sorted(needed),
        "sourceAttemptRevisions": [r["sourceAttemptRevisions"][0] for r in receipts] if complete else [],
        "reasons": ["effort_projection_not_correctness_or_mastery", "one_namespace_level_no_set_or_tag_multiplier"],
        "display": {"visible": enabled, "label": "Practice", "canHide": True,
                    "message": "Full day of practice. Extra work is saved but adds no XP today."
                    if daily.get(today, 0) == daily_cap else "Practice saved."},
        "sharedFlightLabTotal": None, "xpAwarded": 0}


def day_plan_limit(events, as_of, limit=3, zone="UTC"):
    today = day_of(as_of, zone)
    previous = [day_of(e["occurredAt"], zone) for e in events if e["savedWorkNonempty"] and day_of(e["occurredAt"], zone) < today]
    returning = bool(previous) and (datetime.fromisoformat(today) - datetime.fromisoformat(max(previous))).days >= 2
    return min(1 if returning else 3, limit), returning


def missions(events, scope, as_of, *, enabled=False, rest=False, limit=3, zone="UTC"):
    """Plan only from pre-day history. Today's behavior changes completion only."""
    if not enabled or rest:
        return []
    today, indexed = day_of(as_of, zone), source_index(events)
    limit, _ = day_plan_limit(events, as_of, limit, zone)
    before = []
    for event in events:
        if not event["savedWorkNonempty"] or day_of(event["occurredAt"], zone) >= today:
            continue
        checks = [c for c in event.get("checkHistory", [event.get("check")]) if c and day_of(c["checkedAt"], zone) < today]
        before.append({**event, "check": max(checks, key=lambda c: (c["checkedAt"],
            {"correct": 0, "needs_review": 1, "uncertain": 2}[c["outcome"]])) if checks else None})
    identities = item_identities(before)
    groups = {}
    for event in before:
        groups.setdefault(identities[id(event)], []).append(event)
    targets = []
    for identity, rows in sorted(groups.items()):
        last = next((e for e in reversed(rows) if e.get("check")), rows[-1])
        check = last.get("check")
        repair = check and check["outcome"] in {"needs_review", "uncertain"}
        kind = "fix_one" if repair else "retrieve_one"
        priority = (0 if repair else 1,
                    0 if repair and last["confidence"] == "confident" else 1, last["occurredAt"], identity)
        targets.append((priority, identity, rows, {"ruleVersion": PRACTICE_RULE_VERSION, "scope": scope,
            "missionId": [today, list(identity), kind], "kind": kind, "skillId": last["item"]["skillId"],
            "itemId": last["sourceAttempt"]["itemId"], "status": "available",
            "label": "Fix one" if repair else "Retrieve one",
            "completionBasis": "saved_work_and_self_check_not_correctness", "optional": True, "itemLimit": 1,
            "dueCount": None, "reasons": ["one_card_is_a_good_day", "optional_suggestion_no_scheduler_write"],
            "plannedSourceAttemptRevisions": [last["sourceAttempt"]],
            "sourceAttemptRevisions": [last["sourceAttempt"]], "dataNeeded": []}))
    # Reserve room for a proposed handwriting exercise, even with a full history.
    selected = sorted(targets, key=lambda target: target[0])[:max(1, limit - 1)]
    cards = [target[3] for target in selected]
    if len(cards) < limit:
        for kind in ("hand_work_one", "practice_one"):
            if len(cards) == limit:
                break
            cards.append({"ruleVersion": PRACTICE_RULE_VERSION, "scope": scope,
                "missionId": [today, "any_new_problem", kind], "kind": kind, "skillId": None, "itemId": None,
                "target": "any_new_problem", "status": "available", "optional": True, "itemLimit": 1, "dueCount": None,
                "label": "Hand-work one: any new problem" if kind == "hand_work_one" else "Work one: another new problem",
                "completionBasis": "saved_work_and_self_check_not_correctness", "plannedSourceAttemptRevisions": [],
                "sourceAttemptRevisions": [], "reasons": ["one_card_is_a_good_day", "no_fabricated_item"], "dataNeeded": []})
    # Match today's work to identities frozen at planning time, so a new alias
    # or item cannot change the selected targets. One item can finish one card.
    old_items = {e["sourceAttempt"]["itemId"]: identity for _, identity, rows, _ in targets for e in rows}
    old_hashes = {e["sourceAttempt"]["itemContentHash"]: identity for _, identity, rows, _ in targets for e in rows}
    completion_identities = item_identities(events)
    prior_for_completion = {}
    for event in events:
        source = event["sourceAttempt"]
        prior = old_items.get(source["itemId"]) or old_hashes.get(source["itemContentHash"])
        if prior is not None:
            prior_for_completion.setdefault(completion_identities[id(event)], set()).add(prior)
    used = set()
    for event in sorted(events, key=lambda e: (e.get("firstCheckedAt") or e["occurredAt"], e["sourceAttempt"]["attemptId"], e["sourceAttempt"]["revision"])):
        if not checked(event) or day_of(event.get("firstCheckedAt") or event["check"]["checkedAt"], zone) != today:
            continue
        source = event["sourceAttempt"]
        token = completion_identities[id(event)]
        prior = prior_for_completion.get(token, set())
        identity = min(prior) if prior else None
        if token in used:
            continue
        for card in cards:
            if card["status"] == "complete":
                continue
            if card.get("target") == "any_new_problem":
                eligible = identity is None and (card["kind"] != "hand_work_one" or event.get("workKind") in {"scratch", "worksheet"})
            else:
                target = next(t for t in selected if t[3] is card)
                earlier_attempts = {e["sourceAttempt"]["attemptId"] for e in target[2]}
                eligible = identity == target[1] and (changed_correction(event, indexed) if card["kind"] == "fix_one" else
                    event["mode"] == "closed_note" and clean(event) and day_of(event["occurredAt"], zone) == today
                    and source["attemptId"] not in earlier_attempts)
            if eligible:
                card.update(status="complete", sourceAttemptRevisions=[source])
                used.add(token)
                break
    return cards


def weekly_goal(events, as_of, *, target=0, zone="UTC"):
    today = datetime.fromisoformat(day_of(as_of, zone)).date()
    start = (today - timedelta(days=6)).isoformat()
    days = sorted({day_of(e["check"]["checkedAt"], zone) for e in events if checked(e)
                   and start <= day_of(e["check"]["checkedAt"], zone) <= today.isoformat()})
    return {"enabled": target > 0, "targetDays": target, "completedDays": days,
            "message": "Choose study days and rest days that suit you.", "carryover": 0}
