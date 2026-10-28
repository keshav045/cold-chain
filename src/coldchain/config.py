"""Generator configuration. Every tunable lives here; nothing is random outside the seed."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

DEFAULT_SEED = 20261022

SCALES = {
    "full": {"n_shipments": 1000, "n_containers": 300},
    "starter": {"n_shipments": 50, "n_containers": 15},
}


@dataclass
class Config:
    seed: int = DEFAULT_SEED
    scale: str = "full"
    n_shipments: int = 1000
    n_containers: int = 300
    interval_min: int = 5  # reading cadence (minutes)
    min_trip_days: int = 2
    max_trip_days: int = 5
    first_departure_day: int = 4  # days after simulation start (2026-01-01 UTC)
    last_departure_day: int = 354
    turnaround_min: int = 720  # minimum idle time between two shipments of a container
    # Scenario quotas (each at least 1 shipment, remainder is CLEAN).
    scenario_mix: dict = field(
        default_factory=lambda: {
            "BRIEF": 0.14,
            "PROLONGED": 0.10,
            "CRITICAL": 0.04,
            "DROPOUT": 0.08,
            "STUCK": 0.03,
            "ROUTE_DELAY": 0.08,
        }
    )
    expired_sensor_rate: float = 0.05  # share of sensors whose calibration lapsed in 2026
    p_delay_induced_excursion: float = 0.6
    # Record-level defects (each at least 1 instance)
    rate_delivery_before_departure: float = 0.015
    rate_wrong_policy: float = 0.015
    rate_duration_undercounted: float = 0.05  # of excursions
    rate_physical_range: float = 0.0001  # of readings
    sim_year: int = 2026

    def to_dict(self) -> dict:
        return asdict(self)


def make_config(scale: str = "full", seed: int = DEFAULT_SEED, **overrides) -> Config:
    if scale not in SCALES:
        raise ValueError(f"unknown scale {scale!r}; choose from {sorted(SCALES)}")
    params = dict(SCALES[scale])
    params.update(overrides)
    cfg = Config(seed=seed, scale=scale, **params)
    # Guard: ensure there is a valid duration range even under the worst-case ROUTE_DELAY
    # (delta_max = 145*5 = 725 min).  If this check fails, reduce ROUTE_DELAY quota or raise max_trip_days.
    delta_max = 145 * 5  # see scheduling.py: rng.integers(36, 145) * 5
    dur_min = cfg.min_trip_days * 1440
    dur_max_worst = cfg.max_trip_days * 1440 - delta_max - 45
    if dur_max_worst < dur_min:
        raise ValueError(
            f"max_trip_days={cfg.max_trip_days} is too small: with the maximum ROUTE_DELAY ({delta_max} min) "
            f"dur_max ({dur_max_worst}) would be less than min trip duration ({dur_min} min). "
            f"Increase max_trip_days or reduce min_trip_days."
        )
    return cfg
