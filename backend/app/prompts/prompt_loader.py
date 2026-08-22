"""
Prompt Loader — prompts/prompt_loader.py

Dynamically loads AI prompt templates from the filesystem.

Priority order:
  1. File-based prompts in backend/app/prompts/*.md (version-controlled, preferred)
  2. DB-stored SystemPrompt records (admin-managed overrides, future use)

Templates use Python string.Template syntax: $variable or ${variable}.
The loader does NOT perform substitution — that is PromptBuilder's responsibility.

Caching:
  - File contents are cached in memory after first load.
  - Use reload() during development to pick up changes without restart.
  - The cache is bypassed in test environments (TESTING=true).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

# Default prompts directory — co-located with this file
_DEFAULT_PROMPTS_DIR = Path(__file__).parent
_SUPPORTED_EXTENSIONS = (".md", ".txt", ".j2")


class PromptLoader:
    """
    Loads and caches prompt templates from the filesystem.

    All AI prompt loading in the application goes through this class.
    Prompts are NEVER hardcoded inside service files.
    """

    def __init__(self, prompts_dir: Path = _DEFAULT_PROMPTS_DIR) -> None:
        self._dir = prompts_dir
        self._cache: dict[str, str] = {}
        self._testing = os.getenv("TESTING", "false").lower() == "true"

    def load(self, name: str) -> str:
        """
        Load a prompt template by name (filename without extension).

        Args:
            name: Template name, e.g. "interviewer", "report_generator"

        Returns:
            Raw template string (variables not yet substituted).

        Raises:
            FileNotFoundError: If no matching template file is found.
        """
        # Skip cache in test environments to prevent state leakage
        if not self._testing and name in self._cache:
            return self._cache[name]

        path = self._resolve_path(name)
        content = path.read_text(encoding="utf-8")

        if not self._testing:
            self._cache[name] = content

        logger.debug("prompt_loaded", name=name, path=str(path), chars=len(content))
        return content

    def reload(self, name: str) -> str:
        """
        Force reload from disk, bypassing the cache.
        Use during development to pick up prompt edits without restarting.
        """
        self._cache.pop(name, None)
        logger.info("prompt_cache_invalidated", name=name)
        return self.load(name)

    def reload_all(self) -> None:
        """Clear the entire prompt cache. All templates will be reloaded on next use."""
        count = len(self._cache)
        self._cache.clear()
        logger.info("prompt_cache_cleared", evicted=count)

    def exists(self, name: str) -> bool:
        """Check whether a prompt template file exists."""
        try:
            self._resolve_path(name)
            return True
        except FileNotFoundError:
            return False

    def list_prompts(self) -> list[str]:
        """Return names of all available prompt templates."""
        try:
            return sorted(
                p.stem
                for p in self._dir.iterdir()
                if p.is_file() and p.suffix in _SUPPORTED_EXTENSIONS
            )
        except FileNotFoundError:
            logger.warning("prompts_directory_not_found", dir=str(self._dir))
            return []
        except PermissionError:
            logger.warning("prompts_directory_permission_error", dir=str(self._dir))
            return []

    def _resolve_path(self, name: str) -> Path:
        """Find the prompt file, trying supported extensions in order."""
        for ext in _SUPPORTED_EXTENSIONS:
            path = self._dir / f"{name}{ext}"
            if path.exists():
                return path
        raise FileNotFoundError(
            f"Prompt template '{name}' not found in {self._dir}. "
            f"Tried extensions: {_SUPPORTED_EXTENSIONS}. "
            f"Available prompts: {self.list_prompts()}"
        )


@lru_cache(maxsize=1)
def get_prompt_loader() -> PromptLoader:
    """
    Returns the application-scoped PromptLoader singleton.
    FastAPI dependency — use via Depends(get_prompt_loader).
    """
    prompts_dir = Path(__file__).parent
    loader = PromptLoader(prompts_dir)
    logger.info(
        "prompt_loader_initialized",
        prompts_dir=str(prompts_dir),
        available=loader.list_prompts(),
    )
    return loader
