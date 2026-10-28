"""Properties of the generated dataset."""
import re

import pandas as pd
import pytest

from coldchain import schema
from coldchain.config import SCALES, make_config
from coldchain.export import export_all
from coldchain.generate import generate
from coldchain.timeutil import to_minutes


def test_all_ids_match_their_zero_padded_formats(result):
    for t in schema.TABLES:
        for f in t.fields:
            if f.regex:
                s = result.tables[t.name][f.name].dropna().astype(str)
                assert s.str.fullmatch(f.regex).all(), (t.name, f.name)


def test_ids_are_unique_and_sequential_where_counters(result):
    for tbl, col, prefix in [("shipment", "shipment_id", "SHP-2026-"), ("excursion", "excursion_id", "EXC-2026-"),
                             ("notification", "notification_id", "NTF-2026-"), ("custody_event", "custody_id", "CUS-2026-")]:
        ids = result.tables[tbl][col]
        nums = [int(i[len(prefix):]) for i in ids]
        assert ids.is_unique and sorted(nums) == list(range(1, len(nums) + 1)), tbl
    assert result.tables["container"]["container_id"].iloc[0] == "CNT-000001"
    assert result.tables["sensor"]["sensor_id"].iloc[0] == "SNS-CNT-000001-TEMP"
    r = result.tables["sensor_reading"]["reading_id"].iloc[0]
    assert re.fullmatch(r"RDG-SNS-CNT-\d{6}-TEMP-\d{8}T\d{6}Z", r)


def test_same_seed_gives_identical_data_and_different_seed_differs(tmp_path):
    cfg = make_config("starter", n_shipments=12, n_containers=5)
    a, b = tmp_path / "a", tmp_path / "b"
    fa = export_all(generate(cfg), str(a), ("csv", "json", "sql"))
    fb = export_all(generate(cfg), str(b), ("csv", "json", "sql"))
    assert fa == fb and all(v["content_sha256"] for v in fa.values())
    fc = export_all(generate(make_config("starter", seed=7, n_shipments=12, n_containers=5)), str(tmp_path / "c"), ("csv",))
    assert fc["sensor_reading.csv.gz"]["content_sha256"] != fa["sensor_reading.csv.gz"]["content_sha256"]


def test_starter_and_full_share_one_code_path_and_the_documented_volumes():
    assert SCALES["full"] == {"n_shipments": 1000, "n_containers": 300}
    s, f = make_config("starter"), make_config("full")
    assert (s.interval_min, s.seed, s.scenario_mix) == (f.interval_min, f.seed, f.scenario_mix)
    mid = generate(make_config("starter", n_shipments=20, n_containers=6))   # any scale runs through generate()
    assert len(mid.tables["shipment"]) == 20 and len(mid.tables["container"]) == 6


def test_cadence_and_trip_length(result):
    rd, ships = result.tables["sensor_reading"], result.tables["shipment"]
    for sid, g in rd.groupby("shipment_id"):
        d = pd.Series(to_minutes(g["timestamp"])).diff().dropna()
        assert (d % 5 == 0).all() and (d >= 5).all()
    s = ships[ships["actual_arrival"] > ships["actual_departure"]]
    days = (to_minutes(s["actual_arrival"]) - to_minutes(s["actual_departure"])) / 1440
    assert days.min() >= 2 and days.max() <= 5


def test_no_container_overlap_and_every_reading_fk_resolves(result):
    T = result.tables
    rs = T["route_stop"]
    w = []
    for sid, g in rs.groupby("shipment_id"):
        g = g.sort_values("sequence")
        w.append((T["shipment"].set_index("shipment_id").loc[sid, "container_id"],
                  to_minutes(g["actual_departure"])[0], to_minutes(g["actual_arrival"])[-1]))
    df = pd.DataFrame(w, columns=["c", "s", "e"]).sort_values(["c", "s"])
    for _, g in df.groupby("c"):
        assert (g["s"].to_numpy()[1:] >= g["e"].to_numpy()[:-1]).all()
    assert T["sensor_reading"]["shipment_id"].isin(T["shipment"]["shipment_id"]).all()
    assert T["sensor_reading"]["sensor_id"].isin(T["sensor"]["sensor_id"]).all()


def test_no_ground_truth_leaks_into_input_tables(result):
    for name, df in result.tables.items():
        assert not (set(df.columns) & schema.FORBIDDEN_INPUT_COLUMNS), name
    gt_ids = set(result.ground_truth["gt_id"])
    for name, df in result.tables.items():
        for c in df.select_dtypes(include=["object", "string"]).columns:
            assert not df[c].isin(gt_ids).any()


def test_every_edge_case_and_scenario_is_present_even_at_starter_scale(result):
    assert set(result.ground_truth["issue_type"]) == {
        "OUT_OF_PHYSICAL_RANGE", "SENSOR_DROPOUT_GAP", "DELIVERY_BEFORE_DEPARTURE", "WRONG_POLICY",
        "DURATION_UNDERCOUNTED", "CALIBRATION_FAILURE", "ROUTE_DELAY",
        "EXCURSION_BRIEF", "EXCURSION_PROLONGED", "EXCURSION_CRITICAL"}


def test_boundary_scenarios_are_generated(result):
    gt = result.ground_truth
    ex = result.tables["excursion"].set_index("excursion_id")
    pol = result.tables["threshold_policy"].set_index("policy_id")
    hits = set()
    for eid in gt[gt["issue_type"].str.startswith("EXCURSION_")]["entity_id"]:
        e = ex.loc[eid]
        m = pol.loc[e["policy_id"], "max_excursion_minutes"]
        if e["duration_minutes"] == m:
            hits.add("at_limit")
        if e["duration_minutes"] == m + 5:
            hits.add("just_over")
    assert hits == {"at_limit", "just_over"}


def test_derived_values_come_from_readings_not_random_labels(result):
    """Every excursion duration (before deliberate undercounting) equals (end - start) + 5 min."""
    ex = result.tables["excursion"]
    calc = (to_minutes(ex["end_ts"]) - to_minutes(ex["start_ts"])) + 5
    under = set(result.ground_truth.query("issue_type == 'DURATION_UNDERCOUNTED'")["entity_id"])
    ok = (ex["duration_minutes"].to_numpy() == calc) | ex["excursion_id"].isin(under).to_numpy()
    assert ok.all()
