"""
Event Bus — events/event_bus.py

In-process async pub/sub event bus for the interview platform.

Design principles:
  - Handlers NEVER crash the interview engine. Every handler invocation
    is wrapped in _safe_invoke which logs and swallows exceptions.
  - Handlers run concurrently via asyncio.gather for minimal latency impact.
  - The bus is an application-scoped singleton initialized at startup.
  - Replacing this with Redis pub/sub or Kafka requires only changing
    EventBus.publish() — no other code changes.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict
from collections.abc import Awaitable, Callable

import structlog

from .base import BaseEvent, EventType

logger = structlog.get_logger(__name__)

HandlerFn = Callable[[BaseEvent], Awaitable[None]]


class EventBus:
    """
    In-process async event bus.

    Handlers registered with subscribe() are called only for matching event types.
    Handlers registered with subscribe_all() receive every event (e.g., audit log).

    This implementation is suitable for a monolithic deployment.
    For microservices or high-throughput analytics, replace publish() with a
    Kafka/Redis producer while keeping the same handler registration API.
    """

    def __init__(self) -> None:
        self._handlers: dict[EventType, list[HandlerFn]] = defaultdict(list)
        self._global_handlers: list[HandlerFn] = []

    def subscribe(self, event_type: EventType, handler: HandlerFn) -> None:
        """Subscribe handler to a specific event type."""
        self._handlers[event_type].append(handler)
        logger.debug(
            "event_bus_subscribed",
            event_type=str(event_type),
            handler=handler.__qualname__,
        )

    def subscribe_all(self, handler: HandlerFn) -> None:
        """
        Subscribe handler to ALL event types.
        Use for cross-cutting concerns: audit logging, metrics, analytics.
        """
        self._global_handlers.append(handler)
        logger.debug("event_bus_subscribed_global", handler=handler.__qualname__)

    def unsubscribe(self, event_type: EventType, handler: HandlerFn) -> None:
        """Remove a specific handler subscription."""
        handlers = self._handlers.get(event_type, [])
        with contextlib.suppress(ValueError):
            handlers.remove(handler)  # no-op if the handler was never registered

    async def publish(self, event: BaseEvent) -> None:
        """
        Publish an event to all registered handlers.

        Handlers run concurrently. A failing handler NEVER prevents other
        handlers from running and NEVER propagates to the caller.
        """
        handlers: list[HandlerFn] = [
            *self._handlers.get(event.event_type, []),
            *self._global_handlers,
        ]

        if not handlers:
            logger.debug(
                "event_published_no_handlers",
                event_type=str(event.event_type),
                event_id=str(event.event_id),
            )
            return

        logger.debug(
            "event_published",
            event_type=str(event.event_type),
            event_id=str(event.event_id),
            handler_count=len(handlers),
        )

        # gather with return_exceptions=True ensures all handlers run
        # even if earlier ones fail
        await asyncio.gather(
            *[self._safe_invoke(handler, event) for handler in handlers],
            return_exceptions=True,
        )

    async def _safe_invoke(self, handler: HandlerFn, event: BaseEvent) -> None:
        """
        Call a handler, catching and logging any exception.
        The interview engine must never be disrupted by analytics failures.
        """
        try:
            await handler(event)
        except Exception:
            logger.exception(
                "event_handler_error",
                event_type=str(event.event_type),
                event_id=str(event.event_id),
                handler=handler.__qualname__,
            )


# ─── Application singleton ────────────────────────────────────────────────────

_event_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """
    FastAPI dependency — returns the application event bus.
    Raises RuntimeError if called before initialize_event_bus().
    """
    if _event_bus is None:
        raise RuntimeError(
            "EventBus has not been initialized. "
            "Call initialize_event_bus() in your FastAPI lifespan startup."
        )
    return _event_bus


def initialize_event_bus() -> EventBus:
    """
    Create and configure the application-scoped EventBus.

    Call once in FastAPI lifespan startup:
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            initialize_event_bus()
            yield
            # cleanup...

    Default handlers registered:
      - log_event_handler  → structured log for every event
      - persist_event_handler → writes to audit_logs table
    """
    global _event_bus  # noqa: PLW0603

    from .handlers import log_event_handler, persist_event_handler  # noqa: PLC0415

    bus = EventBus()
    bus.subscribe_all(log_event_handler)
    bus.subscribe_all(persist_event_handler)

    _event_bus = bus
    logger.info("event_bus_initialized", global_handler_count=2)
    return bus
