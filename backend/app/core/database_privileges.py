"""运行账号权限边界，供就绪检查和恢复/授权工具共同使用。"""

UNSAFE_RUNTIME_ROLE = (
    "NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=:role) OR EXISTS("
    "SELECT 1 FROM pg_roles r WHERE (r.rolsuper OR r.rolcreatedb OR r.rolcreaterole) "
    "AND pg_has_role(:role,r.oid,'MEMBER')) OR EXISTS("
    "SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
    "WHERE n.nspname='public' AND c.relkind IN ('r','p') "
    "AND pg_has_role(:role,c.relowner,'MEMBER')) OR EXISTS("
    "SELECT 1 FROM pg_database WHERE datname=current_database() "
    "AND pg_has_role(:role,datdba,'MEMBER'))"
)
