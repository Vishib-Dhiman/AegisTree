"""Legacy ETL script executing raw SQL on engine."""


def legacy_db_fetch(engine, query_str: str):
    return engine.execute(query_str)
