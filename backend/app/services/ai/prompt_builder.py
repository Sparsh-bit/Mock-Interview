"""
Prompt Builder — prompt_builder.py

Constructs structured provider message lists from named prompt templates.
Uses Python's string.Template for variable substitution — intentionally simple.

Template variables use $variable or ${variable} syntax.
No logic in templates — only substitution.
"""

from __future__ import annotations

from collections.abc import Mapping
from string import Template
from typing import TYPE_CHECKING

from .base_provider import ProviderMessage
from .untrusted import contains_fence, fence, with_rule

if TYPE_CHECKING:
    from app.prompts.prompt_loader import PromptLoader


class PromptBuilder:
    """
    Builds ProviderMessage lists from named Markdown templates.

    The builder is the only component that knows how templates map to messages.
    Services call builder.chat() or builder.render(), never raw string formatting.

    Example:
        builder = PromptBuilder(loader)

        # Two-turn message list (most common for interview evaluation)
        messages = builder.chat(
            system_template="interviewer",
            user_content=candidate_answer,
            track_name="Cognizant Java FSE",
            topic_name="Java Collections",
            difficulty="medium",
        )

        # Raw rendered string (for system prompt inspection or logging)
        system_text = builder.render("interviewer", track_name="...", ...)
    """

    def __init__(self, loader: PromptLoader) -> None:
        self._loader = loader

    def render(self, template_name: str, **variables: str) -> str:
        """
        Render a named template with the given variables.
        Unknown variables are left as-is (safe_substitute).
        """
        raw = self._loader.load(template_name)
        return Template(raw).safe_substitute(**variables)

    def chat(
        self,
        system_template: str,
        user_content: str,
        *,
        untrusted: Mapping[str, str] | None = None,
        **variables: str,
    ) -> list[ProviderMessage]:
        """
        Build a standard [system, user] message list.

        This is the canonical shape for single-turn interview evaluations.
        The system template sets the AI's persona and constraints;
        the user_content contains the candidate's answer or the task input.

        `untrusted` IS THE TRUST BOUNDARY AND IT IS NOT OPTIONAL DECORATION. Values passed
        there are wrapped by `services/ai/untrusted.fence` before substitution, and the
        system message gains the rule that names a wrapped block as data. Values passed as
        plain `**variables` are spliced into the system prompt verbatim — which is correct
        for a track name out of the catalogue and is a prompt-injection hole for anything a
        candidate typed, because the system message is where the model's instructions live.

        Deciding which is which cannot be done here: `$topic` is a database row in the
        orchestrator and a candidate's typed phrase in the GD endpoint. So the call site
        declares it, and `tests/test_prompt_injection.py` parses the real source with `ast`
        to check every call site against a registry of candidate-controlled names. A new
        call site that passes one of them plainly fails that test.

        A fence is also attached when `user_content` itself is fenced — the resume analyser
        puts the whole resume in the user turn, which is the right role but still needs the
        rule to be present for the delimiter to mean anything.
        """
        fenced = {name: fence(name, value) for name, value in (untrusted or {}).items()}
        system_content = self.render(system_template, **variables, **fenced)
        if fenced or contains_fence(user_content):
            system_content = with_rule(system_content)
        return [
            ProviderMessage(role="system", content=system_content),
            ProviderMessage(role="user", content=user_content),
        ]

    def chat_static(
        self,
        system_template: str,
        user_content: str,
    ) -> list[ProviderMessage]:
        """
        Build [system, user] where the system block is the template VERBATIM.

        The point is that the system block comes out byte-identical on every call, which
        is what makes prompt caching pay: a cached prefix reads at 0.1x input instead of
        being re-charged in full. `chat()` cannot do this — it substitutes per-request
        variables INTO the system template, so no two calls share a prefix and a cache
        marker would bill a 1.25x write every time and never read.

        So everything that varies per request has to be in `user_content`. A template
        used here must contain no $variables at all; test_prompt_caching.py asserts that
        for every template a call site marks cacheable, because the failure is silent —
        the call still works, it just quietly costs 25% more forever.
        """
        # Loaded, NOT rendered. safe_substitute on a template with no variables
        # would be a no-op, but going through render() invites someone to pass a
        # variable later and break the byte-identity without noticing.
        system_content = self._loader.load(system_template)
        # THE RULE IS A CONSTANT, so prefixing it keeps the system block byte-identical
        # between calls and prompt caching still pays. It is attached only when the user
        # turn actually carries a fenced block: a template that never receives candidate
        # data should not spend the tokens, and a call site is consistent either way, so
        # this does not make the prefix vary within one call site.
        if contains_fence(user_content):
            system_content = with_rule(system_content)
        return [
            ProviderMessage(role="system", content=system_content),
            ProviderMessage(role="user", content=user_content),
        ]

    def append_assistant(
        self,
        messages: list[ProviderMessage],
        assistant_content: str,
    ) -> list[ProviderMessage]:
        """
        Append an assistant turn to extend a multi-turn conversation.

        Used by the Interview Orchestrator when building follow-up context:
            messages = builder.chat("interviewer", first_question, ...)
            messages = builder.append_assistant(messages, candidate_answer)
            messages = builder.append_user(messages, follow_up_question)
        """
        return [*messages, ProviderMessage(role="assistant", content=assistant_content)]

    def append_user(
        self,
        messages: list[ProviderMessage],
        user_content: str,
    ) -> list[ProviderMessage]:
        """Append a user turn to a multi-turn conversation."""
        return [*messages, ProviderMessage(role="user", content=user_content)]
