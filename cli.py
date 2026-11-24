"""Command line front end for the blend optimiser.

Usage:
  python cli.py DB import-materials materials.csv
  python cli.py DB select A,B,C
  python cli.py DB composition NAME "C=0.8:1.2,Mn=0.6:1.5"
  python cli.py DB run NAME BATCH_KG

Exit codes: 0 ok, 1 no feasible blend, 2 input error.
"""
import csv, math, sqlite3, sys
import store

BATCH_MIN, BATCH_MAX = 0.001, 1e9
NARGS = {"import-materials": 1, "select": 1, "composition": 2, "run": 2}


def _num(text, path, rownum, col):
    where = f"{path}: row {rownum}, column {col}"
    if text is None or text.strip() == "":
        raise ValueError(f"{where}: missing value")
    try:
        v = float(text)
    except ValueError:
        raise ValueError(f"{where}: not a number: {text!r}") from None
    if not math.isfinite(v):
        raise ValueError(f"{where}: not a finite number: {text.strip()!r}")
    return v


def read_materials(csv_path):
    """Validate the whole CSV first; returns [(name, cost, pct, max_share)]. Row numbers count the header as row 1."""
    try:
        f = open(csv_path, newline="", encoding="utf-8-sig")
    except OSError as e:
        raise ValueError(f"cannot open materials file {csv_path}: {e.strerror}") from None
    with f:
        try:
            first = f.readline()
        except UnicodeDecodeError:
            raise ValueError(f"{csv_path}: not UTF-8 text; save it from Excel as 'CSV UTF-8 (comma delimited)'") from None
        f.seek(0)
        if first.count(";") > first.count(","):
            raise ValueError(f"{csv_path}: file looks semicolon-separated; save as comma-separated CSV")
        reader = csv.DictReader(f)
        header = [h.strip() for h in (reader.fieldnames or [])]
        if "name" not in header or "cost" not in header:
            raise ValueError(f"{csv_path}: header must contain name and cost columns (got: {', '.join(header) or 'empty file'})")
        low = {}
        for h in header:
            if h.lower() in low:
                raise ValueError(f"{csv_path}: header has duplicate column {h} (clashes with {low[h.lower()]}; "
                                 "column names are case-insensitive)")
            low[h.lower()] = h
        reader.fieldnames = header
        elements = [h for h in header if h not in ("name", "cost", "max_share")]
        out, seen = [], {}
        try:
            for i, row in enumerate(reader, start=2):
                if None in row:
                    raise ValueError(f"{csv_path}: row {i}: more cells than header columns")
                name = (row["name"] or "").strip()
                if not name:
                    raise ValueError(f"{csv_path}: row {i}, column name: missing value")
                if name in seen:
                    raise ValueError(f"{csv_path}: row {i}: duplicate material name {name} (first on row {seen[name]})")
                seen[name] = i
                cost = _num(row["cost"], csv_path, i, "cost")
                if cost < 0:
                    raise ValueError(f"{csv_path}: row {i}, column cost: negative cost {cost}")
                pct = {}
                for el in elements:
                    v = _num(row[el], csv_path, i, el)
                    if not 0 <= v <= 100:
                        raise ValueError(f"{csv_path}: row {i}, column {el}: percent {v} outside 0..100")
                    pct[el] = v
                ms = row.get("max_share")
                ms = None if ms is None or ms.strip() == "" else _num(ms, csv_path, i, "max_share")
                if ms is not None and not 0 <= ms <= 1:
                    raise ValueError(f"{csv_path}: row {i}, column max_share: {ms} outside 0..1")
                out.append((name, cost, pct, ms))
        except UnicodeDecodeError:
            raise ValueError(f"{csv_path}: not UTF-8 text; save it from Excel as 'CSV UTF-8 (comma delimited)'") from None
    if not out:
        raise ValueError(f"{csv_path}: no material rows")
    return out


def import_materials(db, csv_path):
    """CSV header: name,cost,<element>,...[,max_share]. Returns number of materials imported."""
    rows = read_materials(csv_path)
    for name, cost, pct, ms in rows:
        store.add_material(db, name, cost, pct, ms)
    store.select(db, [])
    return len(rows)


def select(db, names_csv):
    names = list(dict.fromkeys(n.strip() for n in names_csv.split(",") if n.strip()))
    if not names:
        raise ValueError("select needs at least one material name")
    known = {r[0] for r in db.execute("SELECT name FROM material")}
    missing = [n for n in names if n not in known]
    if missing:
        raise ValueError(f"unknown material(s): {', '.join(missing)}")
    store.select(db, names)
    return names


def parse_ranges(spec, known=None):
    """'C=0.8:1.2,Mn=0.6:1.5' -> {'C': (0.8, 1.2), 'Mn': (0.6, 1.5)}.
    If known element names are given, names match case-insensitively and unknown names are an error."""
    out = {}
    canon = {k.lower(): k for k in known} if known is not None else None
    seen = {}
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            el, rng = part.split("=")
            lo_t, hi_t = rng.split(":")
            lo, hi = float(lo_t), float(hi_t)
        except ValueError:
            raise ValueError(f"bad range {part!r}, expected like C=0.8:1.2") from None
        el = el.strip()
        if not math.isfinite(lo) or not math.isfinite(hi):
            raise ValueError(f"{el}: range {rng.strip()} is not a finite number range; use plain numbers like 0.8:1.2")
        if el.lower() in seen:
            raise ValueError(f"duplicate element {el} in composition (already given as {seen[el.lower()]})")
        seen[el.lower()] = el
        if canon is not None:
            if el.lower() not in canon:
                raise ValueError(f"unknown element {el} (known: {', '.join(known) or 'none, import materials first'})")
            el = canon[el.lower()]
        if lo > hi:
            raise ValueError(f"{el}: min {lo} > max {hi}")
        if lo < 0 or hi > 100:
            raise ValueError(f"{el}: range must lie within 0..100 %")
        out[el] = (lo, hi)
    if not out:
        raise ValueError("composition needs at least one element range")
    return out


def composition(db, name, spec):
    name = name.strip()
    if not name:
        raise ValueError("composition name must not be empty")
    ranges = parse_ranges(spec, store.elements(db))
    store.save_composition(db, name, ranges)
    return ranges


def _fmt_kg(kg):
    return f"{kg:.3f}" if kg >= 1 else f"{kg:.4g}"


def format_result(r):
    lines = []
    for w in r.warnings:
        lines.append(f"WARNING: {w}")
    if not r.ok:
        lines.append(f"No feasible blend: {r.message}")
        if r.unconstrained:
            lines.append(f"note: not constrained by this composition: {', '.join(r.unconstrained)}")
        return "\n".join(lines)
    lines.append("kg per material:")
    for n, kg in r.kg.items():
        lines.append(f"  {n}: {_fmt_kg(kg)}")
    lines.append(f"total cost: {r.cost:.2f}")
    lines.append("achieved composition (%):")
    for el, v in r.composition.items():
        lines.append(f"  {el}: {v:.4f}")
    if r.unconstrained:
        lines.append(f"note: not constrained by this composition (0..100 %): {', '.join(r.unconstrained)}")
    return "\n".join(lines)


def run(db, name, batch_kg):
    msg = f"batch size must be a number of kg from {BATCH_MIN} to {BATCH_MAX:.0e}, got {batch_kg!r}"
    try:
        b = float(batch_kg)
    except (TypeError, ValueError):
        raise ValueError(msg) from None
    if not math.isfinite(b) or not BATCH_MIN <= b <= BATCH_MAX:
        raise ValueError(msg)
    return store.run(db, name, b)


def _db_error(path, e):
    text = str(e)
    low = text.lower()
    if "locked" in low or "busy" in low:
        hint = "another program has the database open; close it and try again"
    elif "readonly" in low or "read-only" in low:
        hint = "the database file or its folder is read-only; make it writable or use another file"
        text = "database is read-only"
    elif "not a database" in low or "malformed" in low or "encrypted" in low:
        hint = "this file is not a database made by this tool; give a new file name"
        text = "file is not a database"
    elif "unable to open" in low:
        hint = "check that the folder exists and you may write there"
    else:
        hint = "check the database file path"
    return f"database {path}: {text} (hint: {hint})"


def _safe_streams():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv=None):
    _safe_streams()
    a = sys.argv[1:] if argv is None else argv
    if len(a) < 2:
        print(__doc__); return 2
    cmd, rest = a[1], a[2:]
    if cmd not in NARGS:
        print(f"error: unknown command {cmd}"); print(__doc__); return 2
    if len(rest) < NARGS[cmd]:
        print(f"error: missing argument for {cmd}"); print(__doc__); return 2
    if len(rest) > NARGS[cmd]:
        print(f"error: too many arguments for {cmd} (extra: {' '.join(rest[NARGS[cmd]:])}); "
              "put values with spaces or commas in quotes"); return 2
    try:
        db = store.connect(a[0])
        if cmd == "import-materials":
            n = import_materials(db, rest[0])
            print(f"imported {n} material{'' if n == 1 else 's'}")
            print("note: material selection reset; run select again before run")
        elif cmd == "select":
            print("selected: " + ", ".join(select(db, rest[0])))
        elif cmd == "composition":
            composition(db, rest[0], rest[1]); print(f"saved composition {rest[0].strip()}")
        elif cmd == "run":
            r = run(db, rest[0], rest[1]); print(format_result(r))
            return 0 if r.ok else 1
    except sqlite3.Error as e:
        print(f"error: {_db_error(a[0], e)}"); return 2
    except (ValueError, OSError) as e:
        print(f"error: {e}"); return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
