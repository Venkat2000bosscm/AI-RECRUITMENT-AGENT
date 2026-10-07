from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import Candidate, Job, Offer, User
from ..schemas import OfferOut, OfferResponseRequest
from ..services import guardrails, recruitment

router = APIRouter(prefix="/api/offers", tags=["offers"])


def offer_out(db: Session, o: Offer) -> OfferOut:
    out = OfferOut.model_validate(o)
    out.candidate_name = db.get(Candidate, o.candidate_id).name
    out.job_title = db.get(Job, o.job_id).title
    return out


@router.get("", response_model=list[OfferOut])
def list_offers(candidate_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    q = select(Offer).order_by(Offer.created_at.desc())
    if candidate_id:
        q = q.where(Offer.candidate_id == candidate_id)
    return [offer_out(db, o) for o in db.scalars(q).all()]


@router.post("/{offer_id}/response", response_model=OfferOut)
def respond(offer_id: int, req: OfferResponseRequest, db: Session = Depends(get_db), user: User = Depends(current_user)):
    guardrails.ensure_permission(user, "draft_offer")
    o = db.get(Offer, offer_id)
    if o is None:
        raise HTTPException(404, "Offer not found")
    recruitment.record_offer_response(db, o, req.accepted, user.name)
    db.commit()
    return offer_out(db, o)
