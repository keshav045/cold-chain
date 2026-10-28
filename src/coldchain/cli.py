"""Command line: generate | validate | reproduce | docs."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

from . import schema
from .config import DEFAULT_SEED, SCALES, make_config
from .export import export_all
from .generate import generate
from .validate import validate_dir, write_reports


def _formats(s):
    return tuple(x.strip() for x in s.split(",") if x.strip())


def cmd_generate(a):
    cfg = make_config(a.scale, a.seed, **({"n_shipments": a.shipments} if a.shipments else {}),
                      **({"n_containers": a.containers} if a.containers else {}))
    print(f"generating scale={cfg.scale} seed={cfg.seed} shipments={cfg.n_shipments} containers={cfg.n_containers}")
    res = generate(cfg)
    files = export_all(res, a.out, _formats(a.formats))
    print(f"wrote {len(files)} files to {a.out}")
    if not a.no_validate:
        rep = validate_dir(a.out)
        write_reports(rep, a.out)
        print(f"validation: {'PASS' if rep['ok'] else 'FAIL'}  hard_failures={rep['hard_failures']}  "
              f"precision={rep['ground_truth_comparison']['overall']['precision']} "
              f"recall={rep['ground_truth_comparison']['overall']['recall']}")
        return 0 if rep["ok"] else 1
    return 0


def cmd_validate(a):
    rep = validate_dir(a.data)
    if a.write:
        write_reports(rep, a.data)
    o = rep["ground_truth_comparison"]["overall"]
    print(f"{'PASS' if rep['ok'] else 'FAIL'}  hard_failures={rep['hard_failures']}  precision={o['precision']} recall={o['recall']}")
    for k, v in rep["checks"].items():
        if not v["passed"]:
            print(f"  FAIL {k}: {v['failures']}  {v['examples']}")
    return 0 if rep["ok"] else 1


def cmd_reproduce(a):
    """Generate twice into separate folders and compare row counts + SHA-256 checksums."""
    cfg = make_config(a.scale, a.seed)
    base = a.out or tempfile.mkdtemp(prefix="coldchain-repro-")
    manifests = []
    for run in ("run_a", "run_b"):
        d = os.path.join(base, run)
        print(f"[{run}] generating ...")
        export_all(generate(cfg), d, _formats(a.formats))
        with open(os.path.join(d, "source_manifest.json"), encoding="utf-8") as f:
            manifests.append({x["path"]: (x["rows"], x["content_sha256"]) for x in json.load(f)["files"]})
    a_, b_ = manifests
    rows, ok = [], True
    for p in sorted(a_):
        same = a_[p] == b_.get(p)
        ok &= same
        rows.append({"file": p, "rows": a_[p][0], "sha256_run_a": a_[p][1], "sha256_run_b": b_.get(p, ("", ""))[1], "identical": same})
        print(f"  {'OK ' if same else 'DIFF'} {p:34s} rows={a_[p][0]:>9,}  {a_[p][1][:16]}")
    ok &= set(a_) == set(b_)
    with open(os.path.join(base, "reproducibility.json"), "w", encoding="utf-8") as f:
        json.dump({"seed": cfg.seed, "scale": cfg.scale, "identical": bool(ok), "files": rows}, f, indent=2)
    print("REPRODUCIBLE: identical row counts and checksums" if ok else "NOT REPRODUCIBLE")
    return 0 if ok else 1


def cmd_docs(a):
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "data_dictionary.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(schema.data_dictionary_md())
    with open(os.path.join(a.out, "erd.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(schema.erd_md())
    print(f"wrote data_dictionary.md and erd.md to {a.out}")
    return 0


def main(argv=None):
    _epilog = (
        "Examples:\n"
        "  coldchain generate --scale starter --out ./out\n"
        "  coldchain generate --scale full --seed 20261022 --out ./out --formats csv,json,sql\n"
        "  coldchain validate --data ./out\n"
        "  coldchain validate --data ./out --write\n"
        "  coldchain reproduce --scale starter\n"
        "  coldchain docs --out ./docs\n"
    )
    p = argparse.ArgumentParser(
        prog="coldchain",
        description="Synthetic cold-chain data generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_epilog,
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate", help="generate, export and validate a dataset")
    g.add_argument("--scale", choices=sorted(SCALES), default="full")
    g.add_argument("--seed", type=int, default=DEFAULT_SEED)
    g.add_argument("--out", required=True)
    g.add_argument("--formats", default="csv,json,sql", help="comma list of csv,json,sql (csv is always written)")
    g.add_argument("--shipments", type=int, help="override shipment count")
    g.add_argument("--containers", type=int, help="override container count")
    g.add_argument("--no-validate", action="store_true")
    g.set_defaults(fn=cmd_generate)
    v = sub.add_parser("validate", help="validate an exported dataset directory")
    v.add_argument("--data", required=True)
    v.add_argument("--write", action="store_true", help="(re)write validation_summary.json/md")
    v.set_defaults(fn=cmd_validate)
    r = sub.add_parser("reproduce", help="generate twice and compare checksums")
    r.add_argument("--scale", choices=sorted(SCALES), default="starter")
    r.add_argument("--seed", type=int, default=DEFAULT_SEED)
    r.add_argument("--out")
    r.add_argument("--formats", default="csv,json,sql")
    r.set_defaults(fn=cmd_reproduce)
    d = sub.add_parser("docs", help="write data dictionary + ERD from the schema")
    d.add_argument("--out", default="docs")
    d.set_defaults(fn=cmd_docs)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
