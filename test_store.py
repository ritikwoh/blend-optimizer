import store


def test_masters_round_trip_and_unselected_material_is_ignored():
    db = store.connect()
    store.add_material(db, "A", 10, {"C": 2.0, "Mn": 0.0})
    store.add_material(db, "B", 4, {"C": 0.0, "Mn": 0.0})
    store.add_material(db, "Cheap_but_not_selected", 1, {"C": 2.0, "Mn": 0.0})
    store.select(db, ["A", "B"])
    store.save_composition(db, "steel1", {"C": (1.0, 1.0), "Mn": (0.0, 5.0)})
    r = store.run(db, "steel1", 100)
    assert r.ok and r.kg == {"A": 50.0, "B": 50.0} and r.cost == 700.0
    assert "Cheap_but_not_selected" not in r.kg
