"""Weekday and date pairs checked against the calendar. Synthetic text only."""

from datetime import UTC, datetime

from proxenos import dates
from proxenos.clones import work

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)  # a Thursday


def test_a_prompt_gets_today_and_the_next_fourteen_days_with_their_weekdays():
    text = dates.today(NOW)

    assert text.startswith("Today is Thursday 2026-11-05.\n")
    rows = [line for line in text.splitlines() if line.startswith("- ")]
    assert len(rows) == 14
    assert rows[0] == "- Thursday 2026-11-05, 5 November, today"
    assert rows[1] == "- Friday 2026-11-06, 6 November"
    assert work._today(NOW) == text  # every work prompt starts with it


def test_the_pair_the_model_got_a_day_off_is_asked_about_naming_both_readings():
    body = "I can do Thursday, November 6th or Friday, November 7th."

    fixed, asks, logs = dates.check(body, NOW)

    assert fixed == body and logs == []
    assert len(asks) == 2
    assert "Friday, November 6, 2026 or Thursday, November 5, 2026" in asks[0]
    assert "Saturday, November 7, 2026 or Friday, November 6, 2026" in asks[1]


def test_every_way_of_writing_a_pair_is_read_and_the_right_ones_pass():
    for wrong in ("Thu 6 Nov", "Thursday the 6th of November", "Nov 6 (Thu)", "THU, 6 NOV."):
        assert len(dates.check(f"See you {wrong}", NOW)[1]) == 1, wrong
    for right in ("Fri 6 Nov", "Friday, November 6th", "Nov 6 (Fri)", "Thursday 5 Nov 2026"):
        assert dates.check(f"See you {right}", NOW) == (f"See you {right}", [], []), right
    assert dates.check("at 10 on Thursday, 6 people came", NOW)[1] == []  # no month, no pair
    assert dates.check("Thursday, February 30", NOW)[1] == []  # not a date at all


def test_a_year_written_is_the_year_used_and_without_one_the_next_occurrence():
    assert dates.check("Friday, November 6, 2026", NOW)[1] == []
    # In 2025 it was a Thursday, and the Friday nearest has passed: a correction, not a question.
    assert dates.check("Friday, November 6, 2025", NOW)[0] == "Thursday, November 6, 2025"
    # Monday, March 2 fell on a Monday this year and is in the past; read for 2027 it's a Tuesday.
    assert len(dates.check("Monday, March 2", NOW)[1]) == 1
    recently = datetime(2026, 3, 10, 12, tzinfo=UTC)
    assert dates.check("Monday, March 2", recently)[1] == []  # the one just gone, a week ago


def test_when_only_the_weekday_can_be_wrong_it_is_corrected_in_place_and_logged():
    # November 3rd, 2026 was a Tuesday; the Wednesday nearest, the 4th, has passed.
    text = "We met Wed 3 Nov 2026 and WEDNESDAY, November 3, 2026."

    fixed, asks, logs = dates.check(text, NOW)

    assert fixed == "We met Tue 3 Nov 2026 and TUESDAY, November 3, 2026."
    assert asks == [] and len(logs) == 2 and "Tuesday" in logs[0]


def test_the_work_clone_puts_the_questions_first_in_a_drafts_asks():
    job = {"id": "reply-1", "for": "reply", "title": "T", "chat": None}
    answer = {
        "title": "T",
        "kind": "reply",
        "channel": "email",
        "to": "Ana",
        "body": "Thursday, November 6th works.",
        "asks": ["Which room?"],
    }

    draft = work._draft(job, answer, NOW)

    assert draft["body"] == "Thursday, November 6th works."
    assert len(draft["asks"]) == 2 and draft["asks"][0].startswith('You wrote "Thursday')
    assert draft["asks"][1] == "Which room?"


def test_a_status_never_calls_something_done_on_a_day_that_hasnt_come():
    text = (
        "Consultation completed (30 Nov), kickoff Done on 12 Dec 2026. Completed 2 Nov. "
        "Still to be done by 1 Dec, and it will be completed 3 Dec."
    )

    fixed, logs = dates.scheduled(text, NOW)

    assert fixed == (
        "Consultation scheduled for 30 Nov, kickoff Scheduled for 12 Dec 2026. Completed 2 Nov. "
        "Still to be done by 1 Dec, and it will be completed 3 Dec."
    )
    assert len(logs) == 2
