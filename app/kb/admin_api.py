"""Ops Console KB admin API backed by the cohort database tables."""



import os
import re
import shutil
from datetime import UTC, date, datetime
from pathlib import Path
from fastapi import Body
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.api.v1.auth import get_current_user
from app.core.config import settings
from app.core.limiter import limiter
from app.core.logging import logger
from app.ingestion.loader import load_materials
from app.kb.schema import SourceType
from app.kb.store import build_default_store
from app.models.cohort import Cohort, CohortMaterial
from app.models.user import User
from app.schemas.knowledge import IngestionStats
from app.services.database import database_service

router = APIRouter()
db_service = database_service

_SAFE_FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,199}$")
_COHORT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,99}$")
_MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB
_MIN_COHORT_DAYS = 3
_UNASSIGNED_COHORT_ID = "unassigned"

TYPE_TO_DIR = {
    SourceType.FAQ: "faqs",
    SourceType.SCHEDULE: "schedules",
    SourceType.ONBOARDING: "onboarding",
    SourceType.PROGRAM_DOC: "docs",
}


# ----------------------------------------------------------------------
# Shared cohort helpers
# ----------------------------------------------------------------------


def _slugify_cohort_id(name: str) -> str:
    """Create a stable URL-safe cohort id from a display name."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    slug = slug[:100].rstrip("-")
    return slug or "cohort"


def _validate_materials_root(value: str) -> str:
    """Return a normalized relative materials path."""
    path = Path(value)

    if path.is_absolute() or ".." in path.parts:
        raise HTTPException(
            status_code=422,
            detail="materials_root must be a relative path inside the project.",
        )

    normalized = path.as_posix().strip("/")
    if not normalized:
        raise HTTPException(
            status_code=422,
            detail="materials_root must not be empty.",
        )

    return normalized


def _materials_base_dir() -> Path:
    """Return the base directory used for uploaded material files."""
    return Path(os.getenv("MATERIALS_BASE_DIR", "."))


def _materials_directory(materials_root: str) -> Path:
    """Resolve a cohort materials directory without allowing path escape."""
    base = _materials_base_dir().resolve()
    destination = (base / materials_root).resolve()

    if destination != base and base not in destination.parents:
        raise HTTPException(
            status_code=400,
            detail="Invalid materials directory.",
        )

    return destination


def _validate_date_range(
    start_date: date | None,
    end_date: date | None,
    *,
    creating: bool,
) -> None:
    """Validate cohort dates.

    Creation additionally forbids an end date that has already passed.
    Existing historical cohorts may still be edited without changing dates.
    """
    if end_date is not None and creating and end_date < date.today():
        raise HTTPException(
            status_code=422,
            detail="End Date cannot be before the cohort creation date.",
        )

    if start_date is not None and end_date is not None:
        if end_date < start_date:
            raise HTTPException(
                status_code=422,
                detail="End Date cannot be before Start Date.",
            )

        if (end_date - start_date).days < _MIN_COHORT_DAYS:
            raise HTTPException(
                status_code=422,
                detail=f"Cohort period must be at least {_MIN_COHORT_DAYS} days.",
            )


def _sync_expired_cohorts(session) -> int:
    """Persist expired cohorts as disabled without deleting any related data."""
    today = date.today()
    cohorts = session.exec(
        select(Cohort).where(
            Cohort.enabled == True,  # noqa: E712
            Cohort.end_date != None,  # noqa: E711
        )
    ).all()

    changed = 0
    now = datetime.now(UTC)

    for cohort in cohorts:
        if cohort.end_date is not None and cohort.end_date < today:
            cohort.enabled = False
            cohort.updated_at = now
            session.add(cohort)
            changed += 1

    if changed:
        session.commit()
        logger.info("expired_cohorts_disabled", count=changed)

    return changed


def _get_cohort_or_404(session, cohort_id: str) -> Cohort:
    normalized = cohort_id.strip().lower()
    cohort = session.get(Cohort, normalized)

    if cohort is None:
        raise HTTPException(
            status_code=404,
            detail=f"Cohort {cohort_id!r} not found.",
        )

    return cohort


def _material_relative_path(material: CohortMaterial) -> Path:
    """Return a material path relative to its cohort materials_root.

    New rows store e.g. ``faqs/example.md``. Older rows that contain only a
    filename are supported by reconstructing the type directory.
    """
    source = Path(material.source)

    if source.parent != Path("."):
        return source

    try:
        source_type = SourceType(material.type)
    except ValueError:
        return source

    subdirectory = TYPE_TO_DIR.get(source_type)
    return Path(subdirectory) / source if subdirectory else source


def _cohort_out(session, cohort: Cohort) -> "CohortOut":
    materials = session.exec(
        select(CohortMaterial)
        .where(CohortMaterial.cohort_id == cohort.cohort_id)
        .order_by(CohortMaterial.title, CohortMaterial.source)
    ).all()

    return CohortOut(
        cohort_id=cohort.cohort_id,
        name=cohort.name,
        materials_root=cohort.materials_root,
        enabled=cohort.enabled,
        description=cohort.description,
        project=cohort.project,
        start_date=cohort.start_date,
        end_date=cohort.end_date,
        materials=[
            MaterialOut(
                title=material.title,
                source=material.source,
                type=SourceType(material.type),
            )
            for material in materials
        ],
    )


# ----------------------------------------------------------------------
# Cohort schemas
# ----------------------------------------------------------------------


class MaterialOut(BaseModel):
    title: str
    source: str
    type: SourceType


class CohortOut(BaseModel):
    cohort_id: str
    name: str
    materials_root: str
    enabled: bool
    description: str | None = None
    project: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    materials: list[MaterialOut]


class CohortCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    materials_root: str | None = Field(default=None, max_length=1000)
    description: str | None = Field(default=None, max_length=2000)
    project: str | None = Field(default=None, max_length=200)
    start_date: date | None = None
    end_date: date | None = None
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped


class CohortUpdateIn(BaseModel):
    """Partial update. Omitted fields are left unchanged."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    enabled: bool | None = None
    description: str | None = Field(default=None, max_length=2000)
    project: str | None = Field(default=None, max_length=200)
    start_date: date | None = None
    end_date: date | None = None
    clear_description: bool = False
    clear_project: bool = False
    clear_start_date: bool = False
    clear_end_date: bool = False


class MaterialAddOut(BaseModel):
    cohort: CohortOut
    material: MaterialOut


# ----------------------------------------------------------------------
# Cohort routes
# ----------------------------------------------------------------------


@router.get("/cohorts")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["kb_admin"][0])
async def list_cohorts(
    request: Request,
    include_disabled: bool = False,
    user: User = Depends(get_current_user),
):
    """List database-backed cohorts, optionally including disabled cohorts."""
    with db_service.get_session_maker() as session:
        _sync_expired_cohorts(session)

        statement = select(Cohort).order_by(Cohort.name, Cohort.cohort_id)
        if not include_disabled:
            statement = statement.where(Cohort.enabled == True)  # noqa: E712

        cohorts = session.exec(statement).all()

        return {
            "cohorts": [
                _cohort_out(session, cohort)
                for cohort in cohorts
            ]
        }


@router.get("/cohorts/{cohort_id}")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["kb_admin"][0])
async def get_cohort(
    request: Request,
    cohort_id: str,
    user: User = Depends(get_current_user),
):
    """Return one cohort and its registered materials from PostgreSQL."""
    with db_service.get_session_maker() as session:
        _sync_expired_cohorts(session)
        cohort = _get_cohort_or_404(session, cohort_id)
        return _cohort_out(session, cohort)


@router.post("/cohorts", status_code=201)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["kb_admin"][0])
async def create_cohort(
    request: Request,
    payload: CohortCreateIn = Body(...),
    user: User = Depends(get_current_user),
):
    """Create a cohort in PostgreSQL and create its materials directory."""
    _validate_date_range(
        payload.start_date,
        payload.end_date,
        creating=True,
    )

    with db_service.get_session_maker() as session:
        base_id = _slugify_cohort_id(payload.name)
        candidate_id = base_id
        suffix = 2

        while session.get(Cohort, candidate_id) is not None:
            candidate_id = f"{base_id[:95]}-{suffix}"
            suffix += 1

        if not _COHORT_ID_PATTERN.fullmatch(candidate_id):
            raise HTTPException(
                status_code=422,
                detail="Could not derive a valid cohort ID from the supplied name.",
            )

        materials_root = _validate_materials_root(
            payload.materials_root or f"materials/{candidate_id}"
        )

        # A cohort whose end date has already passed can never be enabled.
        enabled = bool(
            payload.enabled
            and (
                payload.end_date is None
                or payload.end_date >= date.today()
            )
        )

        cohort = Cohort(
            cohort_id=candidate_id,
            name=payload.name.strip(),
            materials_root=materials_root,
            enabled=enabled,
            description=payload.description.strip() if payload.description else None,
            project=payload.project.strip() if payload.project else None,
            start_date=payload.start_date,
            end_date=payload.end_date,
            updated_at=datetime.now(UTC),
        )

        try:
            _materials_directory(materials_root).mkdir(parents=True, exist_ok=True)
            session.add(cohort)
            session.commit()
            session.refresh(cohort)
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(
                status_code=409,
                detail=f"Cohort {candidate_id!r} already exists.",
            ) from exc

        logger.info(
            "cohort_created",
            user_id=user.id,
            cohort=cohort.cohort_id,
        )

        return _cohort_out(session, cohort)


@router.patch("/cohorts/{cohort_id}")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["kb_admin"][0])
async def update_cohort(
    request: Request,
    cohort_id: str,
    payload: CohortUpdateIn,
    user: User = Depends(get_current_user),
):
    """Update cohort metadata in PostgreSQL.

    Disabling a cohort does not delete its chunks, files, materials registry,
    learner assignment, or chat history. Re-enabling it therefore restores
    access to the same cohort data.
    """
    with db_service.get_session_maker() as session:
        _sync_expired_cohorts(session)
        cohort = _get_cohort_or_404(session, cohort_id)

        fields_set = payload.model_fields_set

        new_start = cohort.start_date
        new_end = cohort.end_date

        if payload.clear_start_date:
            new_start = None
        elif "start_date" in fields_set:
            new_start = payload.start_date

        if payload.clear_end_date:
            new_end = None
        elif "end_date" in fields_set:
            new_end = payload.end_date

        _validate_date_range(
            new_start,
            new_end,
            creating=False,
        )

        if payload.name is not None:
            stripped_name = payload.name.strip()
            if not stripped_name:
                raise HTTPException(
                    status_code=422,
                    detail="Cohort Name is required.",
                )
            cohort.name = stripped_name

        if payload.clear_description:
            cohort.description = None
        elif "description" in fields_set:
            cohort.description = (
                payload.description.strip()
                if payload.description
                else None
            )

        if payload.clear_project:
            cohort.project = None
        elif "project" in fields_set:
            cohort.project = (
                payload.project.strip()
                if payload.project
                else None
            )

        cohort.start_date = new_start
        cohort.end_date = new_end

        if "enabled" in fields_set and payload.enabled is not None:
            cohort.enabled = payload.enabled

        # Expiration always wins over a requested enabled=True.
        if cohort.end_date is not None and cohort.end_date < date.today():
            cohort.enabled = False

        cohort.updated_at = datetime.now(UTC)

        session.add(cohort)
        session.commit()
        session.refresh(cohort)

        logger.info(
            "cohort_updated",
            user_id=user.id,
            cohort=cohort.cohort_id,
            enabled=cohort.enabled,
        )

        return _cohort_out(session, cohort)


@router.delete("/cohorts/{cohort_id}", status_code=204)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["kb_admin"][0])
async def delete_cohort(
    request: Request,
    cohort_id: str,
    user: User = Depends(get_current_user),
):
    """Permanently delete a cohort.

    Unlike disabling, permanent deletion retires the cohort's KB chunks and
    changes affected user/session assignments to ``unassigned``.
    """
    with db_service.get_session_maker() as session:
        cohort = _get_cohort_or_404(session, cohort_id)
        materials_root = cohort.materials_root

        # Preserve shared directories: another cohort may intentionally point
        # to the same materials_root (for example a demo cohort).
        shared_root = session.exec(
            select(Cohort).where(
                Cohort.cohort_id != cohort.cohort_id,
                Cohort.materials_root == materials_root,
            )
        ).first()

        try:
            store = build_default_store()
            store.retire_cohort(cohort.cohort_id)

            # Permanent deletion removes membership references.
            session.execute(
                text(
                    """
                    UPDATE "user"
                    SET cohort_id = :unassigned
                    WHERE LOWER(cohort_id) = :cohort_id
                    """
                ),
                {
                    "unassigned": _UNASSIGNED_COHORT_ID,
                    "cohort_id": cohort.cohort_id.lower(),
                },
            )
            session.execute(
                text(
                    """
                    UPDATE "session"
                    SET cohort_id = :unassigned
                    WHERE LOWER(cohort_id) = :cohort_id
                    """
                ),
                {
                    "unassigned": _UNASSIGNED_COHORT_ID,
                    "cohort_id": cohort.cohort_id.lower(),
                },
            )

            # CohortMaterial rows are deleted through the model relationship's
            # delete-orphan cascade.
            session.delete(cohort)
            session.commit()

            if shared_root is None:
                directory = _materials_directory(materials_root)
                if directory.exists():
                    shutil.rmtree(directory)

        except Exception as exc:
            session.rollback()
            logger.exception(
                "cohort_delete_failed",
                user_id=user.id,
                cohort=cohort_id,
                error=str(exc),
            )
            raise HTTPException(
                status_code=500,
                detail="Failed to delete cohort.",
            ) from exc

        logger.info(
            "cohort_deleted",
            user_id=user.id,
            cohort=cohort_id,
        )


@router.post(
    "/cohorts/{cohort_id}/materials",
    response_model=MaterialAddOut,
    status_code=201,
)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["kb_admin"][0])
async def upload_material(
    request: Request,
    cohort_id: str,
    title: str = Form(..., min_length=1, max_length=300),
    material_type: SourceType = Form(...),
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    """Upload and register an approved material for an enabled cohort."""
    with db_service.get_session_maker() as session:
        _sync_expired_cohorts(session)
        cohort = _get_cohort_or_404(session, cohort_id)

        if not cohort.enabled:
            raise HTTPException(
                status_code=409,
                detail="Disabled cohorts cannot receive new materials.",
            )

        filename = file.filename or ""
        safe_name = Path(filename).name

        if not safe_name or not _SAFE_FILENAME_PATTERN.fullmatch(safe_name):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Invalid file name. Use letters, numbers, spaces, dots, "
                    "hyphens, or underscores only."
                ),
            )

        contents = await file.read()
        if not contents:
            raise HTTPException(
                status_code=400,
                detail="Uploaded file is empty.",
            )

        if len(contents) > _MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"File exceeds the "
                    f"{_MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit."
                ),
            )

        subdirectory = TYPE_TO_DIR.get(material_type)
        if subdirectory is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported material type: {material_type}",
            )

        relative_source = Path(subdirectory) / safe_name
        cohort_directory = _materials_directory(cohort.materials_root)
        destination = (cohort_directory / relative_source).resolve()

        if (
            destination != cohort_directory
            and cohort_directory not in destination.parents
        ):
            raise HTTPException(
                status_code=400,
                detail="Invalid file destination.",
            )

        destination.parent.mkdir(parents=True, exist_ok=True)

        existing = session.exec(
            select(CohortMaterial).where(
                CohortMaterial.cohort_id == cohort.cohort_id,
                CohortMaterial.source == relative_source.as_posix(),
            )
        ).first()

        if existing is not None or destination.exists():
            raise HTTPException(
                status_code=409,
                detail=(
                    f"A material named '{safe_name}' already exists "
                    f"for this cohort."
                ),
            )

        destination.write_bytes(contents)

        material = CohortMaterial(
            cohort_id=cohort.cohort_id,
            title=title.strip(),
            source=relative_source.as_posix(),
            type=material_type.value,
        )

        try:
            session.add(material)
            session.commit()
            session.refresh(material)
        except IntegrityError as exc:
            session.rollback()
            destination.unlink(missing_ok=True)
            raise HTTPException(
                status_code=409,
                detail="That material is already registered.",
            ) from exc
        except Exception:
            session.rollback()
            destination.unlink(missing_ok=True)
            raise

        logger.info(
            "cohort_material_uploaded",
            user_id=user.id,
            cohort=cohort.cohort_id,
            source=material.source,
        )

        return MaterialAddOut(
            cohort=_cohort_out(session, cohort),
            material=MaterialOut(
                title=material.title,
                source=material.source,
                type=SourceType(material.type),
            ),
        )


@router.delete("/cohorts/{cohort_id}/materials/{source:path}")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["kb_admin"][0])
async def remove_material(
    request: Request,
    cohort_id: str,
    source: str,
    delete_file: bool = False,
    user: User = Depends(get_current_user),
):
    """Unregister a material and retire only that material's KB chunks."""
    normalized_source = Path(source).as_posix()

    with db_service.get_session_maker() as session:
        cohort = _get_cohort_or_404(session, cohort_id)

        material = session.exec(
            select(CohortMaterial).where(
                CohortMaterial.cohort_id == cohort.cohort_id,
                CohortMaterial.source == normalized_source,
            )
        ).first()

        # Compatibility with older registry rows that stored only a filename.
        if material is None:
            candidates = session.exec(
                select(CohortMaterial).where(
                    CohortMaterial.cohort_id == cohort.cohort_id
                )
            ).all()
            matching = [
                item
                for item in candidates
                if Path(item.source).name == Path(normalized_source).name
            ]
            if len(matching) == 1:
                material = matching[0]

        if material is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Material {source!r} not found "
                    f"for cohort {cohort_id!r}."
                ),
            )

        relative_path = _material_relative_path(material)

        # load_materials() stores metadata.source as the path passed on disk.
        # Reconstruct the same relative path so the exact composite source_id
        # is retired instead of leaving stale chunks behind.
        loaded_source = str(Path(cohort.materials_root) / relative_path)
        source_id = f"{cohort.cohort_id}::{loaded_source}"

        store = build_default_store()
        store.retire_material(source_id)

        if delete_file:
            target = (
                _materials_directory(cohort.materials_root)
                / relative_path
            ).resolve()
            cohort_directory = _materials_directory(cohort.materials_root)

            if target == cohort_directory or cohort_directory in target.parents:
                target.unlink(missing_ok=True)

        removed_source = material.source
        session.delete(material)
        session.commit()

        logger.info(
            "cohort_material_removed",
            user_id=user.id,
            cohort=cohort.cohort_id,
            source=removed_source,
        )

        return _cohort_out(session, cohort)


@router.post("/cohorts/{cohort_id}/onboard", response_model=IngestionStats)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["kb_admin"][0])
async def onboard_cohort(
    request: Request,
    cohort_id: str,
    user: User = Depends(get_current_user),
):
    """Ingest an enabled cohort from its database-backed materials_root.

    This route intentionally does not delete existing chunks before ingestion.
    The KB store's update-not-duplicate behavior handles unchanged sources.
    """
    with db_service.get_session_maker() as session:
        _sync_expired_cohorts(session)
        cohort = _get_cohort_or_404(session, cohort_id)

        if not cohort.enabled:
            raise HTTPException(
                status_code=409,
                detail=f"Cohort {cohort_id!r} is disabled.",
            )

        materials_root = cohort.materials_root
        if not materials_root:
            raise HTTPException(
                status_code=400,
                detail=f"Cohort {cohort_id!r} has no materials_root.",
            )

        # Keep the same relative-path representation used by earlier ingestion
        # so source_id values remain stable and re-ingestion does not create a
        # second set of chunks merely because an absolute path was introduced.
        root_path = Path(materials_root)

        try:
            materials = load_materials(root_path, cohort.cohort_id)
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Materials directory for cohort {cohort_id!r} "
                    f"was not found: {root_path}"
                ),
            ) from exc

        if not materials:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"No approved material files were found under "
                    f"{str(root_path)!r}."
                ),
            )

        try:
            store = build_default_store()
            stats = store.ingest(materials)

            logger.info(
                "cohort_onboarded",
                user_id=user.id,
                cohort=cohort.cohort_id,
                materials=len(materials),
                sources_seen=stats.sources_seen,
                sources_ingested=stats.sources_ingested,
                sources_skipped=stats.sources_skipped,
            )

            return stats

        except Exception as exc:
            logger.exception(
                "cohort_onboarding_failed",
                user_id=user.id,
                cohort=cohort_id,
                error=str(exc),
            )
            raise HTTPException(
                status_code=500,
                detail="Cohort ingestion failed.",
            ) from exc


# ----------------------------------------------------------------------
# Knowledge-base material routes
# ----------------------------------------------------------------------


@router.get("/materials")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["kb_admin"][0])
async def list_materials(
    request: Request,
    user: User = Depends(get_current_user),
):
    """List all currently ingested KB materials."""
    try:
        store = build_default_store()
        materials = store.list_materials()

        logger.info(
            "kb_materials_listed",
            user_id=user.id,
            count=len(materials),
        )

        return {"materials": materials}

    except Exception as exc:
        logger.exception(
            "kb_list_failed",
            user_id=user.id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to list knowledge-base materials.",
        ) from exc


@router.get("/materials/{material_id:path}")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["kb_admin"][0])
async def get_material(
    request: Request,
    material_id: str,
    user: User = Depends(get_current_user),
):
    """Fetch a single material's current KB content."""
    try:
        store = build_default_store()
        material = store.get_material(material_id)

        if not material:
            raise HTTPException(
                status_code=404,
                detail=f"No material found for material_id={material_id}",
            )

        logger.info(
            "kb_material_fetched",
            user_id=user.id,
            material_id=material_id,
        )

        return material

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "kb_material_fetch_failed",
            user_id=user.id,
            material_id=material_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to load material.",
        ) from exc


@router.post("/retire/{material_id:path}")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["kb_admin"][0])
async def retire_material(
    request: Request,
    material_id: str,
    user: User = Depends(get_current_user),
):
    """Retire a material from the vector knowledge base."""
    try:
        store = build_default_store()
        retired = store.retire_material(material_id)

        if not retired:
            raise HTTPException(
                status_code=404,
                detail=f"No material found for material_id={material_id}",
            )

        logger.info(
            "kb_material_retired_via_api",
            user_id=user.id,
            material_id=material_id,
        )

        return {
            "material_id": material_id,
            "retired": True,
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "kb_retire_failed",
            user_id=user.id,
            material_id=material_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to retire material.",
        ) from exc