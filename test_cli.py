import os
import pytest
import cli, store

HERE = os.path.dirname(os.path.abspath(__file__))


def _csv(tmp_path):
    p = tmp_path / "m.csv"
    p.write_text("name,cost,C,Mn\nA,10,2.0,0.0\nB,4,0.0,0.0\n", encoding="utf-8")
    return str(p)


def test_hand_worked_case_end_to_end(tmp_path, capsys):
    # A: 2% C @10/kg, B: 0% C @4/kg, need exactly 1% C in 100 kg -> 50 A + 50 B, cost 700.
    dbp = str(tmp_path / "demo.db")
    assert cli.main([dbp, "import-materials", _csv(tmp_path)]) == 0
    assert cli.main([dbp, "select", "A,B"]) == 0
    assert cli.main([dbp, "composition", "steel1", "C=1.0:1.0,Mn=0:5"]) == 0
    capsys.readouterr()
    assert cli.main([dbp, "run", "steel1", "100"]) == 0
    out = capsys.readouterr().out
    assert "  A: 50.000" in out and "  B: 50.000" in out
    assert "total cost: 700.00" in out
    assert "  C: 1.0000" in out and "  Mn: 0.0000" in out
    assert "WARNING" not in out


def test_functions_direct():
    db = store.connect()
    p = os.path.join(HERE, "materials.csv")
    assert cli.import_materials(db, p) == 6
    cli.select(db, "steel_scrap,carburiser")
    cli.composition(db, "s", "C=1.0:1.0")
    r = cli.run(db, "s", 100)
    # 0.2a + 98c = 100, a + c = 100 -> c = 80/97.8
    c = 80 / 97.8
    assert r.ok and r.kg == {"steel_scrap": round(100 - c, 3), "carburiser": round(c, 3)}
    assert r.cost == round(24 * (100 - c) + 60 * c, 2)
    assert r.composition["C"] == 1.0


def test_parse_ranges():
    assert cli.parse_ranges("C=0.8:1.2,Mn=0.6:1.5") == {"C": (0.8, 1.2), "Mn": (0.6, 1.5)}
    with pytest.raises(ValueError):
        cli.parse_ranges("C=2:1")


def test_precheck_warning_printed(tmp_path, capsys):
    dbp = str(tmp_path / "d.db")
    cli.main([dbp, "import-materials", _csv(tmp_path)])
    cli.main([dbp, "select", "B"])
    cli.main([dbp, "composition", "x", "C=1:2"])
    capsys.readouterr()
    assert cli.main([dbp, "run", "x", "100"]) == 1
    out = capsys.readouterr().out
    assert "WARNING: C: no selected material contains it" in out
    assert "No feasible blend" in out


def test_select_unknown_material_rejected():
    db = store.connect()
    store.add_material(db, "A", 1, {"C": 1.0})
    with pytest.raises(ValueError):
        cli.select(db, "A,Z")
