"""Fix round 1: one test per reviewer defect, all through cli.main (exit codes + messages)."""
import os
import pytest
import cli

HERE = os.path.dirname(os.path.abspath(__file__))
SHIPPED = os.path.join(HERE, "materials.csv")
ALL6 = "pig_iron,steel_scrap,hms_scrap,ferro_manganese,ferro_silicon,carburiser"


def _call(capsys, *args):
    capsys.readouterr()
    code = cli.main(list(args))
    return code, capsys.readouterr().out


@pytest.fixture
def db(tmp_path, capsys):
    p = str(tmp_path / "t.db")
    assert _call(capsys, p, "import-materials", SHIPPED)[0] == 0
    assert _call(capsys, p, "select", ALL6)[0] == 0
    return p


def _write(tmp_path, text):
    p = tmp_path / "m.csv"
    p.write_text(text, encoding="utf-8")
    return str(p)


# 7. exact README scenario on the shipped 6x4 data
def test_readme_scenario_exact_numbers(db, capsys):
    assert _call(capsys, db, "composition", "steel1", "C=0.8:1.2,Mn=0.6:1.5")[0] == 0
    code, out = _call(capsys, db, "run", "steel1", "100")
    assert code == 0 and "Traceback" not in out
    vals = {}
    for line in out.splitlines():
        if line.startswith("  ") and ":" in line:
            k, v = line.strip().split(":")
            vals[k] = float(v)
    assert vals["hms_scrap"] == pytest.approx(99.236, abs=2e-3)
    assert vals["ferro_manganese"] == pytest.approx(0.271, abs=2e-3)
    assert vals["carburiser"] == pytest.approx(0.493, abs=2e-3)
    cost = float(out.split("total cost:")[1].split()[0])
    assert cost == pytest.approx(2040.03, abs=0.02)
    assert "not constrained by this composition (0..100 %): Si, P" in out


# 1. unknown element / case-insensitive match
def test_unknown_element_rejected(db, capsys):
    code, out = _call(capsys, db, "composition", "x", "Zz=1:2")
    assert code == 2 and "error: unknown element Zz (known: C, Mn, Si, P)" in out


def test_lowercase_element_matches(db, capsys):
    assert _call(capsys, db, "composition", "x", "c=0.8:1.2,mn=0.6:1.5")[0] == 0
    code, out = _call(capsys, db, "run", "x", "100")
    assert code == 0 and "total cost: 2040.03" in out


# 2. unknown composition name
def test_unknown_composition_rejected(db, capsys):
    _call(capsys, db, "composition", "steel1", "C=0.8:1.2")
    code, out = _call(capsys, db, "run", "nosuch", "100")
    assert code == 2 and "error: unknown composition nosuch (saved: steel1)" in out


# 3. crashes -> clean errors, exit 2
def test_missing_csv(tmp_path, capsys):
    code, out = _call(capsys, str(tmp_path / "d.db"), "import-materials", str(tmp_path / "nope.csv"))
    assert code == 2 and out.startswith("error:") and "nope.csv" in out and "Traceback" not in out


def test_missing_cell(tmp_path, capsys):
    p = _write(tmp_path, "name,cost,C,Mn\nA,10,2.0\n")
    code, out = _call(capsys, str(tmp_path / "d.db"), "import-materials", p)
    assert code == 2 and "row 2, column Mn: missing value" in out and "m.csv" in out


def test_non_numeric_cost(tmp_path, capsys):
    p = _write(tmp_path, "name,cost,C\nA,ten,2.0\n")
    code, out = _call(capsys, str(tmp_path / "d.db"), "import-materials", p)
    assert code == 2 and "row 2, column cost: not a number: 'ten'" in out


# 4. empty select, bad batch, readable infeasible reasons
def test_empty_select(db, capsys):
    code, out = _call(capsys, db, "select", "")
    assert code == 2 and "error: select needs at least one material" in out


@pytest.mark.parametrize("batch", ["0", "-5", "abc"])
def test_bad_batch(db, capsys, batch):
    _call(capsys, db, "composition", "s", "C=0.8:1.2")
    code, out = _call(capsys, db, "run", "s", batch)
    assert code == 2 and "error: batch size must be" in out


def test_infeasible_single_element_reason(db, capsys):
    _call(capsys, db, "select", "steel_scrap,hms_scrap")
    _call(capsys, db, "composition", "s", "C=1:2")
    code, out = _call(capsys, db, "run", "s", "100")
    assert code == 1
    assert "C min 1.0% cannot be met: best selected material has only 0.3%" in out
    assert "HiGHS" not in out and "infeasible" not in out.lower().replace("no feasible", "")


def test_infeasible_max_reason(db, capsys):
    _call(capsys, db, "select", "pig_iron,ferro_manganese")
    _call(capsys, db, "composition", "s", "Mn=0:0.3")
    code, out = _call(capsys, db, "run", "s", "100")
    assert code == 1 and "Mn max 0.3% cannot be met: lowest selected material already has 0.5%" in out


# 5. combined infeasibility -> binding element(s)
def test_combined_infeasible_binding(tmp_path, capsys):
    # A: high C high Mn, B: low both. C>=1.5 needs >=75% A -> Mn>=1.5, but Mn<=1.0.
    p = _write(tmp_path, "name,cost,C,Mn,Si\nA,10,2.0,2.0,0\nB,5,0.0,0.0,0\n")
    d = str(tmp_path / "d.db")
    _call(capsys, d, "import-materials", p); _call(capsys, d, "select", "A,B")
    _call(capsys, d, "composition", "s", "C=1.5:2,Mn=0:1.0,Si=0:1")
    code, out = _call(capsys, d, "run", "s", "100")
    assert code == 1
    assert "combined constraints conflict (targets: C=1.5:2.0, Mn=0.0:1.0, Si=0.0:1.0)" in out
    assert "Binding element(s): C, Mn" in out


# 6. CSV validation
@pytest.mark.parametrize("text,msg", [
    ("name,cost,C\nA,-1,2\n", "column cost: negative cost"),
    ("name,cost,C\nA,1,120\n", "column C: percent 120.0 outside 0..100"),
    ("name,cost,C\nA,1,-0.5\n", "column C: percent -0.5 outside 0..100"),
    ("name,cost,C,max_share\nA,1,2,1.5\n", "column max_share: 1.5 outside 0..1"),
    ("name,cost,C\nA,1,2\nA,3,1\n", "row 3: duplicate material name A (first on row 2)"),
])
def test_csv_validation(tmp_path, capsys, text, msg):
    d = str(tmp_path / "d.db")
    code, out = _call(capsys, d, "import-materials", _write(tmp_path, text))
    assert code == 2 and msg in out
    # nothing half-imported
    assert "unknown material(s): A" in _call(capsys, d, "select", "A")[1]


def test_reimport_prints_selection_reset(db, capsys):
    code, out = _call(capsys, db, "import-materials", SHIPPED)
    assert code == 0 and "note: material selection reset; run select again before run" in out
    _call(capsys, db, "composition", "s", "C=0.8:1.2")
    code, out = _call(capsys, db, "run", "s", "100")
    assert code == 2 and "no materials selected" in out
