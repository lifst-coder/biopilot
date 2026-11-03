"""Enforcement of the "original records are immutable" principle at the ORM layer.

Models opt in by inheriting :class:`ImmutableMixin` and listing protected columns in
``__immutable_fields__`` (use ``"*"`` to protect every column). A ``before_flush``
listener rejects any UPDATE touching those columns and any DELETE of such a row.
Corrections are made by creating *new* records (amendments, re-analyses, decisions).
"""

from __future__ import annotations

from typing import Any, ClassVar

from sqlalchemy import event
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import instance_state

from app.core.errors import ImmutableRecordError


class ImmutableMixin:
    """Marks a model as (partially) immutable once persisted."""

    __immutable_fields__: ClassVar[tuple[str, ...]] = ("*",)


def _changed_protected_fields(obj: ImmutableMixin) -> list[str]:
    state = instance_state(obj)
    protected = obj.__immutable_fields__
    changed: list[str] = []
    for attr in state.mapper.column_attrs:
        if protected != ("*",) and attr.key not in protected:
            continue
        history = state.attrs[attr.key].history
        if history.has_changes() and history.deleted:
            changed.append(attr.key)
    return changed


@event.listens_for(Session, "before_flush")
def _guard_immutable(session: Session, _flush_context: Any, _instances: Any) -> None:
    for obj in session.deleted:
        if isinstance(obj, ImmutableMixin):
            raise ImmutableRecordError(f"{type(obj).__name__} records cannot be deleted")
    for obj in session.dirty:
        if isinstance(obj, ImmutableMixin) and session.is_modified(obj):
            changed = _changed_protected_fields(obj)
            if changed:
                raise ImmutableRecordError(
                    f"{type(obj).__name__} fields are immutable: {', '.join(sorted(changed))}"
                )
