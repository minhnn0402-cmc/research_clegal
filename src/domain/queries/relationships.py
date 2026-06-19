
bulk_upsert_relation_bao_gom = """
    UNWIND $rel_list AS rel
    MATCH (a {ID: rel.head_ID})
    WHERE a:VAN_BAN OR a:DIEU_KHOAN
    MATCH (b:DIEU_KHOAN {ID: rel.tail_ID})
    MERGE (a)-[r:bao_gom]->(b)
    SET r.thoi_gian_cap_nhat = rel.thoi_gian_cap_nhat,
        r.nguon_cap_nhat = rel.nguon_cap_nhat
"""

bulk_upsert_for_status_relations = """
    UNWIND $rel_list AS rel
    // Ensure source node exists
    CALL apoc.merge.node([rel.head_class], {ID: rel.head_ID}) YIELD node as a
    
    // Enrich skeleton source node if necessary
    WITH rel, a, size(keys(a)) AS k_a, split(toString(rel.head_ID), '#') AS parts_head
    OPTIONAL MATCH (a_var:DIEU_KHOAN)
    WHERE k_a <= 1 AND size(parts_head) > 1 
      AND (a_var.ID STARTS WITH (parts_head[0] + '_dk_') OR a_var.ID STARTS WITH (parts_head[0] + '_bosung_'))
      AND a_var.ID ENDS WITH ('#' + parts_head[1])
    WITH rel, a, collect(a_var) AS a_vars
    CALL apoc.do.when(
        size(a_vars) > 0,
        'SET a += apoc.map.clean(properties(a_vars[0]), ["ID"], []) RETURN a',
        'RETURN a',
        {a: a, a_vars: a_vars}
    ) YIELD value AS a_val
    WITH rel, a_val.a AS a
    
    // Ensure target node exists
    CALL apoc.merge.node([rel.tail_class], {ID: rel.tail_ID}) YIELD node as b
    
    // Enrich skeleton target node if necessary
    WITH rel, a, b, size(keys(b)) AS k_b, split(toString(rel.tail_ID), '#') AS parts_tail
    OPTIONAL MATCH (b_var:DIEU_KHOAN)
    WHERE k_b <= 1 AND size(parts_tail) > 1 
      AND (b_var.ID STARTS WITH (parts_tail[0] + '_dk_') OR b_var.ID STARTS WITH (parts_tail[0] + '_bosung_'))
      AND b_var.ID ENDS WITH ('#' + parts_tail[1])
    WITH rel, a, b, collect(b_var) AS b_vars
    CALL apoc.do.when(
        size(b_vars) > 0,
        'SET b += apoc.map.clean(properties(b_vars[0]), ["ID"], []) RETURN b',
        'RETURN b',
        {b: b, b_vars: b_vars}
    ) YIELD value AS b_val
    WITH rel, a, b_val.b AS b
    SET b += apoc.map.clean(coalesce(rel.target_node_props, {}), ["ID"], [])
    WITH rel, a, b
    // Create relationship
    CALL apoc.merge.relationship(
        a,
        rel.rel_type,
        {},
        coalesce(rel.rel_props, {}),
        b,
        coalesce(rel.rel_props, {})
    ) YIELD rel as r
    WITH rel, r
    // Update properties
    SET r += coalesce(rel.rel_props, {})
"""

bulk_upsert_for_status_relations_strict = """
    UNWIND $rel_list AS rel
    MATCH (a {ID: rel.head_ID})
    WHERE (rel.head_class = 'VAN_BAN' AND a:VAN_BAN)
       OR (rel.head_class = 'DIEU_KHOAN' AND a:DIEU_KHOAN)
    MATCH (b {ID: rel.tail_ID})
    WHERE (rel.tail_class = 'VAN_BAN' AND b:VAN_BAN)
       OR (rel.tail_class = 'DIEU_KHOAN' AND b:DIEU_KHOAN)
    SET b += apoc.map.clean(coalesce(rel.target_node_props, {}), ["ID"], [])
    WITH rel, a, b
    CALL apoc.merge.relationship(
        a,
        rel.rel_type,
        {},
        coalesce(rel.rel_props, {}),
        b,
        coalesce(rel.rel_props, {})
    ) YIELD rel as r
    WITH rel, r
    SET r += coalesce(rel.rel_props, {})
"""

