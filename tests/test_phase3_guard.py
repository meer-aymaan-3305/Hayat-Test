"""Phase 3 of IMPLEMENTATION.md: the claim check (G6), lists (G7) and varied openings."""

from hayat_backend.slots import SlotState
from hayat_backend.turn_guard import NO_SOURCE_LINE, check

KB = "Each programme lasts seven days: five days of retreat experiences. Destinations being explored include Spain and Japan."


def run(reply, user_text="tell me more", knowledge=KB, history=("Hello there.",), facts=None):
    return check(
        reply, user_text=user_text, plan=None, state=SlotState(facts or {}), focus=None, active=[],
        assistant_history=list(history), knowledge=knowledge, turn=3,
    )


def test_a_hospital_name_or_accreditation_with_no_source_is_removed():
    out = run("Happy to help with that. We work with Apollo Hospital in Chennai. Shall we carry on?")
    assert "Apollo" not in out.reply and "G6" in out.failures
    out = run("Good question. Our partner hospitals are JCI accredited. Anything else on your mind?")
    assert "JCI" not in out.reply and "G6" in out.failures


def test_facts_found_in_the_sources_are_kept():
    out = run("It lasts seven days in total. We are exploring places like Spain and Japan.")
    assert "Spain and Japan" in out.reply and "G6" not in out.failures
    out = run("A 7 night stay in Turkey is noted.", user_text="7 nights in Turkey please")
    assert "Turkey" in out.reply and "G6" not in out.failures


def test_when_every_fact_is_unsupported_hayat_says_she_does_not_have_it():
    out = run("Thanks for asking. The retreat is held at the Four Seasons Bali.")
    assert NO_SOURCE_LINE in out.reply


def test_a_list_becomes_one_flowing_sentence():
    out = run("It includes:\n- yoga\n- nutrition workshops\n- spa time", knowledge=KB + " the programme includes yoga, nutrition workshops and spa time")
    assert "\n" not in out.reply and "G7" in out.failures
    assert "yoga, nutrition workshops and spa time" in out.reply


def test_a_stock_opener_used_before_is_not_used_again():
    history = ["Got it, you're thinking about the retreat.", "Lovely, Spain is noted."]
    out = run("Got it, June works well for the retreat timing.", user_text="June", history=history)
    assert out.reply.startswith("June works well")
