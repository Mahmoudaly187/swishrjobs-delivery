"""RBAC plus city / station data scoping, delivered as FastAPI dependencies.

Roles, and what they may reach:

    recruiter        own station only, masked by default, no export
    station_manager  own station, full view with a reason, no export
    operations       every station in their cities
    admin            everything, including export
    auditor          read-only across everything, full view with a reason, no export

Two distinct powers are modelled because the brief separates them: *seeing* full
personal data (``view_full``) and *taking data out* (``export``). Export always
requires an approval id, per criterion 6 and the brief's "exporting require approval".
"""
from __future__ import annotations

from dataclasses import dataclass, field

ROLES: dict[str, dict] = {
    "recruiter": {"scopes": {"station"}, "view_full": False, "export": False, "detokenize": False},
    "station_manager": {"scopes": {"station"}, "view_full": True, "export": False, "detokenize": True},
    "operations": {"scopes": {"city"}, "view_full": True, "export": False, "detokenize": True},
    "admin": {"scopes": {"all"}, "view_full": True, "export": True, "detokenize": True},
    "auditor": {"scopes": {"all"}, "view_full": True, "export": False, "detokenize": False},
}


class AccessDenied(Exception):
    """Raised when a principal reaches outside its scope or lacks a power."""

    def __init__(self, message: str, code: str = "forbidden"):
        super().__init__(message)
        self.code = code


@dataclass
class Principal:
    actor: str
    role: str
    city: str | None = None
    station: str | None = None
    permissions: set[str] = field(default_factory=set)

    @property
    def policy(self) -> dict:
        return ROLES[self.role]

    def can(self, power: str) -> bool:
        return power in self.permissions or self.policy.get(power, False)

    def in_scope(self, city: str | None, station: str | None) -> bool:
        scopes = self.policy["scopes"]
        if "all" in scopes:
            return True
        if "city" in scopes and self.city and city:
            return self.city == city
        if "station" in scopes and self.station and station:
            return self.station == station
        return False

    def require(self, power: str) -> None:
        if not self.can(power):
            raise AccessDenied(f"role {self.role!r} lacks the {power!r} power", code="no_power")

    def require_scope(self, city: str | None, station: str | None) -> None:
        if not self.in_scope(city, station):
            raise AccessDenied(
                f"principal {self.actor!r} is not scoped to city={city!r} station={station!r}",
                code="out_of_scope",
            )


def principal_from_headers(headers: dict) -> Principal:
    """Build a principal from request headers.

    In production this is replaced by the identity provider's claims; the mapping is
    kept explicit so the tests can drive every role without a live IdP.
    """
    role = (headers.get("x-role") or "").strip().lower()
    if role not in ROLES:
        raise AccessDenied("missing or unknown x-role", code="unauthenticated")
    raw = (headers.get("x-permissions") or "").strip()
    perms = {p.strip() for p in raw.split(",") if p.strip()}
    return Principal(
        actor=headers.get("x-actor") or role,
        role=role,
        city=(headers.get("x-city") or "").strip() or None,
        station=(headers.get("x-station") or "").strip() or None,
        permissions=perms,
    )
