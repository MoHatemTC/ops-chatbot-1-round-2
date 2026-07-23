"""Loaders that turn approved source files into :class:`RawMaterial` objects.

The loaders are format aware but deliberately simple: they read a directory of
approved materials, tag each document with the right :class:`SourceType` and
cohort, and hand normalized :class:`RawMaterial` objects to the knowledge base
store. They perform no embedding or persistence.

Directory convention (relative to the cohort root)::

    <root>/
        faqs/        -> SourceType.FAQ
        schedules/   -> SourceType.SCHEDULE
        onboarding/  -> SourceType.ONBOARDING
        docs/        -> SourceType.PROGRAM_DOC

FAQ and schedule files may be JSON; everything else is treated as plain
text/markdown.
"""

import json
from pathlib import Path

from app.core.logging import logger
from app.schemas.knowledge import (
    RawMaterial,
    SourceMetadata,
    SourceType,
)

# Maps a sub-directory name to the material type it holds.
_DIR_TO_TYPE: dict[str, SourceType] = {
    "faqs": SourceType.FAQ,
    "faq": SourceType.FAQ,
    "schedules": SourceType.SCHEDULE,
    "schedule": SourceType.SCHEDULE,
    "onboarding": SourceType.ONBOARDING,
    "docs": SourceType.PROGRAM_DOC,
    "program": SourceType.PROGRAM_DOC,
}

# File extensions treated as textual material.
_TEXT_SUFFIXES = {".md", ".markdown", ".txt"}


def _read_title(path: Path, content: str) -> str:
    """Derive a human-readable title from a markdown heading or the filename.

    Args:
        path: Source file path.
        content: File content.

    Returns:
        The first markdown H1 if present, otherwise the humanized file stem.
    """
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return path.stem.replace("_", " ").replace("-", " ").strip().title()


def _render_faq_json(data: object) -> str:
    """Render FAQ JSON into readable ``Q:``/``A:`` text.

    Accepts a list of objects with ``question``/``answer`` keys (aliases
    ``q``/``a`` are also honored). Any other shape falls back to pretty JSON.

    Args:
        data: Parsed JSON payload.

    Returns:
        A plain-text rendering suitable for chunking.
    """
    if isinstance(data, list):
        blocks: list[str] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            question = str(item.get("question") or item.get("q") or "").strip()
            answer = str(item.get("answer") or item.get("a") or "").strip()
            if question or answer:
                blocks.append(f"Q: {question}\nA: {answer}")
        if blocks:
            return "\n\n".join(blocks)
    return json.dumps(data, ensure_ascii=False, indent=2)


def _render_schedule_json(data: object) -> str:
    """Render schedule JSON into readable lines.

    Accepts a list of objects; each object's key/value pairs are flattened into
    a single line. Any other shape falls back to pretty JSON.

    Args:
        data: Parsed JSON payload.

    Returns:
        A plain-text rendering suitable for chunking.
    """
    if isinstance(data, list):
        lines: list[str] = []
        for item in data:
            if isinstance(item, dict):
                parts = [f"{key}: {value}" for key, value in item.items()]
                lines.append(" | ".join(parts))
        if lines:
            return "\n".join(lines)
    return json.dumps(data, ensure_ascii=False, indent=2)


def _load_file(path: Path, source_type: SourceType, cohort: str) -> RawMaterial | None:
    """Load a single file into a :class:`RawMaterial`.

    Args:
        path: File to load.
        source_type: The material type inferred from its directory.
        cohort: Cohort the material belongs to.

    Returns:
        The loaded material, or ``None`` if the file is empty or unsupported.
    """
    suffix = path.suffix.lower()
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("kb_loader_read_failed", path=str(path), error=str(exc))
        return None

    if suffix == ".json":
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("kb_loader_bad_json", path=str(path), error=str(exc))
            return None
        if source_type is SourceType.SCHEDULE:
            content = _render_schedule_json(data)
        else:
            content = _render_faq_json(data)
    elif suffix in _TEXT_SUFFIXES:
        content = raw
    else:
        logger.debug("kb_loader_skipped_unsupported", path=str(path), suffix=suffix)
        return None

    if not content.strip():
        return None

    metadata = SourceMetadata(
        title=_read_title(path, raw),
        source=str(path),
        type=source_type,
        cohort=cohort,
    )
    return RawMaterial(metadata=metadata, content=content)


def load_materials(root: Path | str, cohort: str) -> list[RawMaterial]:
    """Load all approved materials for a cohort from a directory tree.

    Walks the known sub-directories (``faqs``, ``schedules``, ``onboarding``,
    ``docs``) beneath ``root``, inferring each file's :class:`SourceType` from
    its directory. Unknown directories and unsupported files are skipped.

    Args:
        root: Root directory holding the cohort's material sub-directories.
        cohort: Cohort identifier stamped onto every loaded material.

    Returns:
        The loaded materials, sorted by source path for deterministic order.

    Raises:
        FileNotFoundError: If ``root`` does not exist.
    """
    root_path = Path(root)
    if not root_path.exists():
        raise FileNotFoundError(f"materials root not found: {root_path}")

    materials: list[RawMaterial] = []
    for subdir, source_type in _DIR_TO_TYPE.items():
        directory = root_path / subdir
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            if not path.is_file():
                continue
            material = _load_file(path, source_type, cohort)
            if material is not None:
                materials.append(material)

    materials.sort(key=lambda item: item.metadata.source)
    logger.info("kb_loader_loaded", cohort=cohort, count=len(materials), root=str(root_path))
    return materials