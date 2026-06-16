"""Contract-parity gate (ADR-0003): the SQLAlchemy models for the three frozen tables
must mirror ``docs/contracts/observation-and-abt.md`` — every contract column present
with matching type-family and nullability. The only permitted extras are additive
provenance columns. Drift fails CI; changing a contract column requires a
``contract_version`` bump in lockstep.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from core.models import AnalyticalBaseTable, ForecastForcing, Observation
from core.models.base import CONTRACT_VERSION

CONTRACT_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "contracts" / "observation-and-abt.md"
)

# contract section number -> model class
SECTION_MODEL = {1: Observation, 2: AnalyticalBaseTable, 3: ForecastForcing}

# additive (non-contract) columns the models are allowed to carry
ALLOWED_EXTRAS = {"created_at", "water_mask_geom"}


def _contract_family(type_cell: str) -> str:
    t = type_cell.strip().lower()
    if t.startswith("text[]"):
        return "array"
    if t.startswith("date"):
        return "date"
    if t.startswith("timestamptz"):
        return "timestamptz"
    if t.startswith("text"):
        return "text"
    if t.startswith("float") or t.startswith("double"):
        return "float"
    if t.startswith("int"):
        return "int"
    if t.startswith("bool"):
        return "bool"
    if t.startswith("jsonb"):
        return "jsonb"
    raise AssertionError(f"unrecognised contract type {type_cell!r}")


def _sa_family(col) -> str:
    name = col.type.__class__.__name__.upper()
    if "ARRAY" in name:
        return "array"
    if "DATETIME" in name or "TIMESTAMP" in name:
        return "timestamptz"
    if name == "DATE":
        return "date"
    if "JSON" in name:
        return "jsonb"
    if name in {"TEXT", "STRING", "VARCHAR"}:
        return "text"
    if "DOUBLE" in name or name in {"FLOAT", "REAL", "NUMERIC"}:
        return "float"
    if "INT" in name:
        return "int"
    if "BOOL" in name:
        return "bool"
    raise AssertionError(f"unmapped SQLAlchemy type {name} for column {col.name}")


def _parse_contract() -> dict[int, dict[str, dict]]:
    """Return {section_no: {col_name: {'family':..., 'nullable':...}}}."""
    sections: dict[int, dict[str, dict]] = {}
    current: int | None = None
    header_re = re.compile(r"^##\s+(\d)\.")
    for line in CONTRACT_PATH.read_text(encoding="utf-8").splitlines():
        m = header_re.match(line)
        if m:
            current = int(m.group(1))
            sections.setdefault(current, {})
            continue
        if current is None or not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4 or not cells[0].startswith("`"):
            continue  # header/separator/short rows
        name = cells[0].strip("`")
        null_cell = cells[3].lower()
        nullable = null_cell.startswith("yes")
        sections[current][name] = {
            "family": _contract_family(cells[1]),
            "nullable": nullable,
        }
    return sections


CONTRACT = _parse_contract()


def test_contract_file_present_and_versioned():
    assert CONTRACT_PATH.exists()
    text = CONTRACT_PATH.read_text(encoding="utf-8")
    assert f"contract_version: {CONTRACT_VERSION}" in text, (
        "model CONTRACT_VERSION must match the markdown's contract_version"
    )


@pytest.mark.parametrize("section,model", SECTION_MODEL.items())
def test_every_contract_column_mirrored(section, model):
    expected = CONTRACT[section]
    assert expected, f"no columns parsed for contract section {section}"
    cols = {c.name: c for c in model.__table__.columns}

    missing = set(expected) - set(cols)
    assert not missing, f"{model.__tablename__} missing contract columns: {sorted(missing)}"

    for name, spec in expected.items():
        col = cols[name]
        fam = _sa_family(col)
        tbl = model.__tablename__
        assert fam == spec["family"], f"{tbl}.{name}: type {fam} != contract {spec['family']}"
        assert col.nullable == spec["nullable"], (
            f"{tbl}.{name}: nullable {col.nullable} != contract {spec['nullable']}"
        )


@pytest.mark.parametrize("section,model", SECTION_MODEL.items())
def test_no_unexpected_extra_columns(section, model):
    extras = {c.name for c in model.__table__.columns} - set(CONTRACT[section])
    assert extras <= ALLOWED_EXTRAS, (
        f"{model.__tablename__} has non-contract columns beyond the allowed extras: "
        f"{sorted(extras - ALLOWED_EXTRAS)}"
    )
