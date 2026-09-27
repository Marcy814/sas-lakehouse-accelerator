import pytest

from accelerator.agents.guardrails import GuardrailViolation, validate_sql

GOLD = {"gold"}


@pytest.mark.parametrize(
    "sql",
    [
        "select produit, sum(total_paye) from gold.mart_ratio_sinistralite group by produit",
        "with t as (select * from gold.fct_sinistre) select count(*) from t",
        "select * from gold.dim_client union all select * from gold.dim_client",
    ],
)
def test_requetes_autorisees(sql):
    requete = validate_sql(sql, GOLD)
    assert "LIMIT" in requete.sql.upper()


@pytest.mark.parametrize(
    "sql",
    [
        "drop table gold.fct_sinistre",
        "delete from gold.fct_sinistre",
        "update gold.dim_client set province = 'QC'",
        "select 1; drop table gold.fct_sinistre",
        "select * from silver.silver_clients",
        "select * from bronze.clients",
        "select * from dim_client",
        "select * from read_csv('/etc/passwd')",
        "select getenv('HOME')",
        "attach 'autre.duckdb'",
        "copy gold.fct_sinistre to 'fuite.csv'",
        "pragma database_list",
        "select * from autre_catalogue.gold.fct_sinistre",
    ],
)
def test_requetes_refusees(sql):
    with pytest.raises(GuardrailViolation):
        validate_sql(sql, GOLD)


def test_limite_plafonnee():
    assert validate_sql("select * from gold.dim_client limit 5", GOLD, max_rows=200).limit_applied is False
    requete = validate_sql("select * from gold.dim_client limit 100000", GOLD, max_rows=200)
    assert requete.limit_applied and "LIMIT 200" in requete.sql


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT produit, mart_ratio_sinistralite AS ratio FROM gold.mart_ratio_sinistralite "
        "WHERE annee = 2025 ORDER BY mart_ratio_sinistralite DESC",
        "select r from gold.mart_ratio_sinistralite as r",
        "with t as (select * from gold.fct_sinistre) select t from t",
        "select s from (select * from gold.fct_sinistre) as s",
    ],
)
def test_table_utilisee_comme_colonne_refusee(sql):
    with pytest.raises(GuardrailViolation, match="describe_table"):
        validate_sql(sql, GOLD)


@pytest.mark.parametrize(
    "sql",
    [
        "select produit, ratio_sinistralite from gold.mart_ratio_sinistralite order by ratio_sinistralite desc",
        "select r.produit, r.* from gold.mart_ratio_sinistralite as r",
        "select produit, sum(total_paye) as total from gold.mart_ratio_sinistralite group by produit order by total",
    ],
)
def test_colonnes_normales_acceptees(sql):
    validate_sql(sql, GOLD)
