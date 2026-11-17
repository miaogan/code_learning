"""体检主库的唯一约束是否真的在拦重复（副本重建失败时的第一诊断步骤）。

起因（2026-11-16 生产）：`radar_techs_pkey` 在 `pg_index` 里 `indisvalid = true`，
但索引实际缺少若干条目，`ON CONFLICT(tech_slug)` 判不出冲突，两次采集各插了一份
重复行；SQLite 副本的 UNIQUE 是真的，重建副本时撞 `UNIQUE constraint failed`。

用法（在 backend 容器内跑，读的是 DATABASE_URL 指向的库）：

    docker compose --env-file deploy.env -f docker-compose.yml -f docker-compose.prod.yml \
        exec -T backend python - < scripts/audit_unique.py

只读，不改任何数据。输出里出现 `<== DUP` 的行就是「目录说唯一、数据却重复」。

修复套路（务必先备份）：去重（保留 `last_seen_at` 最新的一行、合并最小 `first_seen_at`）
→ `REINDEX INDEX <约束名>` 让索引重新负载 → 再插一次重复值确认被 UniqueViolation 拒绝。
"""

from app.core.db import _raw_pg

SQL = """
    select t.relname as tbl, c.relname as idx, i.indisvalid,
           pg_get_indexdef(i.indexrelid) as def
    from pg_index i
    join pg_class c on c.oid = i.indexrelid
    join pg_class t on t.oid = i.indrelid
    join pg_namespace n on n.oid = t.relnamespace
    where i.indisunique and n.nspname = 'public' and t.relkind = 'r'
    order by 1
"""

with _raw_pg() as pg:
    rows = pg.execute(SQL).fetchall()
    bad: list[str] = []
    print(f"unique indexes: {len(rows)}")
    for row in rows:
        table = row["tbl"]
        definition = row["def"]
        body = definition.split("(", 1)[1].rsplit(")", 1)[0]
        # 复合唯一索引与部分索引不在本次体检范围内（副本重建失败的都是单列）。
        if "," in body or "WHERE" in definition:
            print(f"{table:<28} {'(composite/partial, skipped)':<40}")
            continue
        column = body.strip().strip('"')
        query = (
            f'select count(*) as c from (select 1 from public."{table}" '
            f'group by "{column}" having count(*) > 1) x'
        )
        try:
            duplicated = pg.execute(query).fetchone()["c"]
        except Exception as exc:  # noqa: BLE001 - 体检脚本，异常只做展示
            print(f"{table:<28} {column:<22} ERR {type(exc).__name__}")
            continue
        flag = "  <== DUP" if duplicated else ""
        if duplicated:
            bad.append(f"{table}.{column}")
        print(f"{table:<28} {column:<22} valid={row['indisvalid']} dups={duplicated}{flag}")

print()
print("RESULT:", "OK 所有唯一约束都在生效" if not bad else f"DUP 需修复: {', '.join(bad)}")
