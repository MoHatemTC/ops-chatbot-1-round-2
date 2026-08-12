"""Database-backed multi-cohort support.

Each cohort maps to its approved Operations materials registry. A new cohort
can be added either directly in the database, or through the mutation
methods on ``CohortConfigLoader`` (used by the ``/kb/cohorts`` API routes),
without changing application code.

Cohort metadata (name, dates, enabled flag) and the materials registry
(title/source/type per cohort) are stored in the ``cohort`` and
``cohortmaterial`` tables (see ``app.models.cohort``). Material *files*
still live on disk under ``materials_root``:

Materials for newly created cohorts are written under:
    MATERIALS_BASE_DIR (default: current working directory)
joined with each cohort's ``materials_root``.

This module previously read/wrote a ``cohorts_config.json`` file directly on
the running container's disk. That worked for cohorts defined at deploy
time, but any cohort created or edited later through the admin API was lost
on the next deploy, because Railway rebuilds the container filesystem from
the last git commit every time -- the JSON file on disk was never the
persisted source of truth. Moving cohorts into the database fixes that: they
now persist the same way every other piece of application data does.

The public interface of ``CohortConfigLoader`` (and the module-level
``cohort_config`` singleton, ``cohort_gating_enabled()``, and
``is_servable_cohort()``) is unchanged from the JSON-backed version, so
existing callers (``app.api.v1.auth``, ``app.kb.admin_api``) did not need to
change.
"""

from __future__ import annotations

import os
import re
import shutil
import threading
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select

from app.cohorts.scope import normalize_cohort
from app.core.logging import logger
from app.kb.schema import SourceMetadata, SourceType
from app.models.cohort import Cohort as CohortRow
from app.models.cohort import CohortMaterial as CohortMaterialRow
from app.services.database import database_service

_COHORT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,99}$")
_SAFE_FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")


class ConfigModel(BaseModel):
    """Strict base model for cohort configuration."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class MaterialConfig(ConfigModel):
    """One approved material belonging to a cohort."""

    title: str = Field(min_length=1, max_length=300)
    source: str = Field(min_length=1, max_length=1000)
    type: SourceType

    @field_validator("source")
    @classmethod
    def validate_relative_source(cls, value: str) -> str:
        """Reject paths that can escape the configured materials directory."""
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(
                "material source must be a relative path inside materials_root"
            )
        return path.as_posix()


class CohortDefinition(ConfigModel):
    """Validated configuration for one cohort."""

    cohort_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    materials_root: str = Field(min_length=1, max_length=1000)
    enabled: bool = True
    description: str | None = Field(default=None, max_length=2000)
    project: str | None = Field(default=None, max_length=200)
    start_date: date | None = None
    end_date: date | None = None
    materials: list[MaterialConfig] = Field(default_factory=list)

    @field_validator("cohort_id")
    @classmethod
    def validate_cohort_id(cls, value: str) -> str:
        """Normalize and validate a safe, stable cohort identifier."""
        normalized = normalize_cohort(value)
        if not normalized or not _COHORT_ID_PATTERN.fullmatch(normalized):
            raise ValueError(
                "cohort_id must use lowercase letters, numbers, hyphens, "
                "or underscores"
            )
        return normalized

    @field_validator("materials_root")
    @classmethod
    def normalize_materials_root(cls, value: str) -> str:
        """Normalize the configured directory without requiring it to exist yet."""
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("materials_root must be a relative, non-escaping path")
        return path.as_posix()

    @field_validator("materials")
    @classmethod
    def reject_duplicate_sources(
        cls,
        materials: list[MaterialConfig],
    ) -> list[MaterialConfig]:
        """Prevent the same source from being configured twice."""
        sources = [material.source for material in materials]
        if len(sources) != len(set(sources)):
            raise ValueError("materials contains duplicate source paths")
        return materials

    @model_validator(mode="after")
    def validate_date_range(self) -> "CohortDefinition":
        """Ensure the cohort's end date does not precede its start date."""
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        return self

    def to_source_metadata(self) -> list[SourceMetadata]:
        """Convert configured materials into ingestion-ready metadata."""
        return [
            SourceMetadata(
                title=material.title,
                source=material.source,
                type=material.type,
                cohort=self.cohort_id,
            )
            for material in self.materials
        ]


def _slugify_cohort_id(name: str) -> str:
    """Derive a URL/JSON-safe cohort id from a human-readable name."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "cohort"


class CohortConfigError(ValueError):
    """Raised when a cohort mutation fails validation."""


class CohortNotFoundError(CohortConfigError):
    """Raised when an operation targets a cohort that does not exist."""


class CohortAlreadyExistsError(CohortConfigError):
    """Raised when creating a cohort whose id already exists."""


class MaterialNotFoundError(CohortConfigError):
    """Raised when removing a material that isn't configured."""


def _row_to_definition(
    cohort_row: CohortRow, material_rows: list[CohortMaterialRow]
) -> CohortDefinition | None:
    """Convert a ``Cohort`` row (plus its materials) into a validated definition."""
    try:
        return CohortDefinition(
            cohort_id=cohort_row.cohort_id,
            name=cohort_row.name,
            materials_root=cohort_row.materials_root,
            enabled=cohort_row.enabled,
            description=cohort_row.description,
            project=cohort_row.project,
            start_date=cohort_row.start_date,
            end_date=cohort_row.end_date,
            materials=[
                MaterialConfig(title=m.title, source=m.source, type=m.type)
                for m in material_rows
            ],
        )
    except ValidationError as exc:
        logger.warning(
            "cohort_config_entry_invalid",
            cohort_id=cohort_row.cohort_id,
            error=str(exc),
        )
        return None


class CohortConfigLoader:
    """Load, validate, and mutate cohort definitions in the database.

    The database is read on every call so changes made through the admin API
    (or directly in the database) take effect immediately, without a
    redeploy. Invalid rows are skipped and logged on read. A database read
    failure fails closed: cohort gating remains enabled, but no cohort is
    considered servable.

    Mutations (create/update/delete cohort, add/remove material) are
    serialized with an in-process lock so concurrent API requests within a
    single worker process can't race each other. Cross-row consistency
    (e.g. duplicate-source checks) is still enforced at the application
    layer, same as before.
    """

    def __init__(self, config_path: str | Path | None = None) -> None:
        """Initialize the loader.

        Args:
            config_path: Unused; kept for backward compatibility with the
                previous JSON-file-backed constructor signature.
        """
        self._lock = threading.Lock()

    @property
    def materials_base_dir(self) -> Path:
        """Return the base directory that ``materials_root`` values are relative to."""
        return Path(os.getenv("MATERIALS_BASE_DIR", "."))

    def config_exists(self) -> bool:
        """Return whether the cohort tables are reachable and queryable."""
        try:
            with database_service.get_session_maker() as session:
                session.exec(select(CohortRow.cohort_id).limit(1)).first()
            return True
        except SQLAlchemyError as exc:
            logger.warning("cohort_config_unreadable", error=str(exc))
            return False

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def _read_all(self) -> dict[str, CohortDefinition]:
        """Read all valid cohort definitions from the database."""
        try:
            with database_service.get_session_maker() as session:
                cohort_rows = session.exec(select(CohortRow)).all()
                cohorts: dict[str, CohortDefinition] = {}
                for row in cohort_rows:
                    definition = _row_to_definition(row, list(row.materials))
                    if definition is None:
                        continue
                    cohorts[definition.cohort_id] = definition
                return cohorts
        except SQLAlchemyError as exc:
            logger.warning("cohort_config_unreadable", error=str(exc))
            return {}

    def list_cohorts(self, *, include_disabled: bool = False) -> list[str]:
        """Return configured cohort IDs in stable order."""
        cohorts = self._read_all()
        return sorted(
            cohort_id
            for cohort_id, definition in cohorts.items()
            if include_disabled or definition.enabled
        )

    def list_definitions(
        self, *, include_disabled: bool = False
    ) -> list[CohortDefinition]:
        """Return full cohort definitions in stable (name) order."""
        cohorts = self._read_all()
        return sorted(
            (
                definition
                for definition in cohorts.values()
                if include_disabled or definition.enabled
            ),
            key=lambda definition: definition.name.lower(),
        )

    def get(self, cohort_id: str | None) -> CohortDefinition | None:
        """Return one enabled cohort definition, or ``None``."""
        normalized = normalize_cohort(cohort_id)
        if not normalized:
            return None

        definition = self._read_all().get(normalized)
        if definition is None or not definition.enabled:
            return None
        return definition

    def get_any(self, cohort_id: str | None) -> CohortDefinition | None:
        """Return a cohort definition regardless of its enabled state."""
        normalized = normalize_cohort(cohort_id)
        if not normalized:
            return None
        return self._read_all().get(normalized)

    def is_known_cohort(self, cohort_id: str | None) -> bool:
        """Return whether an enabled cohort exists."""
        return self.get(cohort_id) is not None

    def load_cohort_config(self, cohort_id: str) -> dict[str, Any]:
        """Return one cohort as a plain dictionary.

        This method keeps compatibility with existing callers that expect a
        dictionary rather than a Pydantic model.
        """
        normalized = normalize_cohort(cohort_id)
        definition = self.get(normalized)
        if definition is None:
            return {
                "cohort_id": normalized,
                "name": "",
                "materials_root": "",
                "enabled": False,
                "description": None,
                "project": None,
                "start_date": None,
                "end_date": None,
                "materials": [],
            }
        return definition.model_dump(mode="json")

    def get_sources(self, cohort_id: str) -> list[SourceMetadata]:
        """Return ingestion-ready sources for one enabled cohort."""
        definition = self.get(cohort_id)
        return definition.to_source_metadata() if definition else []

    def get_materials_root(self, cohort_id: str) -> Path | None:
        """Return the configured materials directory for one cohort."""
        definition = self.get(cohort_id)
        return Path(definition.materials_root) if definition else None

    def get_materials_abs_path(self, cohort_id: str) -> Path | None:
        """Return the resolved, absolute materials directory for a cohort."""
        definition = self.get_any(cohort_id)
        if definition is None:
            return None
        return self.materials_base_dir / definition.materials_root

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    """def create_cohort(
        self,
        *,
        name: str,
        materials_root: str | None = None,
        description: str | None = None,
        project: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        enabled: bool = True,
    ) -> CohortDefinition:
        """Create and persist a new cohort, returning its validated definition.

        Raises:
            CohortConfigError: if the resulting definition fails validation.
        """
        with self._lock:
            try:
                with database_service.get_session_maker() as session:
                    existing_ids = set(session.exec(select(CohortRow.cohort_id)).all())

                    base_id = _slugify_cohort_id(name)
                    candidate_id = base_id
                    suffix = 2
                    while candidate_id in existing_ids:
                        candidate_id = f"{base_id}-{suffix}"
                        suffix += 1

                    resolved_root = materials_root or f"materials/{candidate_id}"

                    try:
                        definition = CohortDefinition(
                            cohort_id=candidate_id,
                            name=name,
                            materials_root=resolved_root,
                            enabled=enabled,
                            description=description,
                            project=project,
                            start_date=start_date,
                            end_date=end_date,
                            materials=[],
                        )
                    except ValidationError as exc:
                        raise CohortConfigError(str(exc)) from exc

                    row = CohortRow(
                        cohort_id=definition.cohort_id,
                        name=definition.name,
                        materials_root=definition.materials_root,
                        enabled=definition.enabled,
                        description=definition.description,
                        project=definition.project,
                        start_date=definition.start_date,
                        end_date=definition.end_date,
                    )
                    session.add(row)
                    session.commit()
            except SQLAlchemyError as exc:
                raise CohortConfigError(str(exc)) from exc

            (self.materials_base_dir / definition.materials_root).mkdir(
                parents=True, exist_ok=True
            )

            logger.info("cohort_created", cohort_id=definition.cohort_id)
            return definition
            """

    def update_cohort(
        self,
        cohort_id: str,
        *,
        name: str | None = None,
        enabled: bool | None = None,
        description: str | None = ...,  # type: ignore[assignment]
        project: str | None = ...,  # type: ignore[assignment]
        start_date: date | None = ...,  # type: ignore[assignment]
        end_date: date | None = ...,  # type: ignore[assignment]
    ) -> CohortDefinition:
        """Update mutable fields on an existing cohort.

        Fields left as the default sentinel (``...``) are left unchanged;
        pass ``None`` explicitly to clear an optional field.

        Raises:
            CohortNotFoundError: if no cohort with this id exists.
            CohortConfigError: if the resulting definition fails validation.
        """
        normalized = normalize_cohort(cohort_id)
        with self._lock:
            try:
                with database_service.get_session_maker() as session:
                    row = session.get(CohortRow, normalized) if normalized else None
                    if row is None:
                        raise CohortNotFoundError(
                            f"cohort '{cohort_id}' does not exist"
                        )

                    updated_fields: dict[str, Any] = {
                        "cohort_id": row.cohort_id,
                        "name": row.name,
                        "materials_root": row.materials_root,
                        "enabled": row.enabled,
                        "description": row.description,
                        "project": row.project,
                        "start_date": row.start_date,
                        "end_date": row.end_date,
                        "materials": [
                            MaterialConfig(title=m.title, source=m.source, type=m.type)
                            for m in row.materials
                        ],
                    }
                    if name is not None:
                        updated_fields["name"] = name
                    if enabled is not None:
                        updated_fields["enabled"] = enabled
                    if description is not ...:
                        updated_fields["description"] = description
                    if project is not ...:
                        updated_fields["project"] = project
                    if start_date is not ...:
                        updated_fields["start_date"] = start_date
                    if end_date is not ...:
                        updated_fields["end_date"] = end_date

                    try:
                        updated = CohortDefinition(**updated_fields)
                    except ValidationError as exc:
                        raise CohortConfigError(str(exc)) from exc

                    row.name = updated.name
                    row.enabled = updated.enabled
                    row.description = updated.description
                    row.project = updated.project
                    row.start_date = updated.start_date
                    row.end_date = updated.end_date
                    row.updated_at = datetime.now(UTC)
                    session.add(row)
                    session.commit()
            except SQLAlchemyError as exc:
                raise CohortConfigError(str(exc)) from exc

            logger.info("cohort_updated", cohort_id=updated.cohort_id)
            return updated

    def delete_cohort(self, cohort_id: str) -> None:
        """Delete a cohort and all of its uploaded materials."""
        normalized = normalize_cohort(cohort_id)

        with self._lock:
            try:
                with database_service.get_session_maker() as session:
                    row = session.get(CohortRow, normalized) if normalized else None
                    if row is None:
                        raise CohortNotFoundError(
                            f"cohort '{cohort_id}' does not exist"
                        )

                    materials_dir = self.materials_base_dir / row.materials_root
                    session.delete(row)
                    session.commit()
            except SQLAlchemyError as exc:
                raise CohortConfigError(str(exc)) from exc

            if materials_dir.exists():
                shutil.rmtree(materials_dir)

            logger.info("cohort_deleted", cohort_id=normalized)

    def add_material(
        self,
        cohort_id: str,
        *,
        title: str,
        source: str,
        type: SourceType,
    ) -> CohortDefinition:
        """Add one material entry to a cohort.

        Raises:
            CohortNotFoundError: if no cohort with this id exists.
            CohortConfigError: if the material or resulting definition is invalid
                (including a duplicate ``source``).
        """
        normalized = normalize_cohort(cohort_id)
        with self._lock:
            try:
                new_material = MaterialConfig(title=title, source=source, type=type)
            except ValidationError as exc:
                raise CohortConfigError(str(exc)) from exc

            try:
                with database_service.get_session_maker() as session:
                    cohort_row = (
                        session.get(CohortRow, normalized) if normalized else None
                    )
                    if cohort_row is None:
                        raise CohortNotFoundError(
                            f"cohort '{cohort_id}' does not exist"
                        )

                    existing_sources = {m.source for m in cohort_row.materials}
                    if new_material.source in existing_sources:
                        raise CohortConfigError(
                            f"material source '{new_material.source}' already "
                            f"exists for cohort '{normalized}'"
                        )

                    material_row = CohortMaterialRow(
                        cohort_id=normalized,
                        title=new_material.title,
                        source=new_material.source,
                        type=str(new_material.type),
                    )
                    session.add(material_row)
                    session.commit()

                    session.refresh(cohort_row)
                    updated = _row_to_definition(cohort_row, list(cohort_row.materials))
            except SQLAlchemyError as exc:
                raise CohortConfigError(str(exc)) from exc

            if updated is None:
                raise CohortConfigError(
                    f"cohort '{normalized}' failed validation after update"
                )

            logger.info(
                "cohort_material_added",
                cohort_id=updated.cohort_id,
                source=new_material.source,
            )
            return updated

    def remove_material(self, cohort_id: str, source: str) -> CohortDefinition:
        """Remove one material entry from a cohort by its ``source`` path.

        Raises:
            CohortNotFoundError: if no cohort with this id exists.
            MaterialNotFoundError: if no material has that ``source``.
        """
        normalized = normalize_cohort(cohort_id)
        normalized_source = Path(source).as_posix()
        with self._lock:
            try:
                with database_service.get_session_maker() as session:
                    cohort_row = (
                        session.get(CohortRow, normalized) if normalized else None
                    )
                    if cohort_row is None:
                        raise CohortNotFoundError(
                            f"cohort '{cohort_id}' does not exist"
                        )

                    material_row = session.exec(
                        select(CohortMaterialRow).where(
                            CohortMaterialRow.cohort_id == normalized,
                            CohortMaterialRow.source == normalized_source,
                        )
                    ).first()
                    if material_row is None:
                        raise MaterialNotFoundError(
                            f"material '{source}' not found for cohort "
                            f"'{normalized}'"
                        )

                    session.delete(material_row)
                    session.commit()

                    session.refresh(cohort_row)
                    updated = _row_to_definition(cohort_row, list(cohort_row.materials))
            except SQLAlchemyError as exc:
                raise CohortConfigError(str(exc)) from exc

            if updated is None:
                raise CohortConfigError(
                    f"cohort '{normalized}' failed validation after update"
                )

            logger.info(
                "cohort_material_removed",
                cohort_id=updated.cohort_id,
                source=normalized_source,
            )
            return updated


cohort_config = CohortConfigLoader()


def cohort_gating_enabled() -> bool:
    """Return whether multi-cohort configuration is active.

    Database connectivity enables gating even when a particular row is
    malformed. This fails closed instead of silently falling back to another
    cohort.
    """
    return cohort_config.config_exists()


def is_servable_cohort(cohort_id: str | None) -> bool:
    """Return whether the requested cohort may receive knowledge-base answers."""
    normalized = normalize_cohort(cohort_id)
    if not normalized:
        return False

    if cohort_gating_enabled():
        return cohort_config.is_known_cohort(normalized)

    # Backward-compatible single-cohort mode. It is available only when the
    # cohort tables aren't reachable.
    default_cohort = normalize_cohort(os.getenv("DEFAULT_COHORT"))
    return bool(default_cohort and normalized == default_cohort)


__all__ = [
    "CohortAlreadyExistsError",
    "CohortConfigError",
    "CohortConfigLoader",
    "CohortDefinition",
    "CohortNotFoundError",
    "MaterialConfig",
    "MaterialNotFoundError",
    "cohort_config",
    "cohort_gating_enabled",
    "is_servable_cohort",
]
