"""
Deck review — api/v1/deck.py

One endpoint: upload a pitch deck, get it scored against the rubric in
`services/deck/criteria.py`. Nothing is stored. The evaluation is returned and forgotten.

## Why nothing is stored

A deck is the candidate's idea, which is the most commercially sensitive thing this product
could hold, and there is no feature that needs it later — unlike a resume, which
personalises every subsequent interview. Storing it would mean a retention policy, a
deletion path, a row in the data-rights export and a line in the privacy notice, all to
support no behaviour. The scored result goes to the browser and the bytes are dropped.

## The order of operations, which is load-bearing

  consent -> size -> bytes -> file safety -> CHARGE -> evaluate

The charge is second-to-last on purpose. Everything before it is a refusal the candidate
should not pay for: no consent, too large, not a deck, carries a macro. Everything after it
is the expensive part. And `consume` deliberately does not commit — `get_db` commits on
success and rolls back on any exception — so a failed evaluation undoes the charge rather
than selling a review that never happened.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.core.config import settings
from app.core.rate_limit import rate_limiter
from app.core.security import CurrentUser
from app.db.redis import CacheKeys
from app.db.session import AsyncSession, get_db
from app.services.billing.credits import consume
from app.services.deck import DeckEvaluation, DeckEvaluator, DeckExtractionError
from app.services.resume.file_safety import DECK_KINDS, UnsafeDocument, verify

logger = structlog.get_logger(__name__)

router = APIRouter()

#: Shares the AI request budget with the other upload paths — a deck review is one vision
#: call plus one judging call, which is the same order of cost as a resume analysis.
_deck_upload_rate_limit = rate_limiter(
    limit=settings.RATE_LIMIT_AI_REQUESTS_PER_MINUTE,
    window_seconds=60,
    key_builder=lambda user_id: CacheKeys.rate_limit_ai(user_id),
    action="reviewing a deck",
)


@router.post(
    "/review",
    response_model=DeckEvaluation,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(_deck_upload_rate_limit)],
)
async def review_deck(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
) -> DeckEvaluation:
    """
    Score an uploaded pitch deck.

    Accepts a `.pptx` or a PDF export of one, up to `DECK_MAX_UPLOAD_SIZE_MB`.

    Costs one deck review from the candidate's balance. Nothing is stored.

    Status codes, each meaning one thing:

      402  no deck reviews left.
      413  the file is over the size ceiling.
      415  the bytes are not a presentation or a PDF, or they carry active content.
      422  the file is a deck but nothing could be read out of it — a scan, or an
           encrypted export. No charge is kept.
      428  the deck-processing disclosure has not been agreed to yet.
    """
    from app.api.v1.legal import require_consent  # noqa: PLC0415
    from app.models.consent import PURPOSE_DECK_PROCESSING  # noqa: PLC0415

    # ── CONSENT BEFORE BYTES ─────────────────────────────────────────────────
    #
    # First statement in the handler, matching the resume upload. The deck's text and its
    # rendered slides are sent to a model provider outside India, and §5 wants that said
    # before it happens rather than after. A separate purpose from the resume's: see
    # models/consent.py for why agreeing to one is not agreeing to the other.
    await require_consent(
        db,
        current_user.user_id,
        PURPOSE_DECK_PROCESSING,
        what=(
            "Before your first deck review, please read what happens to your slides "
            "and who processes them."
        ),
    )

    filename = (file.filename or "deck").strip()[:255]
    log = logger.bind(user_id=str(current_user.user_id), filename=filename)

    # ── SIZE, FROM THE BYTES WE ACTUALLY READ ────────────────────────────────
    #
    # `file.size` is the client's claim and `content-length` is a header; neither bounds
    # what a body can send. Read with a ceiling and refuse on what arrived. One extra byte
    # is requested so a file exactly at the limit passes and one over it does not.
    ceiling = settings.deck_upload_size_bytes
    data = await file.read(ceiling + 1)
    if len(data) > ceiling:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=(
                f"That deck is larger than {settings.DECK_MAX_UPLOAD_SIZE_MB} MB. "
                "Compress the images or export it as a PDF."
            ),
        )
    if not data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="That file is empty.",
        )

    # ── WHAT THE BYTES ACTUALLY ARE ──────────────────────────────────────────
    #
    # `allowed=DECK_KINDS` so a Word document is refused here rather than reaching a
    # parser that would fail on it later. The same archive, macro and active-content
    # checks the resume upload gets — a .pptx is the same zip container.
    try:
        kind = verify(
            data,
            declared_mime=file.content_type or "",
            filename=filename,
            allowed=DECK_KINDS,
        )
    except UnsafeDocument as exc:
        log.info("deck_upload_refused", reason=exc.reason)
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(exc),
        ) from exc

    # ── CHARGE, THEN DO THE WORK ─────────────────────────────────────────────
    #
    # Raises CreditsExhaustedError (402) when there is nothing left. Not committed here:
    # a failure below rolls the whole request back, charge included.
    await consume(
        db,
        current_user.user_id,
        "deck",
        detail={"filename": filename, "kind": kind, "bytes": len(data)},
    )

    try:
        evaluation = await DeckEvaluator().evaluate(data, kind, filename=filename)
    except DeckExtractionError as exc:
        log.info("deck_unreadable", reason=exc.reason)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    log.info(
        "deck_reviewed",
        weighted_total=evaluation.weighted_total,
        images=evaluation.images_analysed,
        slides=evaluation.slide_count,
    )
    return evaluation
