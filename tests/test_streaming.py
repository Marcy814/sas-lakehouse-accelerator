import json
from datetime import datetime, timedelta

import duckdb

from accelerator import streaming


def _ecrire(dossier, numero, evenements):
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = dossier / f"evenements_{numero:03d}.jsonl"
    chemin.write_text("\n".join(json.dumps(e) for e in evenements) + "\n", encoding="utf-8")


def _evt(event_id, minutes, province="QC", type_evenement="SINISTRE_DECLARE"):
    return {"event_id": event_id, "type_evenement": type_evenement, "sinistre_id": f"S-{event_id}",
            "police_id": "PO-1", "province": province, "type_sinistre": "VOL", "montant": 100.0,
            "event_time": (datetime(2026, 7, 1, 8, 0) + timedelta(minutes=minutes)).isoformat()}


def test_doublons_retards_et_exactly_once(tmp_path):
    base, flux = tmp_path / "lake.duckdb", tmp_path / "flux"
    processeur = streaming.StreamProcessor(db_path=base, stream_dir=flux, delai_filigrane=timedelta(minutes=30),
                                           seuil_alerte=3)
    _ecrire(flux, 1, [_evt("a", 60), _evt("b", 61), _evt("b", 61)])
    (lot1,) = processeur.process_available()
    assert (lot1.lus, lot1.doublons, lot1.retenus) == (3, 1, 2)
    assert lot1.filigrane == datetime(2026, 7, 1, 8, 31)

    _ecrire(flux, 2, [_evt("a", 60), _evt("c", 10), _evt("d", 62), _evt("e", 63)])
    (lot2,) = processeur.process_available()
    assert (lot2.doublons, lot2.en_retard, lot2.retenus, lot2.alertes) == (1, 1, 2, 1)

    assert processeur.process_available() == []
    with duckdb.connect(str(base), read_only=True) as con:
        assert con.execute("select count(*) from bronze.evenements_sinistres").fetchone()[0] == 4
        assert con.execute("select sum(nb_declarations) from gold.sinistres_par_fenetre").fetchone()[0] == 4
        assert con.execute("select count(*) from gold.alertes_temps_reel").fetchone()[0] == 1


def test_lot_en_echec_ne_laisse_aucune_trace(tmp_path):
    base, flux = tmp_path / "lake.duckdb", tmp_path / "flux"
    flux.mkdir()
    (flux / "evenements_001.jsonl").write_text("{pas du json}\n", encoding="utf-8")
    processeur = streaming.StreamProcessor(db_path=base, stream_dir=flux)
    try:
        processeur.process_available()
    except duckdb.Error:
        pass
    with duckdb.connect(str(base), read_only=True) as con:
        assert con.execute("select count(*) from stream.checkpoint").fetchone()[0] == 0


def test_generateur_deterministe(tmp_path):
    premier = streaming.generate_batch(4, stream_dir=tmp_path / "x").read_text(encoding="utf-8")
    second = streaming.generate_batch(4, stream_dir=tmp_path / "y").read_text(encoding="utf-8")
    assert premier == second and premier.count('"QC"') > 40
