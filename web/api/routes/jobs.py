"""Job management endpoints."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from .. import config_adapter, store, worker
from ..models import (
    ClipDetail,
    JobCreateRequest,
    JobListResponse,
    JobProgressEvent,
    JobResponse,
    JobStatus,
)
from ..readiness import get_readiness
from clipping.presets import PRESET_BY_ID, apply_preset

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _job_to_response(job: dict) -> JobResponse:
    clips = []
    for c in job.get("clips", []):
        if isinstance(c, ClipDetail):
            clips.append(c)
        elif isinstance(c, dict):
            clips.append(ClipDetail(**c))

    progress = job.get("progress")
    if progress and isinstance(progress, dict):
        if isinstance(progress.get("timestamp"), str):
            progress["timestamp"] = datetime.fromisoformat(progress["timestamp"])
        progress = JobProgressEvent(**progress)

    return JobResponse(
        id=job["id"],
        status=job.get("status", JobStatus.QUEUED),
        created_at=job.get("created_at", datetime.utcnow()),
        updated_at=job.get("updated_at", datetime.utcnow()),
        url=job.get("url"),
        upload_filename=job.get("upload_filename"),
        source=job.get("source", "youtube"),
        config=job.get("config", {}),
        progress=progress,
        clips=clips,
        error=job.get("error"),
        cancel_requested=job.get("cancel_requested", False),
        log=job.get("log", []),
    )


@router.post("", status_code=201)
async def create_job(req: JobCreateRequest) -> JobResponse:
    if not req.url and not req.upload_filename and not req.reuse_job_id:
        raise HTTPException(
            status_code=400,
            detail="Either 'url', 'upload_filename', or 'reuse_job_id' must be provided.",
        )
    if req.url and req.upload_filename:
        raise HTTPException(status_code=400, detail="Provide either a URL or an uploaded video, not both.")
    if req.reuse_job_id and (req.url or req.upload_filename):
        raise HTTPException(status_code=400, detail="Reuse uses the original source; do not also provide a new source.")

    payload = req.model_dump(mode="json")
    reuse_job_id = payload.pop("reuse_job_id", None)
    stored_url = req.url

    if reuse_job_id:
        previous = store.get_job(reuse_job_id)
        if previous is None:
            raise HTTPException(status_code=404, detail="Job to reuse was not found.")
        if previous.get("status") not in store.TERMINAL_STATES or worker.is_job_active(reuse_job_id):
            raise HTTPException(status_code=409, detail="Wait for the existing job to stop before reusing it.")
        payload["upload_filename"] = previous.get("upload_filename")
        payload["source"] = previous.get("source", "youtube")
        stored_url = previous.get("url")
        if "load_gemini_json" not in req.model_fields_set:
            payload["load_gemini_json"] = True
        previous_dir = config_adapter.PROJECT_ROOT / "outputs" / reuse_job_id
        if previous_dir.resolve().parent != (config_adapter.PROJECT_ROOT / "outputs").resolve():
            raise HTTPException(status_code=400, detail="Invalid job output directory.")
        if not payload["upload_filename"] and not (previous_dir / "video_asli.mp4").is_file():
            raise HTTPException(
                status_code=400,
                detail="Original video is missing. Create a new job from its source URL.",
            )
        if payload["load_gemini_json"] and not (previous_dir / "gemini_response.json").is_file():
            raise HTTPException(
                status_code=400,
                detail="Cached AI JSON is missing. Disable Bypass AI to analyze again.",
            )
    elif payload["load_gemini_json"]:
        raise HTTPException(status_code=400, detail="Bypass AI requires an existing job to reuse.")

    if payload.get("upload_filename"):
        try:
            upload_path = config_adapter.resolve_upload_path(payload["upload_filename"])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not Path(upload_path).is_file():
            raise HTTPException(status_code=400, detail="Uploaded video was not found.")

    if payload.get("preset"):
        if payload["preset"] not in PRESET_BY_ID:
            raise HTTPException(status_code=400, detail="Unknown preset.")
        # Preset values fill only what the client did not explicitly send.
        preset_values = PRESET_BY_ID[payload["preset"]]["settings"]
        aliases = {"camera_switch": "use_camera_switch"}
        for key, value in preset_values.items():
            target = aliases.get(key, key)
            if key not in req.model_fields_set and target not in req.model_fields_set:
                if target in payload or target == "use_camera_switch":
                    payload[target] = value

    readiness = await asyncio.to_thread(get_readiness)
    if not readiness["ready"]:
        raise HTTPException(
            status_code=503,
            detail=(
                "Renderer backend is not ready. Missing: "
                + ", ".join(readiness["missing"])
                + ". Check /api/ready."
            ),
        )

    try:
        job_id = store.create_job(
            url=stored_url,
            upload_filename=payload.get("upload_filename"),
            source=payload["source"],
            config=payload,
            job_id=reuse_job_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await worker.submit_job(job_id, payload)
    return _job_to_response(store.get_job(job_id))


@router.get("")
async def list_jobs() -> JobListResponse:
    jobs = store.list_jobs()
    return JobListResponse(jobs=[_job_to_response(j) for j in jobs], total=len(jobs))


@router.get("/{job_id}")
async def get_job(job_id: str) -> JobResponse:
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_to_response(job)


@router.delete("/{job_id}")
async def delete_job(job_id: str) -> dict:
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.get("status") not in store.TERMINAL_STATES:
        worker.cancel_job(job_id)
        return {
            "message": "Cancellation requested; waiting for the current operation to finish.",
            "id": job_id,
            "cancel_requested": True,
        }
    if worker.is_job_active(job_id):
        raise HTTPException(status_code=409, detail="The worker is still stopping. Try again shortly.")

    store.delete_job(job_id)
    return {"message": "Job deleted", "id": job_id}


@router.get("/{job_id}/status")
async def job_status_sse(job_id: str):
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_stream():
        last = None
        terminal_states = {
            JobStatus.COMPLETED.value,
            JobStatus.FAILED.value,
            JobStatus.CANCELLED.value,
        }
        while True:
            current = store.get_job(job_id)
            if current is None:
                yield f"data: {json.dumps({'type': 'deleted'})}\n\n"
                break

            status = current.get("status", "")
            progress = current.get("progress")
            progress_data = None
            if progress:
                if hasattr(progress, "model_dump"):
                    progress_data = progress.model_dump()
                    if isinstance(progress_data.get("timestamp"), datetime):
                        progress_data["timestamp"] = progress_data["timestamp"].isoformat()
                elif isinstance(progress, dict):
                    progress_data = progress

            event = {
                "type": "progress",
                "status": status,
                "progress": progress_data,
                "error": current.get("error"),
                "cancel_requested": current.get("cancel_requested", False),
                "log_tail": current.get("log", [])[-6:],
            }

            if status in terminal_states:
                event["type"] = status
                event["clips"] = [
                    c.model_dump(mode="json") if isinstance(c, ClipDetail) else c
                    for c in current.get("clips", [])
                ]
                yield f"data: {json.dumps(event, default=str)}\n\n"
                break

            event_json = json.dumps(event, default=str)
            if event_json != last:
                yield f"data: {event_json}\n\n"
                last = event_json

            await asyncio.sleep(1.0)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
