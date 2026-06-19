# First, ensure indexes exist (run once during setup)
create_indexes = """
    CREATE CONSTRAINT van_ban_id IF NOT EXISTS 
    FOR (v:VAN_BAN) REQUIRE v.ID IS UNIQUE;
    
    CREATE CONSTRAINT dieu_khoan_id IF NOT EXISTS 
    FOR (d:DIEU_KHOAN) REQUIRE d.ID IS UNIQUE;
"""

# Creates the node if it does not exist, replaces all properties with new data form props 
# Removes old properties that are not in props
bulk_upsert_for_node_docs = """
    UNWIND $props_list AS props
    MERGE (q:VAN_BAN {ID: props.ID})
    SET q = props
"""

# Conditionally updates properties only if they differ from existing values
# Preserves properties that are not in props
bulk_update_for_node_docs = """
    UNWIND $props_list AS props
    MERGE (q:VAN_BAN {ID: props.ID})
    SET q.tinh_trang_hieu_luc = CASE WHEN q.tinh_trang_hieu_luc <> props.tinh_trang_hieu_luc 
                            THEN props.tinh_trang_hieu_luc 
                            ELSE q.tinh_trang_hieu_luc END,
        q.thoi_gian_cap_nhat = CASE WHEN q.thoi_gian_cap_nhat <> props.thoi_gian_cap_nhat 
                         THEN props.thoi_gian_cap_nhat 
                         ELSE q.thoi_gian_cap_nhat END
    // ... repeat for each property
"""

bulk_upsert_for_node_terms = """
    UNWIND $props_list AS props
    MERGE (q:DIEU_KHOAN {ID: props.ID})
    SET q = props
"""

bulk_update_for_node_terms = """
    UNWIND $props_list AS props
    MERGE (q:DIEU_KHOAN {ID: props.ID})
    SET q.tinh_trang_hieu_luc = CASE WHEN q.tinh_trang_hieu_luc <> props.tinh_trang_hieu_luc 
                            THEN props.tinh_trang_hieu_luc 
                            ELSE q.tinh_trang_hieu_luc END,
        q.thoi_gian_cap_nhat = CASE WHEN q.thoi_gian_cap_nhat <> props.thoi_gian_cap_nhat 
                         THEN props.thoi_gian_cap_nhat 
                         ELSE q.thoi_gian_cap_nhat END
    // ... repeat for each property
"""