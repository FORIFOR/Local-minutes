from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.meeting import Meeting
from ..models.user import User
from ..schemas.meeting import MeetingCreate, MeetingRead
from ..security import get_current_user

router = APIRouter(tags=["meetings"])


@router.get("", response_model=list[MeetingRead])
def list_meetings(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return (
        db.query(Meeting)
        .filter(Meeting.user_id == user.id)
        .order_by(Meeting.started_at.desc())
        .all()
    )


@router.post("", response_model=MeetingRead, status_code=status.HTTP_201_CREATED)
def create_meeting(
    payload: MeetingCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    meeting = Meeting(user_id=user.id, **payload.dict())
    db.add(meeting)
    db.commit()
    db.refresh(meeting)
    return meeting


@router.get("/{meeting_id}", response_model=MeetingRead)
def get_meeting(meeting_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    meeting = (
        db.query(Meeting)
        .filter(Meeting.id == meeting_id, Meeting.user_id == user.id)
        .first()
    )
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return meeting


@router.put("/{meeting_id}", response_model=MeetingRead)
def update_meeting(
    meeting_id: int,
    payload: MeetingCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    meeting = (
        db.query(Meeting)
        .filter(Meeting.id == meeting_id, Meeting.user_id == user.id)
        .first()
    )
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    for key, value in payload.dict().items():
        setattr(meeting, key, value)
    db.commit()
    db.refresh(meeting)
    return meeting


@router.delete("/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_meeting(meeting_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    meeting = (
        db.query(Meeting)
        .filter(Meeting.id == meeting_id, Meeting.user_id == user.id)
        .first()
    )
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    db.delete(meeting)
    db.commit()
    return None
