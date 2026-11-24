"""Fix round 2: one test group per reviewer defect D1..D8, through cli.main."""
import io, os, stat, sys
import pytest
import cli

HERE = os.path.dirname(os.path.abspath(__file__))
SHIPPED = os.path.join(HERE, "materials.csv")


def _call(capsys, *args):
    capsys.readouterr()
    code = cli.main(list(args))
    c = capsys.readouterr()
    return code, c.out + c.err


def _write(tmp_path, text, name="m.csv", encoding="utf-8"):
    p = tmp_path / name
    p.write_text(text, encoding=encoding)
    return str(p)


def _db(tmp_path, capsys, csv_text, sel):
    p = str(tmp_path / "t.db")
    code, out = _call(capsys, p, "import-materials", _write(tmp_path, csv_text))
    assert code == 0, out
    code, out = _call(capsys, p, "select", sel)
    assert code == 0, out
    return p


AB = "name,cost,C,Mn\nA,10,2.0,0.0\nB,4,0.0,0.0\n"


# D1
@pytest.mark.parametrize("spec", ["C=nan:nan", "C=0:inf", "C=-inf:1", "C=NaN:1"])
def test_d1_nonfinite_range_rejected(tmp_path, capsys, spec):
    p = _db(tmp_path, capsys, AB, "A,B")
    code, out = _call(capsys, p, "composition", "s", spec)
    assert code == 2 and "not a finite number" in out and "Traceback" not in out


# D2
def test_d2_bom_csv_imports(tmp_path, capsys):
    path = _write(tmp_path, AB, encoding="utf-8-sig")
    code, out = _call(capsys, str(tmp_path / "t.db"), "import-materials", path)
    assert code == 0, out


def test_d2_semicolon_hint(tmp_path, capsys):
    path = _write(tmp_path, "name;cost;C\nA;10;2,0\n")
    code, out = _call(capsys, str(tmp_path / "t.db"), "import-materials", path)
    assert code == 2 and "semicolon-separated; save as comma-separated CSV" in out


def test_d2_cp1252_console_does_not_crash(tmp_path, capsys, monkeypatch):
    p = _db(tmp_path, capsys, AB, "A,B")
    buf = io.BytesIO()
    w = io.TextIOWrapper(buf, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", w)
    monkeypatch.setattr(sys, "stderr", w)
    code = cli.main([p, "select", "Ω中"])
    sys.stdout.flush()
    assert code == 2
    assert b"unknown material" in buf.getvalue()


# D3
@pytest.mark.parametrize("col,row", [("cost", "A,nan,2.0,0.5"), ("C", "A,10,inf,0.5"),
                                     ("max_share", "A,10,2.0,nan")])
def test_d3_nonfinite_csv_values(tmp_path, capsys, col, row):
    path = _write(tmp_path, "name,cost,C,max_share\n" + row + "\n")
    code, out = _call(capsys, str(tmp_path / "t.db"), "import-materials", path)
    assert code == 2
    assert "m.csv" in out and "row 2" in out and f"column {col}: not a finite number" in out


def test_d3_word_infinite_named_plainly(tmp_path, capsys):
    # 'infinite' is not a float literal: must still name file/row/column, not raw Python text
    path = _write(tmp_path, "name,cost,C\nA,infinite,2.0\n")
    code, out = _call(capsys, str(tmp_path / "t.db"), "import-materials", path)
    assert code == 2 and "m.csv: row 2, column cost: not a number: 'infinite'" in out
    assert "could not convert" not in out


@pytest.mark.parametrize("b", ["nan", "inf", "-inf"])
def test_d3_nonfinite_batch(tmp_path, capsys, b):
    p = _db(tmp_path, capsys, AB, "A,B")
    _call(capsys, p, "composition", "s", "C=1:1")
    code, out = _call(capsys, p, "run", "s", b)
    assert code == 2 and "batch size" in out
    for jargon in ("HiGHS", "linprog", "sqlite", "SQLite", "Traceback"):
        assert jargon not in out


# D4
CAPS = "name,cost,C,Mn,max_share\nA,10,2.0,2.0,{a}\nB,4,0.0,0.0,{b}\n"


@pytest.mark.parametrize("a,b,pct", [("0.3", "0.3", "60"), ("0", "0", "0"), ("0.5", "0.49", "99")])
def test_d4_caps_sum_below_100(tmp_path, capsys, a, b, pct):
    p = _db(tmp_path, capsys, CAPS.format(a=a, b=b), "A,B")
    _call(capsys, p, "composition", "s", "C=0:100")
    code, out = _call(capsys, p, "run", "s", "100")
    assert code == 1
    assert (f"the max_share caps of the selected materials add up to {pct}% of the batch; "
            "they must add up to at least 100%") in out


def test_d4_caps_exactly_100_feasible(tmp_path, capsys):
    p = _db(tmp_path, capsys, CAPS.format(a="0.5", b="0.5"), "A,B")
    _call(capsys, p, "composition", "s", "C=1:1")
    code, out = _call(capsys, p, "run", "s", "100")
    assert code == 0 and "  A: 50.000" in out


def test_d4_only_caps_block(tmp_path, capsys):
    # needs 50 kg A for C=1 and Mn=1, cap 0.4 -> only loosening caps helps
    p = _db(tmp_path, capsys, CAPS.format(a="0.4", b="1"), "A,B")
    _call(capsys, p, "composition", "s", "C=1:1,Mn=1:1")
    code, out = _call(capsys, p, "run", "s", "100")
    assert code == 1
    assert "loosening the max_share caps" in out
    assert "Binding element" not in out


def test_d4_caps_near_100_never_shown_as_100(tmp_path, capsys):
    p = _db(tmp_path, capsys, CAPS.format(a="0.5", b="0.49999"), "A,B")
    _call(capsys, p, "composition", "s", "C=0:100")
    code, out = _call(capsys, p, "run", "s", "100")
    assert code == 1 and "add up to 99.999" in out and "add up to 100%" not in out


def test_d4_caps_apply_note_with_binding_element(tmp_path, capsys):
    # mutation guard for the '; max_share caps apply' note: C binding, caps in play
    p = _db(tmp_path, capsys, CAPS.format(a="0.4", b="1"), "A,B")
    _call(capsys, p, "composition", "s", "C=1:1")
    code, out = _call(capsys, p, "run", "s", "100")
    assert code == 1
    assert "max_share caps apply" in out and "Binding element(s): C" in out


def test_d4_cap_actually_applied(tmp_path, capsys):
    # mutation guard: dropping max_share would give 100 kg of cheap B
    p = _db(tmp_path, capsys, CAPS.format(a="1", b="0.3"), "A,B")
    _call(capsys, p, "composition", "s", "C=0:100")
    code, out = _call(capsys, p, "run", "s", "100")
    assert code == 0 and "  B: 30.000" in out and "  A: 70.000" in out


def test_selection_reset_on_reimport(tmp_path, capsys):
    # mutation guard: import must clear the selection
    # A is selected, then a CSV without A is imported: A must not stay selected
    p = _db(tmp_path, capsys, AB, "A")
    _call(capsys, p, "composition", "s", "C=0:100")
    code, out = _call(capsys, p, "import-materials", _write(tmp_path, "name,cost,C,Mn\nB,4,0,0\n", "m2.csv"))
    assert code == 0 and "selection reset" in out
    code, out = _call(capsys, p, "run", "s", "100")
    assert code == 2 and "no materials selected" in out


# D5
@pytest.mark.parametrize("b", ["0.0005", "2e9", "0"])
def test_d5_batch_bounds(tmp_path, capsys, b):
    p = _db(tmp_path, capsys, AB, "A,B")
    _call(capsys, p, "composition", "s", "C=1:1")
    code, out = _call(capsys, p, "run", "s", b)
    assert code == 2 and "0.001" in out


def test_d5_tiny_batch_kg_printed(tmp_path, capsys):
    p = _db(tmp_path, capsys, AB, "A,B")
    _call(capsys, p, "composition", "s", "C=1:1")
    code, out = _call(capsys, p, "run", "s", "0.001")
    assert code == 0
    assert "  A: 0.0005" in out and "  B: 0.0005" in out
    assert "0.000\n" not in out


def test_d5_tiny_component_in_normal_batch(tmp_path, capsys):
    p = str(tmp_path / "t.db")
    _call(capsys, p, "import-materials", SHIPPED)
    _call(capsys, p, "select", "steel_scrap,carburiser")
    _call(capsys, p, "composition", "s", "C=0.205:0.205")
    code, out = _call(capsys, p, "run", "s", "1")
    assert code == 0 and "  carburiser: 5.11" in out and "e-05" in out
    assert "carburiser: 0\n" not in out and "carburiser: 0.000" not in out


# D6
@pytest.mark.parametrize("spec", ["C=1:2,C=0:3", "C=1:2,c=0:3"])
def test_d6_duplicate_element_in_spec(tmp_path, capsys, spec):
    p = _db(tmp_path, capsys, AB, "A,B")
    code, out = _call(capsys, p, "composition", "s", spec)
    assert code == 2 and "duplicate element" in out


@pytest.mark.parametrize("hdr", ["name,cost,C,C", "name,cost,C,c"])
def test_d6_duplicate_header_columns(tmp_path, capsys, hdr):
    path = _write(tmp_path, hdr + "\nA,1,1,1\n")
    code, out = _call(capsys, str(tmp_path / "t.db"), "import-materials", path)
    assert code == 2 and "duplicate" in out and "column" in out


# D7
@pytest.mark.parametrize("name", ["", "   "])
def test_d7_empty_composition_name(tmp_path, capsys, name):
    p = _db(tmp_path, capsys, AB, "A,B")
    code, out = _call(capsys, p, "composition", name, "C=1:1")
    assert code == 2 and "composition name" in out


@pytest.mark.parametrize("args", [["select", "A", "B"], ["run", "s", "100", "x"],
                                  ["import-materials", "m.csv", "x"], ["composition", "s", "C=1:1", "x"]])
def test_d7_extra_args(tmp_path, capsys, args):
    p = _db(tmp_path, capsys, AB, "A,B")
    _call(capsys, p, "composition", "s", "C=1:1")
    code, out = _call(capsys, p, *args)
    assert code == 2 and "too many arguments" in out


def test_d7_select_dedup_and_grammar(tmp_path, capsys):
    p = str(tmp_path / "t.db")
    code, out = _call(capsys, p, "import-materials", _write(tmp_path, "name,cost,C\nA,1,1\n"))
    assert "imported 1 material\n" in out
    code, out = _call(capsys, p, "select", "A,A, A")
    assert code == 0 and "selected: A\n" in out


# D8
def test_d8_not_a_database(tmp_path, capsys):
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"this is not sqlite at all, just some text padding " * 4)
    code, out = _call(capsys, str(bad), "import-materials", SHIPPED)
    assert code == 2 and "bad.db" in out and "not a database" in out.lower() and "hint" in out


def test_d8_locked(tmp_path, capsys):
    import sqlite3
    p = str(tmp_path / "lk.db")
    assert _call(capsys, p, "import-materials", SHIPPED)[0] == 0
    other = sqlite3.connect(p)
    other.execute("BEGIN EXCLUSIVE")
    try:
        code, out = _call(capsys, p, "select", "pig_iron")
    finally:
        other.rollback(); other.close()
    assert code == 2 and "lk.db" in out and "locked" in out and "hint: another program has the database open" in out


def test_d8_read_only(tmp_path, capsys):
    p = str(tmp_path / "ro.db")
    assert _call(capsys, p, "import-materials", SHIPPED)[0] == 0
    os.chmod(p, stat.S_IREAD)
    try:
        code, out = _call(capsys, p, "import-materials", SHIPPED)
    finally:
        os.chmod(p, stat.S_IREAD | stat.S_IWRITE)
    assert code == 2 and "ro.db" in out and "read-only" in out and "hint" in out
