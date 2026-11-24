"""SQLite masters for the blend optimiser: raw master (materials x elements) and composition master (targets)."""
import sqlite3, json
from blend_optimizer import optimise

SCHEMA = """
CREATE TABLE IF NOT EXISTS element(name TEXT PRIMARY KEY, pos INTEGER);
CREATE TABLE IF NOT EXISTS material(name TEXT PRIMARY KEY, cost REAL NOT NULL, selected INTEGER DEFAULT 0, max_share REAL);
CREATE TABLE IF NOT EXISTS pct(material TEXT, element TEXT, value REAL, PRIMARY KEY(material, element));
CREATE TABLE IF NOT EXISTS composition(name TEXT, element TEXT, lo REAL, hi REAL, PRIMARY KEY(name, element));
"""


def connect(path=":memory:"):
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    return db


def add_material(db, name, cost, pct_by_element, max_share=None):
    for el in pct_by_element:
        db.execute("INSERT OR IGNORE INTO element(name,pos) VALUES(?,(SELECT COUNT(*) FROM element))", (el,))
    db.execute("INSERT OR REPLACE INTO material(name,cost,selected,max_share) VALUES(?,?,0,?)", (name, cost, max_share))
    for el, v in pct_by_element.items():
        db.execute("INSERT OR REPLACE INTO pct VALUES(?,?,?)", (name, el, v))
    db.commit()


def select(db, names):
    """Second master: only the materials chosen for this batch."""
    db.execute("UPDATE material SET selected=0")
    db.executemany("UPDATE material SET selected=1 WHERE name=?", [(n,) for n in names])
    db.commit()


def save_composition(db, name, ranges):
    db.execute("DELETE FROM composition WHERE name=?", (name,))
    db.executemany("INSERT INTO composition VALUES(?,?,?,?)", [(name, e, lo, hi) for e, (lo, hi) in ranges.items()])
    db.commit()


def composition_names(db):
    return [r[0] for r in db.execute("SELECT DISTINCT name FROM composition ORDER BY name")]


def elements(db):
    return [r[0] for r in db.execute("SELECT name FROM element ORDER BY pos")]


def run(db, comp_name, batch_kg):
    if comp_name not in composition_names(db):
        saved = ", ".join(composition_names(db)) or "none"
        raise ValueError(f"unknown composition {comp_name} (saved: {saved})")
    els = [r[0] for r in db.execute("SELECT name FROM element ORDER BY pos")]
    mats = {}
    shares = {}
    for n, c, ms in db.execute("SELECT name,cost,max_share FROM material WHERE selected=1"):
        vals = dict(db.execute("SELECT element,value FROM pct WHERE material=?", (n,)).fetchall())
        mats[n] = {"cost": c, "pct": [vals.get(e, 0.0) for e in els]}
        if ms is not None:
            shares[n] = ms
    target = {e: (lo, hi) for e, lo, hi in db.execute("SELECT element,lo,hi FROM composition WHERE name=?", (comp_name,))}
    if not mats:
        raise ValueError("no materials selected; use the select command first")
    free = [e for e in els if e not in target]
    for e in free:
        target[e] = (0.0, 100.0)
    r = optimise(mats, els, target, batch_kg, shares)
    r.unconstrained = free
    return r
