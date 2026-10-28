"""Master data: products, threshold policies, containers, sensors."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .timeutil import date_of

# name, category, tmin, tmax, rhmin, rhmax
PRODUCTS = [
    ("Seasonal Flu Vaccine", "VACCINE", 2.0, 8.0, 30.0, 70.0),
    ("Insulin Pens", "PHARMA_COLD", 2.0, 8.0, 30.0, 70.0),
    ("Frozen Seafood", "FROZEN_FOOD", -25.0, -18.0, 40.0, 80.0),
    ("Ice Cream", "FROZEN_FOOD", -26.0, -18.0, 40.0, 80.0),
    ("Fresh Dairy", "CHILLED_FOOD", 1.0, 5.0, 50.0, 80.0),
    ("Leafy Greens", "PRODUCE", 0.0, 6.0, 85.0, 97.0),
    ("Fresh Berries", "PRODUCE", 0.0, 4.0, 85.0, 95.0),
    ("Frozen Plasma", "FROZEN_PHARMA", -30.0, -20.0, 25.0, 60.0),
]
# permissible excursion minutes (v1, v2) -- v2 is stricter
MAX_EXC = {"VACCINE": (45, 30), "PHARMA_COLD": (45, 30), "FROZEN_FOOD": (120, 90),
           "CHILLED_FOOD": (90, 60), "PRODUCE": (90, 60), "FROZEN_PHARMA": (45, 30)}
CRIT_T, CRIT_H = 5.0, 12.0
CONTAINER_TYPES = ["REEFER_40FT", "REEFER_20FT", "INSULATED_SHIPPER"]
V1_FROM, V1_TO, V2_FROM = "2025-01-01", "2026-06-30", "2026-07-01"


@dataclass
class Master:
    products: list
    policies: list
    containers: list
    sensors: list
    expired_containers: set

    def policy_for(self, product_id: str, date: str) -> dict:
        for p in self.policies:
            if p["product_id"] == product_id and p["effective_from"] <= date and (
                    p["effective_to"] is None or date <= p["effective_to"]):
                return p
        raise KeyError((product_id, date))


def build(cfg, rng) -> Master:
    products, policies = [], []
    for i, (name, cat, tmin, tmax, rmin, rmax) in enumerate(PRODUCTS, start=1):
        pid = f"PRD-{i:04d}"
        products.append(dict(product_id=pid, name=name, category=cat,
                             target_temp_c=(tmin + tmax) / 2, target_rh_pct=(rmin + rmax) / 2))
        for v, (frm, to) in enumerate([(V1_FROM, V1_TO), (V2_FROM, None)], start=1):
            policies.append(dict(
                policy_id=f"POL-{(i - 1) * 2 + v:06d}", product_id=pid, version=v,
                temp_min_c=tmin, temp_max_c=tmax, rh_min_pct=rmin, rh_max_pct=rmax,
                max_excursion_minutes=MAX_EXC[cat][v - 1],
                critical_margin_temp_c=CRIT_T, critical_margin_rh_pct=CRIT_H,
                effective_from=frm, effective_to=to))
    containers, sensors = [], []
    n_exp = max(1, round(cfg.expired_sensor_rate * cfg.n_containers))
    expired = set(int(x) for x in rng.choice(cfg.n_containers, size=n_exp, replace=False))
    for c in range(cfg.n_containers):
        cid = f"CNT-{c + 1:06d}"
        containers.append(dict(container_id=cid, container_type=CONTAINER_TYPES[int(rng.integers(0, 3))], status="ACTIVE"))
        if c in expired:  # calibration lapsed during sim_year
            cal = int(rng.integers(0, 150))   # days after Jan-15 of the preceding year
            cal_date = _add_days(f"{cfg.sim_year - 1}-01-15", cal)
            due = _add_days(cal_date, 365)
        else:             # calibrated around the turn of the year, 540-day interval
            cal_date = _add_days(f"{cfg.sim_year - 1}-12-01", int(rng.integers(0, 33)))
            due = _add_days(cal_date, 540)
        sensors.append(dict(sensor_id=f"SNS-{cid}-TEMP", container_id=cid, calibration_date=cal_date,
                            calibration_due=due, valid_temp_min_c=-50.0, valid_temp_max_c=85.0,
                            valid_rh_min_pct=0.0, valid_rh_max_pct=100.0))
    return Master(products, policies, containers, sensors, expired)


def _add_days(date: str, days: int) -> str:
    import datetime as dt
    return (dt.date.fromisoformat(date) + dt.timedelta(days=days)).isoformat()
