"""
IngestionRun's surface — the methods the pipeline calls on a publish run.

A module-level helper was once inserted into the middle of the class body,
which Python happily parses (the trailing methods become nested locals of
the helper) and every test stayed green, because tests only exercised the
helper. The first real publish then died at Step 6c with
"'IngestionRun' object has no attribute 'fetch_power_parcel_evidence'".
This file pins the class surface so a split like that fails here instead.
"""

import inspect

import runs


def test_ingestion_run_exposes_every_staging_method():
    required = {
        # lifecycle
        "start", "promote", "fail", "snapshot", "rule_id", "load_rules",
        # curated power evidence
        "fetch_power_parcel_evidence",
        # staged writes — the publish path calls each of these
        "_stage", "stage_grid_parcels", "stage_transmission_lines",
        "stage_substations", "stage_observation_wells",
        "stage_power_rtep_upgrades", "stage_land_parcels",
        "stage_parcel_metrics", "stage_parcel_gates",
    }
    missing = required - set(dir(runs.IngestionRun))
    assert not missing, f"methods fell out of the class body: {sorted(missing)}"


def test_module_helpers_are_module_level_not_class_members():
    # load_rules_readonly and _rows_to_rules are module functions; if they
    # ever land inside the class they stop working for the dry run.
    assert inspect.isfunction(runs.load_rules_readonly)
    assert inspect.isfunction(runs._rows_to_rules)
    assert "load_rules_readonly" not in vars(runs.IngestionRun)
    assert "_rows_to_rules" not in vars(runs.IngestionRun)


def test_class_body_is_contiguous():
    # Once module-level code resumes after `class IngestionRun`, no
    # further 4-space `def` may appear: in the broken layout the class's
    # own trailing methods sat AFTER two module-level defs, silently
    # nested inside the second one instead of belonging to the class.
    src = inspect.getsource(runs).splitlines()
    class_idx = next(i for i, l in enumerate(src)
                     if l.startswith("class IngestionRun"))
    seen_module_level = False
    stray = []
    for line in src[class_idx + 1:]:
        if line and not line[0].isspace():
            seen_module_level = True
        elif seen_module_level and line.startswith("    def "):
            stray.append(line.strip())
    assert not stray, (
        f"class methods defined after module-level code resumed "
        f"(they nest inside a module function, not the class): {stray!r}"
    )
