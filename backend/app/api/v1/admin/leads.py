"""Leads from the `/start` landing page — super-admin only.

    GET   /admin/leads              list, newest first (?status=&q=&page=&limit=)
    GET   /admin/leads/export.csv   the same filter, as a CSV download
    PATCH /admin/leads/{id}         { status?, note? }

Read and update only. A lead is never deleted from here: a number that said
"not interested" is still worth knowing about when it fills the form again.
"""

from __future__ import annotations

import csv
import io
from datetime import timedelta, timezone

from fastapi import APIRouter, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.core.dependencies import SuperAdmin
from app.models.lead import EXPERIENCE_LABELS
from app.schemas.common import APIResponse
from app.services import lead_service

router = APIRouter(prefix="/leads", tags=["admin-leads"])

IST = timezone(timedelta(hours=5, minutes=30))


class LeadUpdate(BaseModel):
    status: str | None = None
    note: str | None = Field(default=None, max_length=1000)


@router.get("", response_model=APIResponse[dict])
async def list_leads(
    admin: SuperAdmin,
    status: str | None = Query(None),
    q: str | None = Query(None, max_length=80),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    rows, total = await lead_service.list_leads(status=status, q=q, page=page, limit=limit)
    return APIResponse(
        data={
            "rows": [lead_service.to_out(r) for r in rows],
            "counts": await lead_service.counts(),
            "page": page,
            "limit": limit,
            "total": total,
        },
        total=total,
    )


def _ist(dt) -> str:
    if dt is None:
        return ""
    d = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return d.astimezone(IST).strftime("%d/%m/%Y %H:%M")


@router.get("/export.csv")
async def export_leads(
    admin: SuperAdmin,
    status: str | None = Query(None),
    q: str | None = Query(None, max_length=80),
):
    rows = await lead_service.all_leads(status=status, q=q)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "Created (IST)", "Name", "Mobile", "Email", "City", "Experience", "Question",
        "Status", "Note", "Ref code",
        "UTM source", "UTM medium", "UTM campaign", "UTM content", "UTM term",
        "Submissions", "Last submitted (IST)", "Converted (IST)",
    ])
    for r in rows:
        w.writerow([
            _ist(r.created_at), r.full_name, r.mobile, r.email or "", r.city,
            EXPERIENCE_LABELS.get(r.experience, "") if r.experience else "",
            r.question, r.status.value, r.note,
            r.ref_code or "", r.utm_source or "", r.utm_medium or "", r.utm_campaign or "",
            r.utm_content or "", r.utm_term or "", r.submissions,
            _ist(r.last_submitted_at), _ist(r.converted_at),
        ])
    return Response(
        content="﻿" + buf.getvalue(),  # BOM so Excel reads UTF-8 names
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="leads.csv"'},
    )


@router.patch("/{lead_id}", response_model=APIResponse[dict])
async def update_lead(lead_id: str, payload: LeadUpdate, admin: SuperAdmin):
    lead = await lead_service.update_lead(lead_id, status=payload.status, note=payload.note)
    return APIResponse(data=lead_service.to_out(lead))
