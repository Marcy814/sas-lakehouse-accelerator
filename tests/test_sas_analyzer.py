from pathlib import Path

from accelerator import config
from accelerator.sas_analyzer import SasAnalyzer

PROGRAMME = """
libname dwh "/data";
/* commentaire ; avec point-virgule */
proc sort data=dwh.ventes out=work.tri nodupkey; by client_id; run;
data dwh.resultat(compress=yes);
  set work.tri(in=a keep=client_id montant);
  by client_id;
  retain total;
  if first.client_id then total = 0;
  total + montant;
  precedent = lag(montant);
  if montant < 100 then categorie = 'PETIT';
run;
proc sql;
  create table work.agg as select a.client_id, max(a.montant, b.plafond) as m
  from dwh.resultat as a left join dwh.plafonds b on a.client_id = b.client_id;
quit;
"""


def _analyser(tmp_path: Path, contenu: str = PROGRAMME):
    fichier = tmp_path / "prog.sas"
    fichier.write_text(contenu, encoding="utf-8")
    return SasAnalyzer().analyze_directory(tmp_path).programs[0]


def test_entrees_sorties_et_lignage(tmp_path):
    programme = _analyser(tmp_path)
    assert programme.inputs == ["dwh.ventes", "dwh.plafonds"]
    assert programme.outputs == ["dwh.resultat"]
    etape_data = programme.steps[1]
    assert etape_data.inputs == ["work.tri"] and etape_data.outputs == ["dwh.resultat"]


def test_detection_des_constructions(tmp_path):
    programme = _analyser(tmp_path)
    for construction in ("RETAIN", "LAG", "BY_FIRST_LAST", "SUM_STATEMENT", "SQL_ROW_MINMAX"):
        assert construction in programme.constructs


def test_pieges_de_migration(tmp_path):
    codes = {p.code for p in _analyser(tmp_path).pitfalls}
    assert {"SAS-MISS-01", "SAS-LAG-01", "SAS-RET-01", "SAS-BY-01", "SAS-SQL-01"} <= codes


def test_ordre_de_migration_du_parc_reel():
    inventaire = SasAnalyzer().analyze_directory(config.SAS_DIR)
    ordre = inventaire.migration_order
    assert ordre.index("01_clients_courants") < ordre.index("02_sinistres_enrichis")
    assert ordre.index("02_sinistres_enrichis") < ordre.index("03_ratio_sinistralite")
    assert ordre.index("02_sinistres_enrichis") < ordre.index("04_indicateurs_fraude")
    assert inventaire.external_sources == ["src.clients", "src.polices", "src.sinistres"]
    programme_03 = next(p for p in inventaire.programs if p.name == "03_ratio_sinistralite")
    assert programme_03.complexity_level == "Élevée"
    assert "MACRO_LOOP" in programme_03.constructs
