"""Deterministic auto-scoring for the patient-self-report outcome measures
(LEFS, QuickDASH, ODI, NDI, PSFS). TUG and BERG are excluded on purpose —
both require a clinician to time or observe the patient and can never be
"filled out" through the portal; they stay staff-entered via the existing
care/api/workflow_views.py:outcome_create path.

Each fixed-item measure ships an item catalog here (schema, for the portal
to render) and a scoring function (server-side, authoritative — the
frontend never computes a score). PSFS is structurally different — the
patient nominates their own activities rather than answering fixed items —
and is scored as a simple average of patient-supplied ratings.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from .models import OutcomeScore

PATIENT_SELF_REPORT_MEASURES = {
    OutcomeScore.Measure.LEFS,
    OutcomeScore.Measure.ODI,
    OutcomeScore.Measure.NDI,
    OutcomeScore.Measure.QUICK_DASH,
    OutcomeScore.Measure.PSFS,
}

_LEFS_ACTIVITIES = [
    "Any of your usual work, housework, or school activities",
    "Your usual hobbies, recreational or sporting activities",
    "Getting into or out of the bath",
    "Walking between rooms",
    "Putting on your shoes or socks",
    "Squatting",
    "Lifting an object, like a bag of groceries, from the floor",
    "Performing light activities around your home",
    "Performing heavy activities around your home",
    "Getting into or out of a car",
    "Walking 2 blocks",
    "Walking a mile",
    "Going up or down 10 stairs",
    "Standing for 1 hour",
    "Sitting for 1 hour",
    "Running on even ground",
    "Running on uneven ground",
    "Making sharp turns while running fast",
    "Hopping",
    "Rolling over in bed",
]
_LEFS_CHOICES = [
    {"value": 0, "label": "Extreme difficulty or unable to perform"},
    {"value": 1, "label": "Quite a bit of difficulty"},
    {"value": 2, "label": "Moderate difficulty"},
    {"value": 3, "label": "A little bit of difficulty"},
    {"value": 4, "label": "No difficulty"},
]

_QUICKDASH_ITEMS = [
    "Open a tight or new jar",
    "Do heavy household chores (e.g. wash walls, floors)",
    "Carry a shopping bag or briefcase",
    "Wash your back",
    "Use a knife to cut food",
    "Recreational activities in which you take some force or impact through your arm, shoulder, or hand",
    "Manage transportation needs (getting from one place to another)",
    "Sleeping, because of pain in your arm, shoulder, or hand",
    "During the past week, how much has arm, shoulder, or hand pain interfered with your normal social activities?",
    "During the past week, were you limited in your work or other regular daily activities because of your arm, shoulder, or hand problem?",
    "Please rate the severity of your arm, shoulder, or hand pain during the past week",
]
_QUICKDASH_CHOICES = [
    {"value": 1, "label": "No difficulty"},
    {"value": 2, "label": "Mild difficulty"},
    {"value": 3, "label": "Moderate difficulty"},
    {"value": 4, "label": "Severe difficulty"},
    {"value": 5, "label": "Unable"},
]

_ODI_SECTIONS = [
    {
        "key": "pain_intensity", "label": "Pain intensity", "choices": [
            "I have no pain at the moment.",
            "The pain is mild at the moment.",
            "The pain is moderate at the moment.",
            "The pain is fairly severe at the moment.",
            "The pain is very severe at the moment.",
            "The pain is the worst imaginable at the moment.",
        ],
    },
    {
        "key": "personal_care", "label": "Personal care (washing, dressing, etc.)", "choices": [
            "I can look after myself normally without causing extra pain.",
            "I can look after myself normally, but it is painful.",
            "It is painful to look after myself, and I am slow and careful.",
            "I need some help but manage most of my personal care.",
            "I need help every day in most aspects of self-care.",
            "I do not get dressed, wash with difficulty, and stay in bed.",
        ],
    },
    {
        "key": "lifting", "label": "Lifting", "choices": [
            "I can lift heavy weights without extra pain.",
            "I can lift heavy weights, but it gives extra pain.",
            "Pain prevents me from lifting heavy weights off the floor, but I can if conveniently placed.",
            "Pain prevents me from lifting heavy weights, but I can manage light to medium weights.",
            "I can lift only very light weights.",
            "I cannot lift or carry anything at all.",
        ],
    },
    {
        "key": "walking", "label": "Walking", "choices": [
            "Pain does not prevent me walking any distance.",
            "Pain prevents me walking more than 1 mile.",
            "Pain prevents me walking more than 1/2 mile.",
            "Pain prevents me walking more than 1/4 mile.",
            "I can only walk using a stick or crutches.",
            "I am in bed most of the time.",
        ],
    },
    {
        "key": "sitting", "label": "Sitting", "choices": [
            "I can sit in any chair as long as I like.",
            "I can only sit in my favorite chair as long as I like.",
            "Pain prevents me from sitting more than 1 hour.",
            "Pain prevents me from sitting more than 30 minutes.",
            "Pain prevents me from sitting more than 10 minutes.",
            "Pain prevents me from sitting at all.",
        ],
    },
    {
        "key": "standing", "label": "Standing", "choices": [
            "I can stand as long as I want without extra pain.",
            "I can stand as long as I want, but it gives extra pain.",
            "Pain prevents me standing for more than 1 hour.",
            "Pain prevents me standing for more than 30 minutes.",
            "Pain prevents me standing for more than 10 minutes.",
            "Pain prevents me from standing at all.",
        ],
    },
    {
        "key": "sleeping", "label": "Sleeping", "choices": [
            "My sleep is never disturbed by pain.",
            "My sleep is occasionally disturbed by pain.",
            "Because of pain I have less than 6 hours sleep.",
            "Because of pain I have less than 4 hours sleep.",
            "Because of pain I have less than 2 hours sleep.",
            "Pain prevents me from sleeping at all.",
        ],
    },
    {
        "key": "social_life", "label": "Social life", "choices": [
            "My social life is normal and gives me no extra pain.",
            "My social life is normal, but increases the degree of pain.",
            "Pain has no significant effect on my social life apart from limiting energetic interests.",
            "Pain has restricted my social life and I do not go out as often.",
            "Pain has restricted my social life to my home.",
            "I have hardly any social life because of pain.",
        ],
    },
    {
        "key": "traveling", "label": "Traveling", "choices": [
            "I can travel anywhere without pain.",
            "I can travel anywhere, but it gives extra pain.",
            "Pain is bad, but I manage journeys over two hours.",
            "Pain restricts me to journeys of less than one hour.",
            "Pain restricts me to short necessary journeys under 30 minutes.",
            "Pain prevents me from traveling except to receive treatment.",
        ],
    },
    {
        "key": "employment_homemaking", "label": "Employment / homemaking", "choices": [
            "My normal work/homemaking activities do not cause pain.",
            "My normal work/homemaking activities increase my pain, but I can still perform all that is required.",
            "I can perform most of my work/homemaking duties, but pain prevents more physically demanding tasks.",
            "Pain prevents me from doing anything but light duties.",
            "Pain prevents me from doing even light duties.",
            "Pain prevents me from doing any job or homemaking.",
        ],
    },
]

_NDI_SECTIONS = [
    {
        "key": "pain_intensity", "label": "Pain intensity", "choices": [
            "I have no pain at the moment.",
            "The pain is very mild at the moment.",
            "The pain is moderate at the moment.",
            "The pain is fairly severe at the moment.",
            "The pain is very severe at the moment.",
            "The pain is the worst imaginable at the moment.",
        ],
    },
    {
        "key": "personal_care", "label": "Personal care (washing, dressing, etc.)", "choices": [
            "I can look after myself normally without causing extra pain.",
            "I can look after myself normally, but it causes extra pain.",
            "It is painful to look after myself, and I am slow and careful.",
            "I need some help but manage most of my personal care.",
            "I need help every day in most aspects of self-care.",
            "I do not get dressed, wash with difficulty, and stay in bed.",
        ],
    },
    {
        "key": "lifting", "label": "Lifting", "choices": [
            "I can lift heavy weights without extra pain.",
            "I can lift heavy weights, but it gives extra pain.",
            "Pain prevents me from lifting heavy weights off the floor, but I can manage if conveniently positioned.",
            "Pain prevents me from lifting heavy weights, but I can manage light to medium weights.",
            "I can lift only very light weights.",
            "I cannot lift or carry anything at all.",
        ],
    },
    {
        "key": "reading", "label": "Reading", "choices": [
            "I can read as much as I want with no neck pain.",
            "I can read as much as I want with slight neck pain.",
            "I can read as much as I want with moderate neck pain.",
            "I cannot read as much as I want because of moderate neck pain.",
            "I can hardly read at all because of severe neck pain.",
            "I cannot read at all because of neck pain.",
        ],
    },
    {
        "key": "headaches", "label": "Headaches", "choices": [
            "I have no headaches at all.",
            "I have slight headaches, which come infrequently.",
            "I have moderate headaches, which come infrequently.",
            "I have moderate headaches, which come frequently.",
            "I have severe headaches, which come frequently.",
            "I have headaches almost all the time.",
        ],
    },
    {
        "key": "concentration", "label": "Concentration", "choices": [
            "I can concentrate fully when I want with no difficulty.",
            "I can concentrate fully when I want with slight difficulty.",
            "I have a fair degree of difficulty concentrating when I want.",
            "I have a lot of difficulty concentrating when I want.",
            "I have a great deal of difficulty concentrating when I want.",
            "I cannot concentrate at all.",
        ],
    },
    {
        "key": "work", "label": "Work", "choices": [
            "I can do as much work as I want.",
            "I can only do my usual work, but no more.",
            "I can do most of my usual work, but no more.",
            "I cannot do my usual work.",
            "I can hardly do any work at all.",
            "I cannot do any work at all.",
        ],
    },
    {
        "key": "driving", "label": "Driving", "choices": [
            "I can drive my car without any neck pain.",
            "I can drive my car as long as I want with slight neck pain.",
            "I can drive my car as long as I want with moderate neck pain.",
            "I cannot drive my car as long as I want because of moderate neck pain.",
            "I can hardly drive at all because of severe neck pain.",
            "I cannot drive my car at all.",
        ],
    },
    {
        "key": "sleeping", "label": "Sleeping", "choices": [
            "I have no trouble sleeping.",
            "My sleep is slightly disturbed (less than 1 hour sleepless).",
            "My sleep is mildly disturbed (1-2 hours sleepless).",
            "My sleep is moderately disturbed (2-3 hours sleepless).",
            "My sleep is greatly disturbed (3-5 hours sleepless).",
            "My sleep is completely disturbed (5-7 hours sleepless).",
        ],
    },
    {
        "key": "recreation", "label": "Recreation", "choices": [
            "I am able to engage in all my recreational activities with no neck pain at all.",
            "I am able to engage in all my recreational activities with some neck pain.",
            "I am able to engage in most, but not all, of my usual recreational activities because of neck pain.",
            "I am able to engage in only a few of my usual recreational activities because of neck pain.",
            "I can hardly do any recreational activities because of neck pain.",
            "I cannot do any recreational activities at all.",
        ],
    },
]


def outcome_measure_schema(measure: str) -> dict:
    """Rendering data for the portal — never used for scoring (that always
    happens server-side against the raw item_responses payload)."""
    if measure == OutcomeScore.Measure.LEFS:
        return {"kind": "items", "instructions": "Rate the difficulty performing each activity today.", "items": [
            {"key": f"item_{i}", "label": label, "choices": _LEFS_CHOICES} for i, label in enumerate(_LEFS_ACTIVITIES)
        ]}
    if measure == OutcomeScore.Measure.QUICK_DASH:
        return {"kind": "items", "instructions": "Rate your ability to do the following activities in the last week.", "items": [
            {"key": f"item_{i}", "label": label, "choices": _QUICKDASH_CHOICES} for i, label in enumerate(_QUICKDASH_ITEMS)
        ]}
    if measure == OutcomeScore.Measure.ODI:
        return {"kind": "sections", "instructions": "Choose the ONE statement in each section that best describes your condition today.", "sections": _ODI_SECTIONS}
    if measure == OutcomeScore.Measure.NDI:
        return {"kind": "sections", "instructions": "Choose the ONE statement in each section that best describes your condition today.", "sections": _NDI_SECTIONS}
    if measure == OutcomeScore.Measure.PSFS:
        return {
            "kind": "activities",
            "instructions": "List 1-5 activities you're having difficulty with because of your condition, and rate your current ability to do each one, from 0 (unable) to 10 (able to perform at the level you did before your injury or problem).",
        }
    return {"kind": "unsupported", "instructions": ""}


def _decimal(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def validate_outcome_responses(measure: str, item_responses: dict) -> dict[str, str]:
    """Required-field validation ahead of scoring. Scoring itself
    (score_outcome_measure) assumes valid input and should only be called
    after this returns no errors."""
    errors: dict[str, str] = {}
    if measure == OutcomeScore.Measure.LEFS:
        for i in range(len(_LEFS_ACTIVITIES)):
            key = f"item_{i}"
            value = item_responses.get(key)
            if value is None or not isinstance(value, int) or not (0 <= value <= 4):
                errors[key] = "Choose one option."
    elif measure == OutcomeScore.Measure.QUICK_DASH:
        for i in range(len(_QUICKDASH_ITEMS)):
            key = f"item_{i}"
            value = item_responses.get(key)
            if value is None or not isinstance(value, int) or not (1 <= value <= 5):
                errors[key] = "Choose one option."
    elif measure in (OutcomeScore.Measure.ODI, OutcomeScore.Measure.NDI):
        sections = _ODI_SECTIONS if measure == OutcomeScore.Measure.ODI else _NDI_SECTIONS
        for section in sections:
            value = item_responses.get(section["key"])
            if value is None or not isinstance(value, int) or not (0 <= value <= 5):
                errors[section["key"]] = "Choose one option."
    elif measure == OutcomeScore.Measure.PSFS:
        activities = item_responses.get("activities")
        if not isinstance(activities, list) or not (1 <= len(activities) <= 5):
            errors["activities"] = "List between 1 and 5 activities."
        else:
            for index, activity in enumerate(activities):
                name = activity.get("name") if isinstance(activity, dict) else None
                rating = activity.get("rating") if isinstance(activity, dict) else None
                if not isinstance(name, str) or not name.strip():
                    errors[f"activities.{index}.name"] = "Describe the activity."
                if not isinstance(rating, int) or not (0 <= rating <= 10):
                    errors[f"activities.{index}.rating"] = "Rate from 0 to 10."
    else:
        errors["measure"] = "This measure cannot be completed through the portal."
    return errors


def score_outcome_measure(measure: str, item_responses: dict) -> tuple[Decimal, Decimal]:
    """Returns (score, maximum_score). Call validate_outcome_responses first —
    this trusts its input is already well-formed."""
    if measure == OutcomeScore.Measure.LEFS:
        total = sum(item_responses[f"item_{i}"] for i in range(len(_LEFS_ACTIVITIES)))
        return _decimal(total), _decimal(len(_LEFS_ACTIVITIES) * 4)

    if measure == OutcomeScore.Measure.QUICK_DASH:
        n = len(_QUICKDASH_ITEMS)
        total = sum(item_responses[f"item_{i}"] for i in range(n))
        score = ((Decimal(total) / n) - 1) * 25
        return _decimal(score), _decimal(100)

    if measure in (OutcomeScore.Measure.ODI, OutcomeScore.Measure.NDI):
        sections = _ODI_SECTIONS if measure == OutcomeScore.Measure.ODI else _NDI_SECTIONS
        total = sum(item_responses[section["key"]] for section in sections)
        maximum_possible = len(sections) * 5
        score = (Decimal(total) / maximum_possible) * 100
        return _decimal(score), _decimal(100)

    if measure == OutcomeScore.Measure.PSFS:
        ratings = [activity["rating"] for activity in item_responses["activities"]]
        score = Decimal(sum(ratings)) / len(ratings)
        return _decimal(score), _decimal(10)

    raise ValueError(f"Unsupported measure for auto-scoring: {measure}")
