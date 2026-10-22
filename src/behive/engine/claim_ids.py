"""Resolve claim ID generation without changing installation-owned schema.

Canonical SERIAL, custom defaults and identity columns must keep their own
allocator. Only the known defaultless layout uses the existing shared sequence.
No process-wide cache: connections may have different search_path/schema.
"""


def claim_id_expression(cur) -> str:
    """Return a fixed SQL expression for the current hive_claims.id layout.

    Use the INSERT keyword DEFAULT, rather than copying/evaluating a catalog
    expression: this also supports GENERATED ALWAYS AS IDENTITY correctly.
    The regclass lookup follows the same search_path as the caller's INSERT.
    Missing table/column and sequence errors remain fatal; never invent IDs.
    """
    cur.execute("""
        SELECT atthasdef OR attidentity <> ''
        FROM pg_catalog.pg_attribute
        WHERE attrelid = 'hive_claims'::regclass
          AND attname = 'id' AND NOT attisdropped
    """)
    row = cur.fetchone()
    if row is None:
        raise RuntimeError("hive_claims.id metadata missing")
    return "DEFAULT" if row[0] else "nextval('hive_facts_seq')"
