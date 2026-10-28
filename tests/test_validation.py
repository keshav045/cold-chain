"""The validator: passes clean data, and fails loudly on every kind of corruption (mutation tests)."""
import numpy as np
import pytest

from coldchain.validate import load_dir, validate_dir, validate_tables


def test_clean_dataset_passes_with_perfect_precision_and_recall(starter_dir):
    rep = validate_dir(starter_dir)
    assert rep["ok"] and rep["hard_failures"] == 0
    o = rep["ground_truth_comparison"]["overall"]
    assert o["precision"] == 1.0 and o["recall"] == 1.0
    for issue, v in rep["ground_truth_comparison"]["by_issue_type"].items():
        assert v["false_positive"] == 0 and v["false_negative"] == 0, issue
        assert v["expected"] > 0, issue
    assert rep["checks"]["sqlite.foreign_key_check"]["passed"]


def test_each_injected_anomaly_is_found_by_the_validator_and_is_in_ground_truth(starter_dir):
    T, gt = load_dir(starter_dir)
    rep = validate_tables(T, gt)
    for issue, v in rep["ground_truth_comparison"]["by_issue_type"].items():
        assert v["detected"] == v["expected"] > 0, issue


def test_validator_without_ground_truth_flags_nothing_unexpected(tables):
    T, _ = tables
    assert validate_tables(T, None)["hard_failures"] == 0


def _hard(rep, name):
    return rep["checks"][name]["failures"]


def test_deleting_a_gap_row_is_caught(tables):
    T, gt = tables
    T["data_gap"] = T["data_gap"].iloc[1:]
    rep = validate_tables(T, gt)
    assert not rep["ok"] and _hard(rep, "gap.flagged") >= 1


def test_treating_a_gap_as_safe_by_filling_it_is_caught(tables):
    T, gt = tables
    rd = T["sensor_reading"]
    g = T["data_gap"].iloc[0]
    sid = g["shipment_id"]
    from coldchain.timeutil import iso, compact, to_minutes
    last = to_minutes(__import__("pandas").Series([g["last_reading_ts"]]))[0]
    sensor = rd[rd["shipment_id"] == sid]["sensor_id"].iloc[0]
    m = last + 5
    new = rd[rd["shipment_id"] == sid].iloc[[0]].copy()
    new["timestamp"], new["reading_id"] = iso([m])[0], f"RDG-{sensor}-{compact([m])[0]}"
    T["sensor_reading"] = __import__("pandas").concat([rd, new], ignore_index=True)
    rep = validate_tables(T, gt)
    assert not rep["ok"]


def test_corrupting_an_fk_is_caught(tables):
    T, gt = tables
    T["shipment"].loc[T["shipment"].index[0], "container_id"] = "CNT-999999"
    rep = validate_tables(T, gt)
    assert not rep["ok"] and _hard(rep, "schema.fk") >= 1


def test_bad_id_format_and_enum_are_caught(tables):
    T, gt = tables
    T["product"].loc[0, "product_id"] = "PRD-1"
    T["excursion"].loc[T["excursion"].index[0], "severity"] = "SEVERE"
    rep = validate_tables(T, gt)
    assert _hard(rep, "schema.format") >= 1 and _hard(rep, "schema.enums") >= 1


def test_duplicate_primary_key_is_caught(tables):
    T, gt = tables
    T["container"].loc[1, "container_id"] = T["container"].loc[0, "container_id"]
    assert _hard(validate_tables(T, gt), "schema.pk_unique") >= 1


def test_wrong_severity_or_status_is_caught(tables):
    T, gt = tables
    i = T["excursion"].index[0]
    T["excursion"].loc[i, "severity"] = "CRITICAL" if T["excursion"].loc[i, "severity"] != "CRITICAL" else "BRIEF"
    rep = validate_tables(T, gt)
    assert not rep["ok"] and _hard(rep, "excursion.values") >= 1


def test_tampered_reading_changes_recomputed_excursions(tables):
    T, gt = tables
    rd = T["sensor_reading"]
    ex = T["excursion"].iloc[0]
    mask = (rd["shipment_id"] == ex["shipment_id"]) & (rd["timestamp"] == ex["start_ts"])
    rd.loc[mask, "temperature_c"] = 5.0 if ex["metric"] == "TEMPERATURE" else rd.loc[mask, "temperature_c"]
    rd.loc[mask & (ex["metric"] == "HUMIDITY"), "humidity_pct"] = 50.0
    rep = validate_tables(T, gt)
    assert not rep["ok"]


def test_leaking_ground_truth_into_inputs_is_caught(tables):
    T, gt = tables
    T["shipment"]["issue_type"] = "WRONG_POLICY"
    assert _hard(validate_tables(T, gt), "schema.no_leakage") >= 1


def test_missing_ground_truth_row_means_false_positive(tables):
    T, gt = tables
    rep = validate_tables(T, gt.iloc[1:])
    assert not rep["ok"] and rep["ground_truth_comparison"]["overall"]["false_positive"] == 1


def test_extra_ground_truth_row_means_false_negative(tables):
    T, gt = tables
    extra = gt.iloc[[0]].copy()
    extra["entity_id"] = "SHP-2026-999999"
    import pandas as pd
    rep = validate_tables(T, pd.concat([gt, extra], ignore_index=True))
    assert not rep["ok"] and rep["ground_truth_comparison"]["overall"]["false_negative"] == 1


def test_container_overlap_is_caught(tables):
    T, gt = tables
    s = T["shipment"]
    c = s["container_id"].value_counts().index[0]
    ids = s[s["container_id"] == c]["shipment_id"].tolist()
    # make the 2nd shipment's route start at the same time as the 1st
    rs = T["route_stop"]
    first = rs[(rs["shipment_id"] == ids[0]) & (rs["sequence"] == 1)].iloc[0]
    j = rs.index[(rs["shipment_id"] == ids[1]) & (rs["sequence"] == 1)][0]
    for col in ("actual_departure", "actual_arrival", "planned_departure", "planned_arrival"):
        rs.loc[j, col] = first[col]
    assert _hard(validate_tables(T, gt), "shipment.container_no_overlap") >= 1


def test_duplicate_reading_is_caught(tables):
    import pandas as pd
    T, gt = tables
    rd = T["sensor_reading"]
    T["sensor_reading"] = pd.concat([rd, rd.iloc[[10]]], ignore_index=True)
    rep = validate_tables(T, gt)
    assert not rep["ok"] and _hard(rep, "reading.no_duplicates") >= 1


def test_reading_counts_reconcile_with_listed_gaps(tables):
    """Readings present + missing intervals listed in data_gap must equal the expected 5-minute slots."""
    T, gt = tables
    T["data_gap"].loc[T["data_gap"].index[0], "missing_readings"] += 1
    rep = validate_tables(T, gt)
    assert not rep["ok"] and _hard(rep, "reconcile.reading_counts") >= 1


def test_exports_are_consistent_across_csv_json_and_sqlite(starter_dir):
    rep = validate_dir(starter_dir)
    assert rep["checks"]["format.consistency"]["passed"]


def test_tampered_json_export_is_caught(starter_dir, tmp_path):
    import json, shutil
    d = tmp_path / "copy"
    shutil.copytree(starter_dir, d)
    p = d / "container.json"
    rows = json.loads(p.read_text())
    p.write_text(json.dumps(rows[:-1]))
    rep = validate_dir(str(d))
    assert not rep["ok"] and rep["checks"]["format.consistency"]["failures"] >= 1
