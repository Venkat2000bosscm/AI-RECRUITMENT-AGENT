"""Approved tool integrations behind connector abstractions (ATS, job boards, calendar, email).

The MVP ships local connectors so the full workflow runs without vendor credentials. Production
connectors (Greenhouse, Lever, Workday, Google/Outlook calendar, etc.) implement the same interfaces.
"""

import logging
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage as MIMEMessage
from email.utils import parseaddr

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import EmailMessage, Interview, Interviewer, Job, utcnow

logger = logging.getLogger(__name__)


class JobBoardConnector:
    """Publishes approved JDs to configured channels. Local implementation records postings only."""

    def publish(self, job: Job, channels: list[str]) -> list[dict]:
        return [{"channel": c, "posting_id": f"{c.lower().replace(' ', '-')}-{job.id}", "status": "live"} for c in channels]


class EmailConnector:
    def send(
        self, db: Session, to: str, subject: str, body: str, kind: str = "general", job_id=None, candidate_id=None
    ) -> EmailMessage:
        msg = EmailMessage(to=to, subject=subject, body=body, kind=kind, job_id=job_id, candidate_id=candidate_id)
        parsed_to = parseaddr(to)[1]
        if not parsed_to or "@" not in parsed_to or parsed_to.startswith("@") or parsed_to.endswith("@"):
            msg.status = "failed"
            logger.warning("Email was not queued because the recipient address is invalid (candidate_id=%s)", candidate_id)
        elif settings.smtp_host:
            try:
                mime = MIMEMessage()
                mime["From"], mime["To"], mime["Subject"] = settings.smtp_from, parsed_to, subject
                mime.set_content(body)
                with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
                    smtp.starttls()
                    if settings.smtp_user:
                        smtp.login(settings.smtp_user, settings.smtp_password or "")
                    smtp.send_message(mime)
                msg.status = "sent"
            except Exception:
                msg.status = "failed"
                logger.exception("Email delivery failed (kind=%s, candidate_id=%s)", kind, candidate_id)
        else:
            msg.status = "queued"
        db.add(msg)
        return msg


class CalendarConnector:
    """Finds free interview slots from interviewer working hours and existing interviews."""

    def is_available(
        self,
        db: Session,
        interviewer_id: int,
        start: datetime,
        end: datetime,
        exclude_interview_id: int | None = None,
    ) -> bool:
        query = select(Interview.id).where(
            Interview.interviewer_id == interviewer_id,
            Interview.status.in_(["proposed", "scheduled"]),
            Interview.start_time < end,
            Interview.end_time > start,
        )
        if exclude_interview_id is not None:
            query = query.where(Interview.id != exclude_interview_id)
        return db.scalar(query.limit(1)) is None

    def busy_slots(self, db: Session, interviewer_id: int) -> list[tuple[datetime, datetime]]:
        rows = db.scalars(
            select(Interview).where(Interview.interviewer_id == interviewer_id, Interview.status.in_(["proposed", "scheduled"]))
        ).all()
        return [(i.start_time, i.end_time) for i in rows if i.start_time and i.end_time]

    def find_slots(
        self, db: Session, interviewer: Interviewer, count: int = 3, duration_minutes: int = 60, start: datetime | None = None
    ) -> list[tuple[datetime, datetime]]:
        busy = self.busy_slots(db, interviewer.id)
        day = (start or utcnow()).replace(minute=0, second=0, microsecond=0) + timedelta(days=1)
        slots: list[tuple[datetime, datetime]] = []
        for _ in range(21):
            if day.weekday() < 5:
                for hour in range(interviewer.work_start_hour, interviewer.work_end_hour):
                    s = day.replace(hour=hour)
                    e = s + timedelta(minutes=duration_minutes)
                    if e.hour > interviewer.work_end_hour or (e.hour == interviewer.work_end_hour and e.minute > 0):
                        continue
                    if all(e <= bs or s >= be for bs, be in busy):
                        slots.append((s, e))
                        if len(slots) >= count:
                            return slots
            day += timedelta(days=1)
        return slots


job_boards = JobBoardConnector()
email = EmailConnector()
calendar = CalendarConnector()
