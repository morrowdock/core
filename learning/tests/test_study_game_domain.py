"""Original synthetic evidence only; no course bank, profile or learner data."""

import ast
import copy
import hashlib
import itertools
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from study_game_domain import DomainInputError, INPUT_FORMAT, RULE_VERSION, evaluate as evaluate_untrusted
from study_game_verification import CheckAttestation, VerificationAuthority, evidence_binding


def evaluate(value):
    """Explicit trusted fixture registry, never used by the real evaluator default."""
    value = copy.deepcopy(value)
    value.setdefault("preferences", {}).setdefault("practiceXp", True)
    bindings = {evidence_binding(e): e for e in value["events"] if e.get("check") and
                e.get("item", {}).get("verification") == "verified" and
                e["check"]["method"] in {"deterministic", "rubric_review"}}
    authority = VerificationAuthority(tuple(CheckAttestation(binding, "whole_solution", "source_verified",
        "independent-original-synthetic-rubric") for binding in bindings))
    return evaluate_untrusted(value, authority=authority)


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def scope(**changes):
    return {"namespaceId": "synthetic-namespace", "course": "demo101", "assignment": "default",
            "examScope": None, **changes}


def attempt(name, day=1, family=None, skill="synthetic-motion", **changes):
    family = family or name
    source = {"attemptId": name, "revision": 2, "revisionHash": digest(name + ":revision2"),
              "itemId": family, "itemVersion": 1, "itemContentHash": digest(family + ":item1")}
    at = f"2030-06-{day:02d}T12:00:00Z"
    value = {"kind": "attempt", "eventId": "event-" + name, "scope": scope(), "occurredAt": at,
             "sourceAttempt": source,
             "item": {"canonicalFamilyId": family, "skillId": skill, "verification": "verified",
                      "sourceReference": "Original synthetic fixture; not course material",
                      "verificationReference": "synthetic-checker-fixture-v1"},
             "sessionId": "session-" + name, "retryOf": None, "correctionOf": None,
             "mode": "closed_note", "savedWorkNonempty": True, "frozen": True,
             "workHash": digest(name + ":work"), "workKind": "scratch",
             "confidence": "confident", "assistance": {"historyComplete": True, "used": [], "revealed": False},
             "context": {"kind": "single", "skillIds": [skill]},
             "check": {"method": "deterministic", "extent": "whole_solution", "outcome": "correct", "sourceAttempt": copy.deepcopy(source),
                       "reference": "original-synthetic-checker-v1", "checkedAt": at}}
    value.update(changes)
    return value


def request(events=(), **changes):
    return {"format": INPUT_FORMAT, "asOf": "2030-06-30T12:00:00Z", "scope": scope(),
            "historyComplete": True, "practiceHistoryComplete": True, "events": copy.deepcopy(list(events)), **changes}


def mixed(name="c", day=9, **changes):
    return attempt(name, day, context={"kind": "mixed", "skillIds": ["synthetic-motion", "synthetic-units"]}, **changes)


def revision(event, number, day):
    value = copy.deepcopy(event)
    value["eventId"] += "-revision-" + str(number)
    value["sourceAttempt"]["revision"] = number
    value["sourceAttempt"]["revisionHash"] = digest(value["eventId"])
    value["occurredAt"] = f"2030-06-{day:02d}T12:00:00Z"
    value["check"]["sourceAttempt"] = copy.deepcopy(value["sourceAttempt"])
    value["check"]["checkedAt"] = value["occurredAt"]
    return value


def stage(events, **changes):
    return evaluate(request(events, **changes))["skills"][0]["candidateStage"]


class MasteryEvidenceTests(unittest.TestCase):
    def test_no_activity_means_no_evidence_or_awards(self):
        events = [{"kind": kind, "eventId": kind, "scope": scope(), "occurredAt": "2030-06-01T12:00:00Z"}
                  for kind in ("upload", "ai_reply")]
        result = evaluate(request(events))
        self.assertEqual(result["skills"], [])
        self.assertEqual(result["previewAwards"], [])
        self.assertEqual(len(result["ignoredActivities"]), 2)

    def test_empty_saved_work_does_not_count(self):
        result = evaluate(request([attempt("a", savedWorkNonempty=False)]))
        self.assertEqual(result["skills"][0]["candidateStage"], "new")
        self.assertEqual(result["previewAwards"], [])

    def test_owner_selfcheck_is_practice_even_if_correct_and_confident(self):
        events = [attempt("a"), attempt("b", 2), mixed()]
        for event in events:
            event["check"]["method"] = "owner_self_check"
        result = evaluate(request(events))
        self.assertEqual(result["skills"][0]["candidateStage"], "practiced")
        self.assertIn("independent_check_bound_to_frozen_revision", result["dataNeeded"])
        self.assertEqual(result["previewAwards"], [])
        self.assertGreater(result["practiceXp"]["previewPracticeXp"], 0)

    def test_ai_judgment_cannot_be_a_check_method(self):
        event = attempt("a")
        event["check"]["method"] = "ai_reply"
        with self.assertRaises(DomainInputError):
            evaluate(request([event]))

    def test_two_days_then_later_mixed_context_can_establish_candidate_mastery(self):
        self.assertEqual(stage([attempt("a")]), "building")
        self.assertEqual(stage([attempt("a"), attempt("b", 2)]), "retained")
        result = evaluate(request([attempt("a"), attempt("b", 2), mixed()]))
        skill = result["skills"][0]
        self.assertEqual(skill["candidateStage"], "mastered")
        self.assertEqual(skill["evidence"]["laterMixedPractice"][0]["attemptId"], "c")
        self.assertEqual(result["readiness"], "not_established")
        self.assertEqual(skill["retentionForecast"], "not_established")
        self.assertFalse(result["officialCourseworkSubmitted"])
        self.assertEqual(result["xpAwarded"], 0)

    def test_one_sitting_and_early_recall_cannot_establish_retention(self):
        a, b = attempt("a"), attempt("b")
        self.assertEqual(stage([a, b, mixed(day=1)]), "building")
        b["occurredAt"] = b["check"]["checkedAt"] = "2030-06-02T11:59:59Z"
        self.assertEqual(stage([a, b]), "building")
        b["occurredAt"] = b["check"]["checkedAt"] = "2030-06-02T12:00:00Z"
        self.assertEqual(stage([a, b]), "retained")

    def test_mixed_threshold_requires_seven_full_days_and_two_skills(self):
        a, b, c = attempt("a"), attempt("b", 2), mixed(day=9)
        c["occurredAt"] = c["check"]["checkedAt"] = "2030-06-09T11:59:59Z"
        self.assertEqual(stage([a, b, c]), "retained")
        c["occurredAt"] = c["check"]["checkedAt"] = "2030-06-09T12:00:00Z"
        self.assertEqual(stage([a, b, c]), "mastered")
        c["context"]["skillIds"] = ["synthetic-motion"]
        self.assertEqual(stage([a, b, c]), "retained")

    def test_single_context_later_practice_is_not_transfer(self):
        self.assertEqual(stage([attempt("a"), attempt("b", 2), attempt("c", 15)]), "retained")

    def test_practicing_transfer_family_early_does_not_prevent_a_later_valid_check(self):
        events = [attempt("a"), attempt("b", 2), attempt("c", 3), mixed("later-c", 9, family="c", retryOf="c")]
        result = evaluate(request(events))
        self.assertEqual(result["skills"][0]["candidateStage"], "mastered")
        self.assertEqual(result["skills"][0]["evidence"]["laterMixedPractice"][0]["attemptId"], "later-c")

    def test_hints_reveals_notes_and_feedback_recorded_but_never_independent(self):
        for used, revealed in [(["hint"], False), (["worked_answer"], True), (["notes"], False),
                               (["external_feedback"], False), ([], True)]:
            with self.subTest(used=used, revealed=revealed):
                event = attempt("a", assistance={"historyComplete": True, "used": used, "revealed": revealed})
                skill = evaluate(request([event]))["skills"][0]
                self.assertEqual(skill["candidateStage"], "practiced")
                self.assertEqual(skill["assistanceRecorded"][0]["used"], used)
                self.assertEqual(skill["assistanceRecorded"][0]["revealed"], revealed)

    def test_assistance_is_sticky_across_revisions_and_cannot_be_erased(self):
        a = attempt("a", assistance={"historyComplete": True, "used": ["hint"], "revealed": True})
        b = revision(a, 3, 2)
        b["assistance"] = {"historyComplete": True, "used": [], "revealed": False}
        result = evaluate(request([b, a]))
        self.assertEqual(result["skills"][0]["candidateStage"], "practiced")
        self.assertTrue(result["skills"][0]["assistanceRecorded"][1]["revealed"])
        self.assertEqual(result["skills"][0]["assistanceRecorded"][1]["used"], ["hint"])

    def test_later_help_does_not_rewrite_an_earlier_frozen_independent_check(self):
        a = attempt("a")
        b = revision(a, 3, 2)
        b["assistance"]["used"] = ["hint"]
        evidence = evaluate(request([a, b]))["skills"][0]["evidence"]["independentRecall"]
        self.assertEqual(evidence, [a["sourceAttempt"]])

    def test_missing_help_or_incomplete_history_fail_closed_with_data_needed(self):
        for assistance in [None, {"historyComplete": False, "used": [], "revealed": False}]:
            result = evaluate(request([attempt("a", assistance=assistance)]))
            self.assertEqual(result["skills"][0]["candidateStage"], "practiced")
            self.assertIn("complete_assistance_and_reveal_history", result["dataNeeded"])
        result = evaluate(request([attempt("a"), attempt("b", 2), mixed()], historyComplete=False))
        self.assertEqual(result["skills"][0]["candidateStage"], "practiced")
        self.assertEqual(result["previewAwards"], [])
        self.assertIn("complete_scope_attempt_history", result["dataNeeded"])
        self.assertEqual(result["skills"][0]["evidence"]["firstAttempt"], [])

    def test_uncertain_wrong_low_confidence_open_notes_and_unfrozen_cannot_advance(self):
        for change in ("uncertain", "needs_review", "confidence", "mode", "frozen", "check"):
            with self.subTest(change=change):
                event = attempt("a")
                if change in {"uncertain", "needs_review"}:
                    event["check"]["outcome"] = change
                elif change == "confidence":
                    event["confidence"] = "unsure"
                elif change == "mode":
                    event["mode"] = "practice"
                elif change == "frozen":
                    event["frozen"] = False
                else:
                    event["check"] = None
                self.assertIn(stage([event]), {"practiced", "needs_review"})

    def test_checked_correction_is_distinct_from_independent_recall(self):
        wrong = attempt("wrong")
        wrong["check"]["outcome"] = "needs_review"
        correction = revision(wrong, 3, 2)
        correction["check"]["outcome"] = "correct"
        correction["correctionOf"] = copy.deepcopy(wrong["sourceAttempt"])
        correction["assistance"]["used"] = ["worked_answer"]
        result = evaluate(request([wrong, correction]))
        skill = result["skills"][0]
        self.assertEqual(skill["candidateStage"], "practiced")
        self.assertEqual(skill["evidence"]["corrections"], [correction["sourceAttempt"]])
        self.assertEqual(skill["evidence"]["independentRecall"], [])
        self.assertEqual(result["previewAwards"], [])

    def test_correction_must_reference_real_earlier_failed_revision(self):
        a = attempt("a")
        b = revision(a, 3, 2)
        b["correctionOf"] = copy.deepcopy(a["sourceAttempt"])
        for rows in ([b], [a, b]):
            with self.assertRaises(DomainInputError):
                evaluate(request(rows))
        a["check"]["outcome"] = "needs_review"
        b["correctionOf"]["revisionHash"] = digest("wrong")
        with self.assertRaises(DomainInputError):
            evaluate(request([a, b]))

    def test_unassisted_correction_still_cannot_be_independent_recall(self):
        wrong = attempt("wrong")
        wrong["check"]["outcome"] = "needs_review"
        correction = revision(wrong, 3, 2)
        correction["check"]["outcome"] = "correct"
        correction["correctionOf"] = copy.deepcopy(wrong["sourceAttempt"])
        self.assertEqual(stage([wrong, correction]), "practiced")

    def test_new_retry_id_immediately_after_help_is_not_recall(self):
        original = attempt("original", assistance={"historyComplete": True, "used": ["hint"], "revealed": False})
        retry = attempt("retry", family="original", retryOf="original")
        retry["occurredAt"] = retry["check"]["checkedAt"] = "2030-06-01T12:01:00Z"
        self.assertEqual(stage([original, retry]), "practiced")
        retry["occurredAt"] = retry["check"]["checkedAt"] = "2030-06-02T12:00:00Z"
        self.assertEqual(stage([original, retry]), "building")

    def test_correction_cannot_predate_the_error_check(self):
        original = attempt("original")
        original["check"]["outcome"] = "needs_review"
        original["check"]["checkedAt"] = "2030-06-03T12:00:00Z"
        correction = revision(original, 3, 2)
        correction["check"]["outcome"] = "correct"
        correction["correctionOf"] = copy.deepcopy(original["sourceAttempt"])
        with self.assertRaises(DomainInputError):
            evaluate(request([original, correction]))

    def test_new_error_prompts_repair_without_deducting_historical_awards(self):
        events = [attempt("a"), attempt("b", 2), mixed()]
        before = evaluate(request(events))
        wrong = attempt("error", 20)
        wrong["check"]["outcome"] = "needs_review"
        after = evaluate(request(events + [wrong]))
        self.assertEqual(after["skills"][0]["candidateStage"], "mastered")
        self.assertTrue(after["skills"][0]["needsReview"])
        self.assertEqual(after["previewAwards"], before["previewAwards"])


class IsolationAndReplayTests(unittest.TestCase):
    def test_scope_partitions_namespace_course_assignment_and_exam_revision(self):
        exam = {"id": "synthetic-exam", "revision": 1, "status": "verified", "sourceReference": "Synthetic scope"}
        variants = [scope(namespaceId="other"), scope(course="demo202"), scope(assignment="named"),
                    scope(examScope=exam), scope(examScope={**exam, "revision": 2})]
        own = attempt("same-id")
        for other_scope in variants:
            foreign = attempt("same-id", 2)
            foreign["scope"] = other_scope
            result = evaluate(request([own, foreign]))
            baseline = evaluate(request([own]))
            for field in ("skills", "missions", "challenge", "scope"):
                self.assertEqual(result[field], baseline[field])

    def test_tentative_content_can_be_practiced_without_verified_mastery(self):
        events = [attempt("a"), attempt("b", 2), mixed()]
        for event in events:
            event["item"]["verification"] = "tentative"
            event["item"].pop("verificationReference")
        result = evaluate(request(events))
        self.assertEqual(result["skills"][0]["candidateStage"], "practiced")
        self.assertIn("verified_content_and_source_reference", result["dataNeeded"])

    def test_tentative_exam_is_not_silently_verified_or_merged_with_course(self):
        exam = {"id": "demo-exam", "revision": 1, "status": "tentative", "sourceReference": "Synthetic owner report"}
        exam_scope = scope(examScope=exam)
        events = [attempt("a"), attempt("b", 2), mixed()]
        for event in events:
            event["scope"] = exam_scope
        result = evaluate(request(events, scope=exam_scope))
        self.assertEqual(result["scope"]["examScope"], exam)
        self.assertEqual(result["skills"][0]["candidateStage"], "practiced")
        self.assertIn("verified_exam_scope_revision", result["dataNeeded"])
        self.assertEqual(evaluate(request(events))["skills"], [])

    def test_duplicate_receipts_alias_ids_revisions_and_retries_cannot_farm(self):
        a = attempt("a")
        alias = {**copy.deepcopy(a), "eventId": "another-receipt"}
        repeats = [attempt(f"retry-{i}", day=2 + i, family="a", retryOf="a") for i in range(10)]
        result = evaluate(request([a, a, alias] + repeats))
        self.assertEqual(stage([a] + repeats), "building")
        self.assertEqual(result["previewAwards"], evaluate(request([a]))["previewAwards"])
        self.assertEqual(len(result["skills"][0]["sourceAttemptRevisions"]), 11)
        revisions = [revision(a, i + 3, i + 2) for i in range(10)]
        self.assertEqual(evaluate(request([a] + revisions))["previewAwards"], result["previewAwards"])

    def test_identical_content_renamed_as_new_family_or_skill_is_rejected(self):
        a, b = attempt("a"), attempt("b", 2)
        b["sourceAttempt"]["itemContentHash"] = a["sourceAttempt"]["itemContentHash"]
        b["check"]["sourceAttempt"] = copy.deepcopy(b["sourceAttempt"])
        with self.assertRaises(DomainInputError):
            evaluate(request([a, b]))

    def test_family_cannot_farm_another_skill_even_with_changed_content_hash(self):
        a, b = attempt("a"), attempt("b", 2, skill="other-skill")
        b["item"]["canonicalFamilyId"] = "a"
        with self.assertRaises(DomainInputError):
            evaluate(request([a, b]))

    def test_backdated_revision_order_is_rejected(self):
        a = attempt("a", 2)
        b = revision(a, 3, 1)
        with self.assertRaises(DomainInputError):
            evaluate(request([a, b]))

    def test_incomplete_empty_history_still_reports_missing_evidence(self):
        self.assertIn("complete_scope_attempt_history", evaluate(request(historyComplete=False))["dataNeeded"])

    def test_same_family_and_session_cannot_supply_delayed_diversity(self):
        a, b = attempt("a"), attempt("b", 2)
        b["sessionId"] = a["sessionId"]
        self.assertEqual(stage([a, b]), "building")
        self.assertEqual(stage([a, attempt("retry", 2, family="a", retryOf="a")]), "building")

    def test_reordered_history_and_replay_are_identical_and_input_is_unchanged(self):
        events = [attempt("a"), attempt("b", 2), mixed()]
        baseline = evaluate(request(events))
        for permutation in itertools.permutations(events):
            value = request(permutation)
            frozen = copy.deepcopy(value)
            self.assertEqual(evaluate(value), baseline)
            self.assertEqual(evaluate(value), baseline)
            self.assertEqual(value, frozen)

    def test_immutable_ids_and_exact_checked_revision_are_enforced(self):
        a = attempt("a")
        for change in ("event", "revision", "check", "item", "attempt"):
            b = copy.deepcopy(a)
            if change == "event":
                b["confidence"] = "unsure"
            elif change == "revision":
                b["eventId"] = "other-event"
                b["sourceAttempt"]["revisionHash"] = digest("other")
            elif change == "check":
                b["check"]["sourceAttempt"]["revision"] += 1
            elif change == "item":
                b = attempt("b", 2, family="a")
                b["sourceAttempt"]["itemContentHash"] = digest("different-content")
            else:
                b = revision(a, 3, 2)
                b["mode"] = "practice"
            with self.subTest(change=change), self.assertRaises(DomainInputError):
                evaluate(request([a, b]))

    def test_unknown_versions_bad_numbers_hashes_times_and_enums_are_rejected(self):
        cases = [request(format="future-version"), request(asOf="2030-06-30T12:00:00-04:00"),
                 request(asOf="2030-02-30T12:00:00Z"), request(historyComplete="yes"),
                 request(preferences={"dailyItemLimit": float("nan")}),
                 request(preferences={"dailyItemLimit": True}),
                 request(preferences={"levels": 1}), request(preferences={"randomReward": True}),
                 request(events=[attempt("a", occurredAt="2031-06-01T12:00:00Z")])]
        for field, value in (("revision", True), ("revisionHash", "not-a-hash"), ("itemVersion", 0)):
            event = attempt("a")
            event["sourceAttempt"][field] = value
            cases.append(request([event]))
        for value in cases:
            with self.subTest(value=value), self.assertRaises(DomainInputError):
                evaluate(value)

    def test_unrelated_future_features_are_disabled_by_default(self):
        result = evaluate(request([attempt("a")]))
        self.assertFalse(result["integrationEnabled"])
        self.assertEqual(result["missions"], [])
        self.assertFalse(result["levels"]["enabled"])
        self.assertIsNone(result["levels"]["candidateLevel"])
        self.assertIsNone(result["levels"]["sharedFlightLabTotal"])
        self.assertFalse(result["challenge"]["enabled"])

    def test_published_contract_example_and_policy_match_executable_rules(self):
        contract = json.loads((Path(__file__).resolve().parents[1] / "docs" / "STUDY-GAME-CONTRACT.json").read_text(encoding="utf-8"))
        result = evaluate(contract["exampleInput"])
        expected = contract["exampleExpected"]
        self.assertEqual(result["skills"][0]["candidateStage"], expected["candidateStage"])
        for key in ("integrationEnabled", "xpAwarded", "readiness"):
            self.assertEqual(result[key], expected[key])
        self.assertEqual(contract["ruleVersion"], result["ruleVersion"])
        self.assertEqual(result["practiceXp"]["previewPracticeXp"], expected["previewPracticeXp"])
        evidence = evaluate(request([attempt("a"), attempt("b", 2), mixed()], preferences={"levels": True}))
        self.assertEqual(evidence["previewAwards"], [])
        self.assertEqual(evidence["practiceXp"]["dailyCap"], contract["practiceXp"]["dailyCap"])

    def test_decisions_include_rule_scope_source_revisions_reasons_and_needed_data(self):
        result = evaluate(request([attempt("a")], preferences={"levels": True, "missions": True}))
        decisions = result["skills"] + result["previewAwards"] + result["missions"] + [result["levels"], result["challenge"], result["returnPlan"], result["weeklyGoal"]]
        for decision in decisions:
            self.assertIn(decision["ruleVersion"], {RULE_VERSION, "study-practice-rules-v3"})
            self.assertEqual(decision["scope"]["namespaceId"], scope()["namespaceId"])
            self.assertIn("sourceAttemptRevisions", decision)
            self.assertTrue(decision["reasons"])
            self.assertIn("dataNeeded", decision)


class OptionalGameTests(unittest.TestCase):
    def test_gentle_return_caps_plan_and_keeps_all_evidence_and_points(self):
        events = [attempt("a"), attempt("b", 2), mixed()]
        normal = evaluate(request(events, asOf="2030-06-09T12:00:00Z", preferences={"levels": True, "missions": True}))
        later = evaluate(request(events, preferences={"levels": True, "missions": True}))
        self.assertEqual(later["returnPlan"]["state"], "welcome_back")
        self.assertEqual(later["returnPlan"]["suggestedItemLimit"], 1)
        self.assertEqual(later["returnPlan"]["xpPenalty"], 0)
        self.assertEqual(later["previewAwards"], normal["previewAwards"])
        self.assertEqual(later["levels"], normal["levels"])
        self.assertEqual(later["skills"][0]["candidateStage"], "mastered")

    def test_rest_day_and_optional_flags_do_not_change_mastery_or_awards(self):
        event = attempt("a")
        baseline = evaluate(request([event]))
        rest = evaluate(request([event], preferences={"missions": True, "restDay": True}))
        self.assertEqual(rest["missions"], [])
        self.assertEqual(rest["returnPlan"]["suggestedItemLimit"], 0)
        self.assertEqual(rest["skills"], baseline["skills"])
        self.assertEqual(rest["previewAwards"], baseline["previewAwards"])

    def test_missions_are_bounded_repair_first_and_never_invent_due_counts(self):
        a, b, c = attempt("a", skill="a-skill"), attempt("b", skill="b-skill"), attempt("c", skill="c-skill")
        b["check"]["outcome"] = "needs_review"
        result = evaluate(request([a, b, c], asOf="2030-06-02T12:00:00Z",
                                 preferences={"missions": True, "dailyItemLimit": 2}))
        self.assertEqual(len(result["missions"]), 2)
        self.assertEqual(result["missions"][0]["kind"], "fix_one")
        self.assertEqual(result["missions"][0]["skillId"], "b-skill")
        self.assertTrue(all(m["optional"] and m["dueCount"] is None for m in result["missions"]))

    def test_levels_use_only_local_preview_points_and_never_actual_or_shared_xp(self):
        result = evaluate(request([attempt("a"), attempt("b", 2), mixed()], preferences={"levels": True}))
        self.assertEqual(result["levels"]["previewStudyXp"], 15)
        self.assertEqual(result["levels"]["candidateLevel"], 1)
        self.assertIsNone(result["levels"]["sharedFlightLabTotal"])
        self.assertEqual(result["xpAwarded"], 0)

    def challenge_result(self, events, kind="no_hint_set", enabled=True, **changes):
        events = copy.deepcopy(events)
        for event in events:
            event["sessionId"] = "challenge-session"
        return evaluate(request(events, preferences={"challenges": enabled},
            challenge={"id": "synthetic-challenge", "sessionId": "challenge-session", "kind": kind}, **changes))

    def test_no_hint_set_is_opt_in_distinct_checked_families_with_no_bonus(self):
        events = [attempt("a"), attempt("b")]
        result = self.challenge_result(events)
        self.assertEqual(result["challenge"]["status"], "complete")
        self.assertEqual(result["challenge"]["bonusXp"], 0)
        self.assertEqual(result["skills"][0]["candidateStage"], "building")
        self.assertEqual(self.challenge_result(events, enabled=False)["challenge"]["status"], "disabled")
        self.assertEqual(self.challenge_result([events[0], events[0]])["challenge"]["status"], "in_progress")

    def test_challenge_hint_or_reveal_or_latest_unchecked_revision_prevents_completion(self):
        a, b = attempt("a"), attempt("b")
        for field in ("hint", "reveal", "unchecked"):
            bad = copy.deepcopy(b)
            if field == "hint":
                bad["assistance"]["used"] = ["hint"]
            elif field == "reveal":
                bad["assistance"]["revealed"] = True
            else:
                bad = revision(b, 3, 2)
                bad["check"] = None
            rows = [a, b, bad] if field == "unchecked" else [a, bad]
            self.assertEqual(self.challenge_result(rows)["challenge"]["status"], "complete" if field == "unchecked" else "in_progress")

    def test_new_attempt_id_cannot_erase_hint_or_later_error_in_challenge(self):
        a, b = attempt("a"), attempt("b")
        b["assistance"]["used"] = ["hint"]
        retry = attempt("retry", 2, family="b", retryOf="b")
        self.assertEqual(self.challenge_result([a, b, retry])["challenge"]["status"], "in_progress")
        b["assistance"]["used"] = []
        retry["check"]["outcome"] = "needs_review"
        self.assertEqual(self.challenge_result([a, b, retry])["challenge"]["status"], "complete")
        self.assertEqual(len(self.challenge_result([a, b, retry])["challenge"]["openRepairs"]), 1)

    def test_open_note_challenge_accepts_notes_without_claiming_independent_mastery(self):
        events = [attempt("a", mode="practice"), attempt("b", mode="practice")]
        for event in events:
            event["assistance"]["used"] = ["notes"]
        result = self.challenge_result(events, kind="open_note_sprint")
        self.assertEqual(result["challenge"]["status"], "complete")
        self.assertEqual(result["skills"][0]["candidateStage"], "practiced")
        self.assertEqual(self.challenge_result(events)["challenge"]["status"], "in_progress")

    def test_transfer_challenge_requires_two_skills_and_matching_conditions(self):
        events = [mixed("a", 1), mixed("b", 1)]
        self.assertEqual(self.challenge_result(events, kind="transfer")["challenge"]["status"], "complete")
        events[1]["context"]["skillIds"] = ["synthetic-motion"]
        self.assertEqual(self.challenge_result(events, kind="transfer")["challenge"]["status"], "in_progress")

    def test_no_hidden_io_or_runtime_dependencies(self):
        module = Path(__file__).resolve().parents[1] / "study_game_domain.py"
        tree = ast.parse(module.read_text(encoding="utf-8"))
        imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        imports += [alias.name for n in ast.walk(tree) if isinstance(n, ast.Import) for alias in n.names]
        self.assertEqual(set(imports), {"copy", "datetime", "json", "re", "study_game_practice", "study_game_verification"})
        calls = [n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
        self.assertFalse({"open", "eval", "exec", "__import__", "print"} & set(calls))


if __name__ == "__main__":
    unittest.main()
