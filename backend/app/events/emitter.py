"""
Event Emitter — events/emitter.py

Thin dependency-injected wrapper around EventBus for use in services.

Why a wrapper instead of using EventBus directly?
  - EventBus is an infrastructure concern; EventEmitter is an application concern.
  - Services depend on EventEmitter, not EventBus — easier to mock in tests.
  - If we switch from in-process to Redis pub/sub, only EventEmitter.emit() changes.
  - Provides a clean emit_many() for batch event dispatch.
"""

from __future__ import annotations

from fastapi import Depends

from .base import BaseEvent
from .event_bus import EventBus, get_event_bus


class EventEmitter:
    """
    Application-layer event emitter used by all services.

    Services receive this via FastAPI DI and call emit() to publish events.
    The EventBus handles dispatch, fan-out, and error isolation.

    Example — in an interview service:
        class InterviewService:
            def __init__(
                self,
                emitter: EventEmitter = Depends(get_event_emitter),
            ):
                self._emitter = emitter

            async def start_session(self, ...) -> InterviewSession:
                session = await self._create_session(...)

                await self._emitter.emit(
                    InterviewStartedEvent(
                        user_id=user_id,
                        session_id=session.id,
                        payload=InterviewStartedPayload(
                            track_id=track_id,
                            track_name=track.name,
                            mode=mode,
                        ),
                    )
                )
                return session
    """

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus

    async def emit(self, event: BaseEvent) -> None:
        """
        Emit a single event to all registered handlers.

        Non-blocking — returns as soon as all handlers have been dispatched.
        Handler failures are caught by the bus and never propagate here.
        """
        await self._bus.publish(event)

    async def emit_many(self, events: list[BaseEvent]) -> None:
        """
        Emit multiple events in order.

        Events are published sequentially to preserve causal ordering.
        Use this when multiple things happen as a result of one action,
        e.g., [AnswerSubmittedEvent, AnswerEvaluatedEvent].
        """
        for event in events:
            await self._bus.publish(event)


def get_event_emitter(bus: EventBus = Depends(get_event_bus)) -> EventEmitter:
    """FastAPI dependency factory for EventEmitter."""
    return EventEmitter(bus)
