"""
Who the panel is actually talking to — tests/test_gd_panel.py

`addressed_candidate` is not a cosmetic flag. It drives the red "They're asking
you directly" banner, the floor countdown, the ignored-question counter, and
through that the candidate's engagement score. Getting it wrong in either
direction is a real cost: a false positive tells a candidate to answer a question
that was asked of Riya and then penalises the silence; a false negative lets a
direct question go by unmarked.

The prompt now instructs panelists to question each other by name ("Where's that
number from, though, Riya?"), so the old rule — any contribution ending in a
question mark — became wrong the moment those rules shipped.
"""

from app.api.v1.gd import (
    PANELIST_NAMES,
    _aimed_at_candidate,
    _candidate_name,
    _mentions,
    other_panelists,
)


def aimed(text: str, name: str = "Sparsh") -> bool:
    return _aimed_at_candidate(text, name, other_panelists(name))


class TestNameMatching:
    def test_matches_a_name_as_a_word(self):
        assert _mentions("Sparsh, what do you think?", "Sparsh")
        assert _mentions("I agree with sparsh on that", "Sparsh")

    def test_does_not_match_a_name_inside_another_word(self):
        # This is the whole reason _mentions exists. Short first names are the norm
        # in this user base and every one of them is a substring of a common word,
        # so a plain `in` test would fire on nearly every line the panel says.
        assert not _mentions("that came from the company report", "Om")
        assert not _mentions("that is the problem with remote work", "Om")
        assert not _mentions("she said the opposite", "Sai")
        assert not _mentions("my manager advised against it", "Ved")
        assert not _mentions("the criteria are different", "Ria")
        assert not _mentions("we should hire anyway", "Ani")

    def test_ignores_case_and_possessives(self):
        assert _mentions("SPARSH made that point", "Sparsh")
        # A possessive is still naming the person.
        assert _mentions("Riya, your point", "Riya")


class TestAimedAtCandidate:
    def test_a_question_naming_the_candidate_is_theirs(self):
        assert aimed("Sparsh, how would you handle that?")
        assert aimed("So do you agree with Arjun or with me, Sparsh?")

    def test_a_question_naming_another_panelist_is_NOT_theirs(self):
        # The failure this fixes. Rules 9 and 11 make these common, and every one
        # ends in a question mark.
        assert not aimed("Where's that number from, though, Riya?")
        assert not aimed("Arjun, that's pre-pandemic data, isn't it?")
        assert not aimed("Meera, do you actually believe that?")

    def test_an_unaddressed_second_person_question_is_theirs(self):
        # Panelists address each other by name, so a bare "you" with nobody named
        # is the candidate. This is what keeps the common invitation working.
        assert aimed("So what do you think?")
        assert aimed("You've been quiet — what's your view?")

    def test_a_statement_is_never_a_question_however_pointed(self):
        assert not aimed("Sparsh's point about cost is the real argument here.")
        assert not aimed("That kills your argument, Arjun.")

    def test_a_rhetorical_question_with_nobody_in_it_is_not_theirs(self):
        # No name, no second person: the panel is thinking aloud at each other.
        assert not aimed("But is that actually true of smaller teams?")
        assert not aimed("Where does that leave the freshers?")

    def test_a_candidate_with_no_usable_name_still_gets_asked_things(self):
        # _candidate_name falls back to a phrase no panelist will ever utter, so the
        # name branch simply never matches and the second-person branch carries it.
        # Without this the whole fallback would be silently dead.
        fallback = _candidate_name("")
        assert not _aimed_at_candidate(
            "Where's that from, Riya?", fallback, other_panelists(fallback)
        )
        assert _aimed_at_candidate(
            "So what would you do?", fallback, other_panelists(fallback)
        )

    def test_a_candidate_sharing_a_panelist_name_is_not_excluded(self):
        # A real user called Riya must still be recognised when addressed, and
        # "Riya" must not simultaneously count as another panelist.
        others = other_panelists("Riya")
        assert "Riya" not in others
        assert _aimed_at_candidate("Riya, what do you think?", "Riya", others)


class TestPanelIntegrity:
    def test_the_panel_has_the_names_the_prompt_and_the_client_expect(self):
        # The roster is one definition, served to the client and interpolated into
        # the prompt. A drift here means a panelist speaks in the wrong voice or a
        # contribution from an unknown speaker is silently dropped.
        assert PANELIST_NAMES == ["Riya", "Arjun", "Meera"]

    def test_candidate_name_is_reduced_to_something_speakable(self):
        assert _candidate_name("Sparsh Sharma") == "Sparsh"
        assert _candidate_name("  priya  ") == "priya"
        assert _candidate_name("") == "the candidate"
        assert _candidate_name("123") == "the candidate"


class TestTheNameIsNotSaidEveryTurn:
    """
    "does not take the name of the user in every argument".

    THE MODEL CANNOT DECIDE THIS AND MUST NOT BE ASKED TO. Every GD turn is a separate
    stateless call with no memory of the previous one, so a prompt rule like "use their
    name when you bring them in, then leave it alone" is unfollowable — there is no way for
    the model to know whether the last turn used it. gd_panel.md carried exactly that rule
    and the panel still said the name constantly, which is the same failure the interview
    panel already had and already fixed server-side (_should_use_name in api/v1/panel.py).

    A GD round is 26 turns against an interview's dozen, so the same one-in-three rhythm
    would still say their name seven times in eight minutes. Hence one in four.
    """

    def _req(self, **over):
        from app.api.v1.gd import GDTurnRequest

        base = {"topic": "Remote work", "history": [], "phase": "discussion"}
        base.update(over)
        return GDTurnRequest(**base)

    def _turn(self, n: int, **over):
        from app.api.v1.gd import Turn

        history = [Turn(speaker="Riya", text=f"point {i}") for i in range(n)]
        return self._req(history=history, **over)

    def test_the_opening_always_uses_it(self):
        from app.api.v1.gd import _should_use_name

        assert _should_use_name(self._req(phase="opening"))
        # An empty transcript is an opening whatever the phase says.
        assert _should_use_name(self._req(phase="discussion", history=[]))

    def test_it_is_not_used_on_most_turns(self):
        from app.api.v1.gd import _should_use_name

        used = sum(1 for n in range(1, 27) if _should_use_name(self._turn(n)))
        # 26 turns is a full round. Anything approaching half is the reported complaint.
        assert used <= 8, f"the panel would say their name {used} times in one round"
        assert used >= 4, "never using it is its own failure — nobody brings them in"

    def test_being_put_on_the_spot_always_uses_it(self):
        # Turning to somebody by name IS how a person does this, so the rhythm yields here.
        from app.api.v1.gd import _should_use_name

        assert _should_use_name(self._turn(7, awaiting_candidate=True))
        assert _should_use_name(self._turn(7, ignored_questions=2))

    def test_the_instruction_is_explicit_in_both_directions(self):
        from app.api.v1.gd import _name_instruction

        yes = _name_instruction(self._req(phase="opening"))
        no = _name_instruction(self._turn(7))
        assert yes.startswith("YES")
        assert no.startswith("NO")
        # Naming other panelists must stay encouraged — it is how a listener follows who is
        # answering whom, and a blanket "no names" would flatten the round.
        assert "OTHER PANELISTS" in no

    def test_the_brief_carries_the_decision(self):
        from app.api.v1.gd import _round_brief

        assert "Using their name this turn" in _round_brief(self._turn(7))

    def test_the_prompt_defers_to_the_server(self):
        import pathlib

        prompt = (
            pathlib.Path(__import__("app").__file__).parent / "prompts/gd_panel.md"
        ).read_text()
        assert "Using their name this turn" in prompt
        assert "INSTRUCTION, not a" in prompt
