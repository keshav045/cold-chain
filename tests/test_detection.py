"""Unit tests of the detection engine and rules on hand-built readings."""
import numpy as np

from coldchain.detection import derive_excursions, find_gaps, find_runs, quality_codes, stuck_mask
from coldchain.rules import classify

POL = dict(temp_min_c=2.0, temp_max_c=8.0, rh_min_pct=30.0, rh_max_pct=70.0, max_excursion_minutes=30,
           critical_margin_temp_c=5.0, critical_margin_rh_pct=12.0)


def series(temps, start=0, step=5):
    ts = start + step * np.arange(len(temps), dtype=np.int64)
    t = np.array(temps, dtype=float)
    return ts, t, np.full(len(t), 50.0)


def exc(temps, **kw):
    ts, t, rh = series(temps)
    codes = np.full(len(ts), "GOOD", dtype=object)
    return derive_excursions(ts, t, rh, codes, POL)


def test_duration_convention_adds_one_interval():
    e = exc([5, 9, 9, 9, 5])               # 3 readings out of range
    assert len(e) == 1 and e[0]["duration"] == 15     # (last - first) + 5 = 10 + 5
    assert e[0]["direction"] == "HIGH" and e[0]["peak_value"] == 9.0 and e[0]["peak_deviation"] == 1.0


def test_single_reading_excursion_is_5_minutes():
    assert exc([5, 8.5, 5])[0]["duration"] == 5


def test_boundary_exactly_at_permissible_minutes_is_brief_and_one_more_is_prolonged():
    assert classify(30, 1.0, 30, 5.0) == "BRIEF"        # == max_excursion_minutes -> tolerated
    assert classify(35, 1.0, 30, 5.0) == "PROLONGED"    # one reading over
    assert classify(85, 1.0, 30, 5.0) == "PROLONGED"
    assert classify(90, 1.0, 30, 5.0) == "CRITICAL"     # >= 3x permissible
    assert classify(5, 5.0, 30, 5.0) == "CRITICAL"      # deep breach even if short
    e = exc([5] + [9] * 6 + [5])                         # 6 readings = 30 min
    assert e[0]["duration"] == 30 and e[0]["severity"] == "BRIEF"
    e = exc([5] + [9] * 7 + [5])                         # 35 min
    assert e[0]["severity"] == "PROLONGED"


def test_values_exactly_on_the_limit_are_in_range():
    assert exc([2.0, 8.0, 2.0, 8.0]) == []


def test_low_and_high_breaches_are_separate_excursions():
    e = exc([5, 9, 1, 5])
    assert [x["direction"] for x in e] == ["HIGH", "LOW"] and all(x["duration"] == 5 for x in e)


def test_gap_is_never_treated_as_in_range_and_never_bridged():
    ts = np.array([0, 5, 10, 30, 35, 40], dtype=np.int64)      # 15 and 20 are missing
    t = np.array([5, 9, 9, 9, 9, 5], dtype=float)
    rh = np.full(6, 50.0)
    codes = np.full(6, "GOOD", dtype=object)
    assert find_gaps(ts) == [(10, 30, 3)]
    runs = find_runs(ts, t, 2.0, 8.0, np.ones(6, bool))
    assert len(runs) == 2                                       # the run is split at the gap
    e = derive_excursions(ts, t, rh, codes, POL)
    assert [x["duration"] for x in e] == [10, 10]               # the 15 missing minutes are NOT counted as out-of-range...
    assert find_gaps(ts)[0][2] == 3                              # ...nor as in-range: they are reported as unverified


def test_faulty_reading_is_excluded_and_flagged():
    ts, t, rh = series([5, 5, 150.0, 5, 5])
    codes, _ = quality_codes(ts, t, rh, (-50, 85, 0, 100), expired=False)
    assert list(codes) == ["GOOD", "GOOD", "SENSOR_FAULT", "GOOD", "GOOD"]
    assert derive_excursions(ts, t, rh, codes, POL) == []       # not a real excursion


def test_stuck_sensor_and_expired_calibration_are_low_trust():
    ts, t, rh = series([5.0 + 0.01 * i for i in range(5)] + [5.5] * 12 + [5.1, 5.2])
    stuck = stuck_mask(ts, t, rh)
    assert stuck.sum() == 12 and stuck[5:17].all()
    codes, _ = quality_codes(ts, t, rh, (-50, 85, 0, 100), expired=False)
    assert (codes == "LOW_TRUST").sum() == 12
    codes, _ = quality_codes(ts, t, rh, (-50, 85, 0, 100), expired=True)
    assert (codes == "LOW_TRUST").all()
    short = stuck_mask(*series([5.5] * 11 + [5.1])[:3])
    assert not short.any()                                       # 11 identical readings is not a stuck run


def test_evidence_quality_low_trust_propagates_to_excursion():
    ts, t, rh = series([5, 9, 9, 5])
    codes = np.array(["GOOD", "LOW_TRUST", "GOOD", "GOOD"], dtype=object)
    assert derive_excursions(ts, t, rh, codes, POL)[0]["evidence"] == "LOW_TRUST"


def test_to_minutes_is_resolution_independent_and_null_safe():
    """Regression: pandas 3 parses to datetime64[us]; a hard-coded ns divisor collapsed every time to one value."""
    import pandas as pd
    from coldchain.timeutil import to_minutes
    m = to_minutes(pd.Series(["2026-01-01T00:00:00Z", "2026-01-01T00:05:00Z", "2026-01-02T00:00:00Z", None, "garbage"]))
    assert list(m[:3] - m[0]) == [0, 5, 1440] and list(m[3:]) == [-1, -1]
    assert m[0] == 29453760  # 2026-01-01T00:00Z in epoch minutes
