"""Run records, the ledger, bundles (sealed test splits) and the hello job's smoke run."""

import json

import duckdb
import pytest
import statsbomb_fixture as fx
import yaml

from rondo.core import bundle, hello, runs

BUDGET = {
    "as_of": "2026-11-08",
    "total_su": 100,
    "split": {"value": 0.6, "scout": 0.4},
    "rerun_reserve_fraction": 0.2,
}


def test_hello_smoke_writes_a_run_folder(tmp_path):
    metrics = hello.run(tmp_path, smoke=True)
    (run_dir,) = tmp_path.iterdir()
    for name in ("config.yaml", "git_sha", "env.txt", "metrics.json", "run.json"):
        assert (run_dir / name).exists(), name
    assert metrics["gcn_forward_backward"]["ms"] > 0
    record = json.loads((run_dir / "run.json").read_text())
    assert record["outcome"] == "ok" and record["track"] == "core"


def test_metrics_json_refuses_test_results(tmp_path):
    run_dir, record = runs.start_run(tmp_path, "value", "m", {"a": 1})
    with pytest.raises(ValueError):
        runs.finish_run(run_dir, record, 1.0, "ok", {"test_auc": 0.7})


def test_ledger_charges_sus_by_gpu_type():
    recs = [
        runs.RunRecord("r1", "value", "m", "h", "abc1234", "V100", "t", 7200, 2.0, "ok"),
        runs.RunRecord("r2", "scout", "m", "h", "abc1234", "H100", "t", 1800, 1.0, "ok"),
    ]
    text = runs.render_ledger(recs, BUDGET)
    assert "| value | 60% | 60.0 | 12.0 | 2.00 | 58.0 |" in text
    assert "| scout | 40% | 40.0 | 8.0 | 1.00 | 39.0 |" in text


def test_config_hash_ignores_key_order():
    assert runs.config_hash({"a": 1, "b": 2}) == runs.config_hash({"b": 2, "a": 1})


def test_split_overlap_rejected(tmp_path):
    p = tmp_path / "split.yaml"
    p.write_text(yaml.safe_dump({"unit": "match_id", "train": [1, 2], "val": [], "test": [2]}))
    with pytest.raises(ValueError, match="both train and test"):
        bundle.load_split(p)


def _ids_in(path, unit):
    return {
        r[0] for r in duckdb.connect().execute(f"select distinct {unit} from '{path}'").fetchall()
    }


@pytest.mark.synthetic_only
def test_bundles_seal_the_test_split(sb_store, tmp_path):
    train_id, test_id = fx.MATCH_IDS
    split = tmp_path / "split.yaml"
    split.write_text(
        yaml.safe_dump({"unit": "match_id", "train": [train_id], "val": [], "test": [test_id]})
    )
    cfg = tmp_path / "m.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "data": {
                    "split_file": str(split),
                    "tables": {"spadl_actions": ["match_id", "action_id", "type_name"]},
                }
            }
        )
    )
    kw = dict(
        parquet=sb_store.parquet, out_dir=tmp_path / "dist", config_path=cfg, allow_dirty=True
    )
    for which, expected in (("train", {train_id}), ("eval", {test_id})):
        path = bundle.build_bundle("value/m", which, **kw)
        assert (path.parent / f"{path.name}.sha256").exists()
        dest = tmp_path / which
        manifest = bundle.read_bundle(path, dest)
        assert _ids_in(dest / "data" / "spadl_actions.parquet", "match_id") == expected
        split_json = json.loads((dest / "split.json").read_text())
        if which == "train":
            assert "test" not in split_json
        else:
            assert set(split_json) == {"unit", "test"}
        assert manifest["tables"]["spadl_actions"]["columns"] == [
            "match_id",
            "action_id",
            "type_name",
        ]
        assert (dest / "code" / "uv.lock").exists()
