"""
Prompt Builder — prompt_builder.py

Constructs structured provider message lists from named prompt templates.
Uses Python's string.Template for variable substitution — intentionally simple.

Template variables use $variable or ${variable} syntax.
No logic in templates — only substitution.
"""

from __future__ import annotations

from string import Template
from typing import TYPE_CHECKING

from .base_provider import ProviderMessage

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
        **variables: str,
    ) -> list[ProviderMessage]:
        """
        Build a standard [system, user] message list.

        This is the canonical shape for single-turn interview evaluations.
        The system template sets the AI's persona and constraints;
        the user_content contains the candidate's answer or the task input.
        """
        system_content = self.render(system_template, **variables)
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
        return [
            # Loaded, NOT rendered. safe_substitute on a template with no variables
            # would be a no-op, but going through render() invites someone to pass a
            # variable later and break the byte-identity without noticing.
            ProviderMessage(role="system", content=self._loader.load(system_template)),
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
