from accelerator.portability import check_sql


def test_sql_portable_accepte():
    sql = "select cast(date_format(d, 'yyyyMMdd') as int) as id, datediff(fin, debut) as j from t"
    verification = check_sql("m", "databricks", sql)
    assert verification.ok


def test_fonctions_duckdb_residuelles_detectees():
    sql = "select date_part('year', age(a, b)) as x, strftime(d, '%Y%m') as m from t union all by name select 1, 2"
    verification = check_sql("m", "snowflake", sql)
    assert not verification.ok
    assert {"age()", "strftime()", "UNION ALL BY NAME"} <= set(verification.duckdb_functions)


def test_erreur_de_syntaxe_signalee():
    verification = check_sql("m", "snowflake", "select from where")
    assert not verification.parsed
