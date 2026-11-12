"""Reference Nigerian Polling Unit directory, ephemeral GPS Haversine matcher, and zero-PII registration."""

from __future__ import annotations

import math
import uuid

from ..schemas import (
    LocationRegistrationIn,
    LocationRegistrationResponse,
    NearestLocationIn,
    NearestLocationResponse,
    PollingUnitInfo,
)

# Public/synthetic reference directory across Nigerian geopolitical zones (zero real voter PII)
POLLING_UNITS: tuple[PollingUnitInfo, ...] = (
    PollingUnitInfo(
        pu_code="PU-LA-IKJ-004",
        pu_name="Alausa Primary School Courtyard (Unit 004)",
        ward="Alausa / Oregun",
        lga="Ikeja",
        state="Lagos",
        lat=6.6143,
        lon=3.3581,
        accessibility_note="Ground-floor wheelchair ramp & priority queue for elderly and blind/low-vision voters (Section 54 Electoral Act).",
    ),
    PollingUnitInfo(
        pu_code="PU-LA-SUR-011",
        pu_name="National Stadium Gate B Civic Space (Unit 011)",
        ward="Shitta / Ogunlana",
        lga="Surulere",
        state="Lagos",
        lat=6.4972,
        lon=3.3649,
        accessibility_note="Shaded seating for senior citizens and Braille ballot guide support.",
    ),
    PollingUnitInfo(
        pu_code="PU-FC-AMAC-001",
        pu_name="Wuse Zone 3 Community Primary School (Unit 001)",
        ward="Wuse",
        lga="Abuja Municipal (AMAC)",
        state="Federal Capital Territory",
        lat=9.0643,
        lon=7.4699,
        accessibility_note="Paved access, priority queue for elderly & PWDs, shaded verification tent.",
    ),
    PollingUnitInfo(
        pu_code="PU-KN-NAS-002",
        pu_name="Kofar Nassarawa Public Square (Unit 002)",
        ward="Gama / Nassarawa",
        lga="Nassarawa",
        state="Kano",
        lat=12.0022,
        lon=8.5317,
        accessibility_note="Accessible flat entry and Hausa civic assistance desk.",
    ),
    PollingUnitInfo(
        pu_code="PU-EN-ENU-007",
        pu_name="New Haven Primary School Hall (Unit 007)",
        ward="New Haven",
        lga="Enugu North",
        state="Enugu",
        lat=6.4584,
        lon=7.5162,
        accessibility_note="Ground-level hall with seating for elderly voters and Igbo audio assistance.",
    ),
    PollingUnitInfo(
        pu_code="PU-OY-IBN-005",
        pu_name="Bodija Market Civic Pavilion (Unit 005)",
        ward="Bodija",
        lga="Ibadan North",
        state="Oyo",
        lat=7.4314,
        lon=3.9145,
        accessibility_note="Flat entry, Yoruba sign & voice guidance, shaded bench for seniors.",
    ),
    PollingUnitInfo(
        pu_code="PU-RV-PHC-009",
        pu_name="D-Line Model Primary School (Unit 009)",
        ward="Diobu / D-Line",
        lga="Port Harcourt",
        state="Rivers",
        lat=4.8056,
        lon=7.0058,
        accessibility_note="Priority queue for elderly voters, pregnant women, and persons with disabilities.",
    ),
    PollingUnitInfo(
        pu_code="PU-KD-KDN-003",
        pu_name="Ungwan Rimi Civic Centre (Unit 003)",
        ward="Ungwan Rimi",
        lga="Kaduna North",
        state="Kaduna",
        lat=10.5264,
        lon=7.4562,
        accessibility_note="Step-free courtyard access and priority assistance desk.",
    ),
)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2.0) ** 2
    return 2.0 * r * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def list_polling_units() -> list[PollingUnitInfo]:
    """Return all sample/reference polling units."""
    return list(POLLING_UNITS)


def get_polling_unit_by_code(pu_code: str) -> PollingUnitInfo | None:
    """Look up a polling unit by code."""
    for pu in POLLING_UNITS:
        if pu.pu_code.upper() == pu_code.strip().upper():
            return pu
    return None


def find_polling_unit(state: str, lga: str, ward: str) -> PollingUnitInfo:
    """Match a user's selected State / LGA / Ward to its reference polling unit."""
    s_norm = state.strip().lower()
    l_norm = lga.strip().lower()
    w_norm = ward.strip().lower()

    for pu in POLLING_UNITS:
        if pu.state.lower() == s_norm and pu.lga.lower() == l_norm and pu.ward.lower() == w_norm:
            return pu
    for pu in POLLING_UNITS:
        if pu.state.lower() == s_norm and pu.lga.lower() == l_norm:
            return pu
    for pu in POLLING_UNITS:
        if pu.state.lower() == s_norm:
            return pu
    return POLLING_UNITS[0]


def find_nearest_polling_unit(lat: float, lon: float) -> tuple[PollingUnitInfo, float]:
    """Compute nearest reference polling unit by Haversine distance without retaining raw GPS."""
    best_pu = POLLING_UNITS[0]
    best_dist = float("inf")
    for pu in POLLING_UNITS:
        d = _haversine_km(lat, lon, pu.lat, pu.lon)
        if d < best_dist:
            best_dist = d
            best_pu = pu
    return best_pu, round(best_dist, 2)


class LocationRegistryStore:
    """In-memory anonymous location registration store (zero real voter PII or raw GPS)."""

    def __init__(self) -> None:
        self._unit_counts: dict[str, int] = {
            "PU-LA-IKJ-004": 4,
            "PU-FC-AMAC-001": 3,
            "PU-KN-NAS-002": 3,
            "PU-EN-ENU-007": 2,
        }

    def register(self, payload: LocationRegistrationIn) -> LocationRegistrationResponse:
        pu = find_polling_unit(payload.state, payload.lga, payload.ward)
        self._unit_counts[pu.pu_code] = self._unit_counts.get(pu.pu_code, 1) + 1
        return LocationRegistrationResponse(
            session_id=f"LOC-{uuid.uuid4().hex[:8].upper()}",
            citizen_alias=payload.citizen_alias,
            polling_unit=pu,
            nearby_registered_demo_users=self._unit_counts[pu.pu_code],
        )

    def register_nearest(self, payload: NearestLocationIn) -> NearestLocationResponse:
        pu, dist_km = find_nearest_polling_unit(payload.lat, payload.lon)
        self._unit_counts[pu.pu_code] = self._unit_counts.get(pu.pu_code, 1) + 1
        return NearestLocationResponse(
            session_id=f"LOC-{uuid.uuid4().hex[:8].upper()}",
            citizen_alias=payload.citizen_alias,
            polling_unit=pu,
            distance_km=dist_km,
            nearby_registered_demo_users=self._unit_counts[pu.pu_code],
        )
