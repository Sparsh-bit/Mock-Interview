"""
Every prompt variable is supplied by every call site — tests/test_prompt_wiring.py

THE FAILURE THIS EXISTS TO CATCH IS SILENT, WHICH IS WHY IT NEEDS A TEST AT ALL.

`PromptBuilder.render` uses `string.Template.safe_substitute`. That choice is deliberate and
right — a prompt is a long document and a hard failure on one missing key would take an
interview down — but it means a variable the caller forgets is not an error. The literal
text `$question_mix` is sent to the model as part of the brief, inside a section headed
"How many questions of each kind". The model then does something reasonable with a document
that has a stray dollar-token in it, the interview runs, the logs are clean, and the only
symptom is that the interview is shaped wrongly.

That is exactly how this repo shipped the bug these tests were written alongside. Three
prompt files were edited to consume `$question_mix`, `$focus_directive` and
`$already_asked`; the call sites that had to supply them were written in a separate change
that did not land. Nothing failed. Nothing logged. `ruff`, `mypy` and 1207 tests all passed
against a prompt that was quietly half-connected.

HOW IT WORKS, AND WHY IT IS PARSED RATHER THAN LISTED. The obvious version of this test is a
hand-written dict of expected variables per template. That version rots: it passes after
somebody adds a variable to a template and forgets the call site, because the dict was not
updated either. So instead both halves are read from the source of truth —

  · the TEMPLATE's variables come from `string.Template.get_identifiers()` over the real
    .md file, so a new `$token` is picked up the moment it is written
  · the CALL SITE's keywords come from parsing the real Python with `ast`, so they cannot
    drift from what the service actually passes

— and the test asserts the second covers the first. Nobody has to remember anything.

TWO CONVENTIONS THIS RELIES ON, both already in the prompts:

  1. Header comments escape their dollars as `$$name`. `string.Template` reads `$$` as a
     literal `$`, so a documented variable is not mistaken for a required one. A prompt that
     documents `$company` unescaped in a comment would fail here, and the fix is to escape
     it — the comment is documentation, not a placeholder.
  2. A call site whose template name is not a literal string cannot be checked, so it is
     reported rather than skipped silently. There are none today.
"""

from __future__ import annotations

import ast
from pathlib import Path
from string import Template

import pytest

_APP = Path(__file__).resolve().parents[1] / "app"
_PROMPTS = _APP / "prompts"

#: Builder methods that take a template name and keyword substitutions.
#:
#: `chat_static` is included even though a static prompt is not meant to have variables:
#: if one ever gains a `$token`, the caller has no way to fill it and the token ships. A
#: failure here would be the correct alarm rather than a false one.
_BUILDER_METHODS = {"chat", "chat_static", "render", "build"}

#: Not a substitution — it is the channel the fenced ones arrive on, read separately by
#: `_fenced_keywords` below. Counting it as a template variable would report a surplus
#: `$untrusted` that no prompt declares.
#:
#: DELIBERATELY JUST THIS ONE. `system_template`, `user_content` and the rest are already
#: subtracted as `control` inside the surplus assertion, and removing them here as well
#: would move that knowledge to two places for no gain.
_CHANNEL_KEYWORDS = {"untrusted"}


def _fenced_keywords(call: ast.Call) -> set[str]:
    """
    The template variables a call site supplies through `untrusted={...}`.

    Only literal string keys are readable. A computed key would be a hole in this
    guarantee, so it is surfaced by `test_no_untrusted_mapping_is_built_dynamically`
    rather than quietly ignored.
    """
    for kw in call.keywords:
        if kw.arg == "untrusted" and isinstance(kw.value, ast.Dict):
            return {
                str(key.value)
                for key in kw.value.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
    return set()


def _untrusted_is_dynamic(call: ast.Call) -> bool:
    """True when `untrusted=` is passed as something other than a literal dict."""
    for kw in call.keywords:
        if kw.arg == "untrusted":
            if not isinstance(kw.value, ast.Dict):
                return True
            return any(
                not (isinstance(key, ast.Constant) and isinstance(key.value, str))
                for key in kw.value.keys
            )
    return False


#: Variables a template may leave to the caller's discretion, with the reason.
#:
#: Empty, and it should stay that way. It exists so that a future genuine exception is
#: recorded next to its justification rather than being handled by loosening the assertion.
_OPTIONAL: dict[tuple[str, str], str] = {}


def _template_variables(name: str) -> set[str]:
    """The `$tokens` a prompt file actually requires, `$$escapes` excluded."""
    for extension in (".md", ".txt", ".j2"):
        path = _PROMPTS / f"{name}{extension}"
        if path.exists():
            return set(Template(path.read_text(encoding="utf-8")).get_identifiers())
    raise AssertionError(f"prompt template {name!r} does not exist")


class _CallSite:
    __slots__ = ("file", "line", "template", "keywords")

    def __init__(self, file: str, line: int, template: str, keywords: set[str]) -> None:
        self.file = file
        self.line = line
        self.template = template
        self.keywords = keywords

    def __repr__(self) -> str:  # pragma: no cover - only ever read in a failure message
        return f"{self.file}:{self.line} -> {self.template}"


def _call_sites() -> tuple[list[_CallSite], list[str]]:
    """
    Every `prompt_builder.<method>(system_template=..., **kwargs)` in the app.

    Returns the checkable sites and, separately, the ones whose template name is not a
    literal and the ones whose `untrusted=` mapping is not a literal dict. Both extra lists
    are asserted empty rather than dropped: either is a hole in this guarantee, and a hole
    should have to be argued for.
    """
    sites: list[_CallSite] = []
    unresolvable: list[str] = []
    dynamic_untrusted: list[str] = []
    for path in sorted(_APP.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr not in _BUILDER_METHODS:
                continue
            keywords = {
                kw.arg
                for kw in node.keywords
                if kw.arg is not None and kw.arg not in _CHANNEL_KEYWORDS
            }
            # THE SECOND CHANNEL. Since the prompt-injection hardening, a candidate-
            # controlled variable is passed as `untrusted={"last_answer": ...}` rather than
            # as a plain keyword, so `PromptBuilder.chat` can fence it before substitution.
            # It is still a variable the call site supplies, and the whole point of this
            # file is that "supplied" is read from the real source rather than remembered —
            # so the dict's keys are read as keywords. Without this the nine call sites
            # that fence something would each report every fenced variable as missing AND
            # as an unknown extra, which is a false alarm in both directions.
            keywords |= _fenced_keywords(node)
            named = next(
                (kw for kw in node.keywords if kw.arg in {"system_template", "name", "template"}),
                None,
            )
            if named is None:
                continue
            rel = str(path.relative_to(_APP.parent))
            if not isinstance(named.value, ast.Constant) or not isinstance(named.value.value, str):
                unresolvable.append(f"{rel}:{node.lineno}")
                continue
            if _untrusted_is_dynamic(node):
                dynamic_untrusted.append(f"{rel}:{node.lineno}")
            sites.append(_CallSite(rel, node.lineno, named.value.value, keywords))
    return sites, unresolvable, dynamic_untrusted


_SITES, _UNRESOLVABLE, _DYNAMIC_UNTRUSTED = _call_sites()


def test_no_untrusted_mapping_is_built_dynamically():
    """
    `untrusted=` has to be a literal dict for the same reason a template name has to be a
    literal string: a computed mapping cannot be read from the source, so neither this file
    nor `test_prompt_injection.py` can tell which variables it fences. A hole in both
    guarantees at once should have to be argued for rather than appearing by accident.
    """
    assert not _DYNAMIC_UNTRUSTED, (
        "these call sites build `untrusted=` dynamically, so no test can check what they "
        f"fence: {_DYNAMIC_UNTRUSTED}"
    )


def test_the_parser_actually_found_the_call_sites():
    """
    Guards the guard. Every assertion below passes trivially against an empty list, so a
    renamed builder method or a moved package would silently disable all of them — which is
    the same class of mistake as the one being guarded against.
    """
    assert len(_SITES) >= 8, f"only found {len(_SITES)} prompt call sites — has the API changed?"
    templates = {site.template for site in _SITES}
    assert "interview_plan" in templates
    assert "cross_question" in templates


def test_every_template_name_is_a_literal():
    assert not _UNRESOLVABLE, (
        "these call sites name their template dynamically, so no test can check that they "
        f"supply its variables: {_UNRESOLVABLE}"
    )


@pytest.mark.parametrize("site", _SITES, ids=repr)
def test_every_call_site_supplies_every_variable_its_template_declares(site: _CallSite):
    """
    THE ONE THAT WOULD HAVE CAUGHT IT.

    A missing key is not an exception, it is a dollar-token in the brief. So the assertion
    has to be made here, statically, because there is no runtime moment at which anything
    goes wrong.
    """
    required = _template_variables(site.template)
    missing = {
        name
        for name in required - site.keywords
        if (site.template, name) not in _OPTIONAL
    }
    assert not missing, (
        f"{site.file}:{site.line} builds the {site.template!r} prompt without "
        f"{sorted(missing)}. safe_substitute will not raise — the literal text "
        f"'${sorted(missing)[0]}' is sent to the model inside the brief. Pass it, or record "
        f"it in _OPTIONAL with a reason."
    )


@pytest.mark.parametrize("site", _SITES, ids=repr)
def test_no_call_site_passes_a_variable_its_template_does_not_declare(site: _CallSite):
    """
    The other direction, and it is not pedantry. A keyword nothing consumes means either the
    prompt lost a section it was supposed to keep, or the caller is computing something
    expensive and throwing it away. Both have happened here; the second cost a paid AI call
    per interview for a block that was rendered and discarded.
    """
    # Not template variables — they are how the builder is told what to build.
    control = {"system_template", "name", "template", "user_content", "history", "images"}
    declared = _template_variables(site.template)
    surplus = site.keywords - declared - control
    assert not surplus, (
        f"{site.file}:{site.line} passes {sorted(surplus)} to the {site.template!r} prompt, "
        f"which declares no such variable. Either the prompt lost the section that used it, "
        f"or the caller is computing something nothing reads."
    )
