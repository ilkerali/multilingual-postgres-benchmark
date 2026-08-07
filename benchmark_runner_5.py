#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Multilingual Database Benchmark Runner v5
=========================================
Compares four storage models for multilingual product catalogues:

  1. Row-based translation table (normalized)
  2. Table per language
  3. Column per language (wide table)
  4. JSONB column

Carried over unchanged from v3
------------------------------
Query definitions (Q1-Q7), BEGIN/ROLLBACK wrapping of writes, NULL-safe Q6,
Q7 without ON CONFLICT, jit = off, max_parallel_workers_per_gather = 0, the
statistical summary (mean / median / stdev / IQR / p95 / drift) and plan
capture. These were validated and are preserved verbatim.

Changed relative to v3
----------------------
1. EACH (model, size) PAIR LIVES IN ITS OWN SCHEMA: m1_10k ... m4_1m, twelve
   in total. In v3 the four models shared three schemas, and Models 1, 2 and 3
   all named their base table 'products'. Each model's DDL dropped the previous
   model's table during generation, so three models ended up measuring a single
   physical table.

2. MAINTENANCE BEFORE MEASUREMENT. Every schema is reindexed and vacuumed
   before its queries run. v3 had no such step, and at one million rows the
   indexes of Models 2 and 3 were 37 times larger than Model 1's (858 MB
   against 23 MB) through accumulated bloat, which directly corrupted the Q1
   and Q2 results.

3. RUN-TIME CONSISTENCY CHECK. The VALUE RETURNED by Q1, Q2 and Q3a is recorded
   and compared across the four models at each dataset size. If the models hold
   the same data these values must be equal. In v3 the substring count returned
   four different values at 1M (586,956 / 585,933 / 586,705 / 586,756) and
   nothing in the output revealed it.

4. Q4 RETURNS THE SAME PAYLOAD IN ALL FOUR MODELS: product_id plus the name in
   five languages. In v3 Model 3 also returned price and Model 4 returned the
   entire JSONB document, so different amounts of data were moved under a
   single query name.

5. PER-RELATION STORAGE DETAIL is recorded, including dead-tuple counts, so
   that any future bloat appears in the output instead of passing silently.

6. THE SUMMARY TABLE PRINTS CLIENT-SIDE MEDIANS, the primary metric of the
   study. v3 printed server-side medians, which is how the published figures
   came to be generated from server-side data by mistake.

7. ENVIRONMENT METADATA is recorded: PostgreSQL version, shared_buffers,
   work_mem and related settings.

Usage
-----
    python benchmark_runner_5.py
    python benchmark_runner_5.py --models 1 2 --sizes 10000
    python benchmark_runner_5.py --no-maintenance     # skip REINDEX / VACUUM
    python benchmark_runner_5.py --explain-every
"""

import argparse
import csv
import json
import os
import statistics
import sys
import time
from datetime import datetime

import psycopg2
import psycopg2.extras

try:
    from config2 import (DATABASE_CONFIG, PRODUCT_COUNTS, BENCHMARK_ITERATIONS,
                         BENCHMARK_WARMUP, LIKE_PATTERN, LANGUAGES,
                         RESULTS_DIR, PLANS_DIR, schema_name)
except ImportError:
    print("ERROR: config2.py not found.")
    sys.exit(1)

OUTPUT_DIR = RESULTS_DIR
PLAN_DIR = PLANS_DIR


# =============================================================================
# QUERY DEFINITIONS
# =============================================================================
# Queries that do the SAME WORK in every model. The 'kind' field controls
# transaction behaviour: read -> commit, write -> BEGIN/ROLLBACK.
# Queries flagged with 'capture' also have their RETURNED VALUE recorded; the
# cross-model consistency check is built on those values.

def build_queries(model, pattern):
    """Build the query set for a given model."""
    base = "products_json" if model == 4 else "products"

    if model == 1:
        q3_from, q3_where_lang = "product_translations", "lang_code = 'tr' AND "
        q3_name, q3_cols = "name", "product_id, name"
    elif model == 2:
        q3_from, q3_where_lang = "products_tr", ""
        q3_name, q3_cols = "name", "product_id, name"
    elif model == 3:
        q3_from, q3_where_lang = "products", ""
        q3_name, q3_cols = "name_tr", "product_id, name_tr"
    else:
        q3_from, q3_where_lang = "products_json", ""
        q3_name = "translations->'tr'->>'name'"
        q3_cols = "product_id, translations->'tr'->>'name'"

    queries = []

    # ---------------- READ ----------------
    queries.append({
        "id": "q1_count_all", "kind": "read", "capture": True,
        "sql": f"SELECT COUNT(*) FROM {base};",
    })
    queries.append({
        "id": "q2_price_filter", "kind": "read", "capture": True,
        "sql": f"SELECT COUNT(*) FROM {base} WHERE price BETWEEN 100 AND 500;",
    })
    # Q3a: cost of a full scan - IDENTICAL SEMANTICS IN ALL MODELS
    queries.append({
        "id": "q3_count_lang_filter", "kind": "read", "capture": True,
        "sql": (f"SELECT COUNT(*) FROM {q3_from} "
                f"WHERE {q3_where_lang}{q3_name} LIKE %(pat)s;"),
        "params": {"pat": pattern},
    })
    # Q3b: early stop / first-page latency - IDENTICAL SEMANTICS IN ALL MODELS
    queries.append({
        "id": "q3_limit_lang_filter", "kind": "read",
        "sql": (f"SELECT {q3_cols} FROM {q3_from} "
                f"WHERE {q3_where_lang}{q3_name} LIKE %(pat)s LIMIT 100;"),
        "params": {"pat": pattern},
    })

    # Q4: fetch all languages for 100 products.
    # v5: THE SAME PAYLOAD in every model -> product_id plus five names.
    if model == 1:
        q4 = """
            SELECT p.product_id,
                   t_tr.name AS name_tr, t_en.name AS name_en,
                   t_de.name AS name_de, t_fr.name AS name_fr,
                   t_mk.name AS name_mk
            FROM products p
            LEFT JOIN product_translations t_tr
                   ON p.product_id = t_tr.product_id AND t_tr.lang_code = 'tr'
            LEFT JOIN product_translations t_en
                   ON p.product_id = t_en.product_id AND t_en.lang_code = 'en'
            LEFT JOIN product_translations t_de
                   ON p.product_id = t_de.product_id AND t_de.lang_code = 'de'
            LEFT JOIN product_translations t_fr
                   ON p.product_id = t_fr.product_id AND t_fr.lang_code = 'fr'
            LEFT JOIN product_translations t_mk
                   ON p.product_id = t_mk.product_id AND t_mk.lang_code = 'mk'
            LIMIT 100;"""
    elif model == 2:
        q4 = """
            SELECT p.product_id,
                   tr.name AS name_tr, en.name AS name_en,
                   de.name AS name_de, fr.name AS name_fr,
                   mk.name AS name_mk
            FROM products p
            LEFT JOIN products_tr tr ON p.product_id = tr.product_id
            LEFT JOIN products_en en ON p.product_id = en.product_id
            LEFT JOIN products_de de ON p.product_id = de.product_id
            LEFT JOIN products_fr fr ON p.product_id = fr.product_id
            LEFT JOIN products_mk mk ON p.product_id = mk.product_id
            LIMIT 100;"""
    elif model == 3:
        q4 = ("SELECT product_id, name_tr, name_en, name_de, name_fr, name_mk "
              "FROM products LIMIT 100;")
    else:
        q4 = ("SELECT product_id, "
              "translations->'tr'->>'name', translations->'en'->>'name', "
              "translations->'de'->>'name', translations->'fr'->>'name', "
              "translations->'mk'->>'name' "
              "FROM products_json LIMIT 100;")
    queries.append({"id": "q4_all_languages", "kind": "read", "sql": q4})

    # ---------------- WRITE ----------------
    # All write queries run inside BEGIN/ROLLBACK and leave no permanent change.
    queries.append({
        "id": "q5_update_price", "kind": "write",
        "sql": f"UPDATE {base} SET price = price * 1.05 "
               f"WHERE product_id % 10 = 0;",
    })

    if model == 1:
        q6 = ("UPDATE product_translations "
              "SET description = COALESCE(description, '') || ' UPDATED' "
              "WHERE lang_code = 'tr' AND product_id <= 10000;")
    elif model == 2:
        q6 = ("UPDATE products_tr "
              "SET description = COALESCE(description, '') || ' UPDATED' "
              "WHERE product_id <= 10000;")
    elif model == 3:
        q6 = ("UPDATE products "
              "SET description_tr = COALESCE(description_tr, '') || ' UPDATED' "
              "WHERE product_id <= 10000;")
    else:
        # jsonb_set: create_missing = true creates the path when 'tr' is absent.
        # Without COALESCE a NULL argument nullifies the whole document rather
        # than one field, which would silently destroy data.
        q6 = ("UPDATE products_json SET translations = jsonb_set("
              "    COALESCE(translations, '{}'::jsonb),"
              "    '{tr,description}',"
              "    to_jsonb(COALESCE(translations->'tr'->>'description', '')"
              "             || ' UPDATED'),"
              "    true) "
              "WHERE product_id <= 10000;")
    queries.append({"id": "q6_update_translation", "kind": "write", "sql": q6})

    # Q7: a genuine bulk insert. No ON CONFLICT clause is needed because the
    # rollback prevents inserted SKUs from colliding with the next iteration.
    if model == 4:
        q7 = ("INSERT INTO products_json (price, sku, translations) "
              "SELECT RANDOM() * 5000, "
              "       'SKU-BENCH-' || g, "
              "       '{\"tr\":{\"name\":\"Urun\"},"
              "         \"en\":{\"name\":\"Product\"}}'::jsonb "
              "FROM generate_series(1, 10000) AS g;")
    else:
        q7 = ("INSERT INTO products (price, sku) "
              "SELECT RANDOM() * 5000, 'SKU-BENCH-' || g "
              "FROM generate_series(1, 10000) AS g;")
    queries.append({"id": "q7_insert_products", "kind": "write", "sql": q7})

    return queries


CAPTURED = ("q1_count_all", "q2_price_filter", "q3_count_lang_filter")

MODEL_TABLES = {
    1: ["products", "product_translations"],
    2: ["products"] + [f"products_{l}" for l in LANGUAGES],
    3: ["products"],
    4: ["products_json"],
}


# =============================================================================
# STATISTICS HELPERS  (unchanged from v3)
# =============================================================================

def summarize(times):
    """Produce a robust statistical summary from a list of timings."""
    if not times:
        return {}
    s = sorted(times)
    n = len(s)

    def pct(p):
        if n == 1:
            return s[0]
        k = (n - 1) * p
        lo, hi = int(k), min(int(k) + 1, n - 1)
        return s[lo] + (s[hi] - s[lo]) * (k - lo)

    head = times[:5] if n >= 10 else times[:1]
    tail = times[-5:] if n >= 10 else times[-1:]
    drift = statistics.mean(tail) - statistics.mean(head)
    return {
        "n": n,
        "mean": statistics.mean(times),
        "median": statistics.median(times),
        "stdev": statistics.stdev(times) if n > 1 else 0.0,
        "min": s[0], "max": s[-1],
        "p25": pct(0.25), "p75": pct(0.75),
        "iqr": pct(0.75) - pct(0.25),
        "p95": pct(0.95),
        "drift_abs": drift,
        "drift_pct": (drift / statistics.mean(head) * 100.0)
                     if statistics.mean(head) > 0 else 0.0,
    }


# =============================================================================
# RUNNER
# =============================================================================

class BenchmarkRunner:
    def __init__(self, iterations, warmup, pattern, explain_every_iteration,
                 maintenance=True):
        self.iterations = iterations
        self.warmup = warmup
        self.pattern = pattern
        self.explain_every_iteration = explain_every_iteration
        self.maintenance = maintenance
        self.conn = None
        self.cur = None
        self.rows = []
        self.plans = []
        self.env = {}

    # ---------- connection ----------
    def connect(self):
        self.conn = psycopg2.connect(**DATABASE_CONFIG)
        self.conn.autocommit = False        # we control transactions explicitly
        self.cur = self.conn.cursor()
        self.cur.execute("SET jit = off;")               # remove JIT noise
        self.cur.execute("SET max_parallel_workers_per_gather = 0;")
        self.conn.commit()
        self._read_environment()

    def _read_environment(self):
        """Record the server environment for reproducibility."""
        self.cur.execute("SELECT version();")
        version = self.cur.fetchone()[0]
        settings = {}
        for name in ("shared_buffers", "work_mem", "maintenance_work_mem",
                     "effective_cache_size", "random_page_cost",
                     "max_parallel_workers_per_gather", "jit"):
            try:
                self.cur.execute("SELECT current_setting(%s);", (name,))
                settings[name] = self.cur.fetchone()[0]
            except Exception:
                self.conn.rollback()
                settings[name] = None
        self.conn.commit()
        self.env = {"pg_version": version.split(" on ")[0], "settings": settings}
        print(f"  {self.env['pg_version']}")
        print("  " + "  ".join(f"{k}={v}" for k, v in settings.items() if v))

    def close(self):
        if self.cur:
            self.cur.close()
        if self.conn:
            self.conn.close()

    def set_schema(self, schema):
        self.cur.execute(f"SET search_path TO {schema};")
        self.conn.commit()

    # ---------- pre-measurement maintenance ----------
    def maintain(self, schema):
        """REINDEX and VACUUM (ANALYZE) so every model starts from an
        equivalent physical state.

        v3 had no such step, and at 1M rows Models 2 and 3 were measured with
        bloated indexes.
        """
        if not self.maintenance:
            print("  maintenance skipped (--no-maintenance)")
            return
        self.conn.commit()
        self.conn.autocommit = True
        t = time.time()
        try:
            self.cur.execute(f"SET search_path TO {schema};")
            self.cur.execute(f"REINDEX SCHEMA {schema};")
            self.cur.execute("VACUUM (ANALYZE);")
            print(f"  REINDEX + VACUUM ANALYZE done ({time.time()-t:.1f} s)")
        except Exception as exc:
            print(f"  ! maintenance failed: {str(exc)[:120]}")
        finally:
            self.conn.autocommit = False
            self.conn.commit()

    # ---------- measurement core ----------
    def _client_timed_run(self, q):
        """Execute once; return (elapsed, captured value)."""
        sql, params = q["sql"], q.get("params")
        start = time.perf_counter()
        self.cur.execute(sql, params)
        value = None
        if q["kind"] == "read":
            rows = self.cur.fetchall()
            if q.get("capture") and rows:
                value = rows[0][0]
        elapsed = time.perf_counter() - start
        return elapsed, value

    def _server_timed_run(self, q):
        """Server-side timing and plan via EXPLAIN (ANALYZE, BUFFERS)."""
        sql, params = q["sql"], q.get("params")
        explain_sql = "EXPLAIN (ANALYZE, BUFFERS, TIMING, FORMAT JSON) " + sql
        self.cur.execute(explain_sql, params)
        plan = self.cur.fetchone()[0][0]
        return plan["Execution Time"] / 1000.0, plan["Planning Time"] / 1000.0, plan

    def measure(self, q):
        """Run warmup + iterations repetitions of one query.

        Write queries execute inside BEGIN/ROLLBACK on every iteration, so all
        repetitions are measured from the SAME starting state.
        """
        is_write = q["kind"] == "write"
        client_times, server_times, planning_times = [], [], []
        last_plan, captured = None, None
        total = self.warmup + self.iterations

        for i in range(total):
            try:
                if is_write:
                    self.cur.execute("BEGIN;")
                if self.explain_every_iteration or i == self.warmup:
                    st, pt, plan = self._server_timed_run(q)
                    if i >= self.warmup:
                        server_times.append(st)
                        planning_times.append(pt)
                    last_plan = plan
                    if is_write:
                        # EXPLAIN ANALYZE really executed the write -> undo it
                        self.cur.execute("ROLLBACK;")
                        self.cur.execute("BEGIN;")

                ct, val = self._client_timed_run(q)
                if i >= self.warmup:
                    client_times.append(ct)
                    if val is not None:
                        captured = val

                if is_write:
                    self.cur.execute("ROLLBACK;")
                else:
                    self.conn.commit()
            except Exception as e:
                try:
                    self.conn.rollback()
                except Exception:
                    pass
                return {"error": f"{type(e).__name__}: {str(e)[:200]}"}

        return {
            "client": summarize(client_times),
            "server": summarize(server_times) if server_times else {},
            "planning_mean": statistics.mean(planning_times) if planning_times else None,
            "plan": last_plan,
            "value": captured,
        }

    # ---------- storage ----------
    def measure_storage(self, model, schema):
        """Per-relation size and dead-tuple count.

        v3 recorded only the totals, which left bloat invisible.
        """
        out = {"table_bytes": 0, "index_bytes": 0, "total_bytes": 0,
               "dead_tuples": 0, "live_tuples": 0, "detail": {}}
        for t in MODEL_TABLES[model]:
            try:
                self.cur.execute(
                    "SELECT pg_table_size(%s), pg_indexes_size(%s), "
                    "       pg_total_relation_size(%s);",
                    (f"{schema}.{t}",) * 3)
                tb, ib, tot = self.cur.fetchone()
                self.cur.execute(
                    "SELECT COALESCE(n_live_tup, 0), COALESCE(n_dead_tup, 0) "
                    "FROM pg_stat_user_tables "
                    "WHERE schemaname = %s AND relname = %s;", (schema, t))
                row = self.cur.fetchone()
                live, dead = row if row else (0, 0)

                out["table_bytes"] += tb
                out["index_bytes"] += ib
                out["total_bytes"] += tot
                out["live_tuples"] += live
                out["dead_tuples"] += dead
                out["detail"][t] = {"table_mb": round(tb / 1e6, 2),
                                    "index_mb": round(ib / 1e6, 2),
                                    "live_tup": live, "dead_tup": dead}
            except Exception as e:
                self.conn.rollback()
                out["detail"][t] = {"error": str(e)[:100]}
        self.conn.commit()
        return out

    # ---------- per-model execution ----------
    def run_model(self, model, schema, num_products):
        print(f"\n{'='*72}")
        print(f"  MODEL {model}  |  {schema}  |  {num_products:,} products")
        print(f"{'='*72}")
        self.set_schema(schema)
        self.maintain(schema)

        storage = self.measure_storage(model, schema)
        print(f"  Storage: table={storage['table_bytes']/1e6:.1f} MB  "
              f"index={storage['index_bytes']/1e6:.1f} MB  "
              f"total={storage['total_bytes']/1e6:.1f} MB  "
              f"dead_tup={storage['dead_tuples']:,}")
        for t, d in storage["detail"].items():
            if "error" not in d:
                print(f"    {t:<22} {d['table_mb']:>9,.1f} MB heap  "
                      f"{d['index_mb']:>8,.1f} MB idx  "
                      f"{d['dead_tup']:>8,} dead")

        row = {
            "model": model,
            "schema": schema,
            "num_products": num_products,
            "pattern": self.pattern,
            "iterations": self.iterations,
            "warmup": self.warmup,
            "explain_every": self.explain_every_iteration,
            "pg_version": self.env.get("pg_version"),
            "storage_table_mb": storage["table_bytes"] / 1e6,
            "storage_index_mb": storage["index_bytes"] / 1e6,
            "storage_total_mb": storage["total_bytes"] / 1e6,
            "storage_dead_tuples": storage["dead_tuples"],
            "storage_detail_json": json.dumps(storage["detail"], sort_keys=True),
        }

        for q in build_queries(model, self.pattern):
            res = self.measure(q)
            if "error" in res:
                print(f"  [X] {q['id']:<24} {res['error']}")
                for suf in ("mean", "median", "stdev", "iqr", "p95",
                            "drift_pct", "srv_mean", "srv_median", "planning"):
                    row[f"{q['id']}_{suf}"] = None
                continue

            c, s = res["client"], res["server"]
            row[f"{q['id']}_mean"] = c["mean"]
            row[f"{q['id']}_median"] = c["median"]
            row[f"{q['id']}_stdev"] = c["stdev"]
            row[f"{q['id']}_iqr"] = c["iqr"]
            row[f"{q['id']}_p95"] = c["p95"]
            row[f"{q['id']}_drift_pct"] = c["drift_pct"]
            row[f"{q['id']}_srv_mean"] = s.get("mean")
            row[f"{q['id']}_srv_median"] = s.get("median")
            row[f"{q['id']}_planning"] = res["planning_mean"]
            if q["id"] in CAPTURED:
                row[f"{q['id']}_value"] = res["value"]

            overhead = (c["mean"] - s["mean"]) if s else None
            extra = f"  -> {res['value']:,}" if q["id"] in CAPTURED and res["value"] is not None else ""
            print(f"  [ok] {q['id']:<24} "
                  f"cli={c['median']:.4f}s  "
                  f"srv={s.get('median', 0):.4f}s  "
                  f"IQR={c['iqr']:.4f}  "
                  f"drift={c['drift_pct']:+.1f}%"
                  + (f"  ovh={overhead:.4f}s" if overhead is not None else "")
                  + extra)

            if res["plan"] is not None:
                self.plans.append({
                    "model": model, "schema": schema,
                    "query": q["id"], "sql": q["sql"], "plan": res["plan"],
                })

        self.rows.append(row)

    # ---------- top level ----------
    def run_all(self, models, sizes):
        self.connect()
        try:
            for model in models:
                for n in sizes:
                    schema = schema_name(model, n)
                    try:
                        self.run_model(model, schema, n)
                    except Exception as e:
                        print(f"  !! Model {model}/{schema} skipped: {e}")
                        self.conn.rollback()
        finally:
            self.close()

    # ---------- consistency check ----------
    def consistency_report(self):
        """The four models at a given size must return the same values.

        If they do not, either the datasets differ or the models are reading
        the same physical table. Both happened in v3 and neither was visible
        in the output.
        """
        print("\n" + "=" * 72)
        print("CONSISTENCY CHECK - all four models must return the same values")
        print("=" * 72)
        by_size = {}
        for r in self.rows:
            by_size.setdefault(r["num_products"], {})[r["model"]] = r

        failures = 0
        for size in sorted(by_size):
            group = by_size[size]
            if len(group) < 2:
                continue
            for qid, label in (("q1_count_all", "COUNT(*)"),
                               ("q2_price_filter", "price 100-500"),
                               ("q3_count_lang_filter", "tr LIKE pattern")):
                vals = {m: group[m].get(f"{qid}_value") for m in sorted(group)}
                present = {m: v for m, v in vals.items() if v is not None}
                if not present:
                    continue
                ok = len(set(present.values())) == 1
                mark = " OK " if ok else "FAIL"
                detail = (f"{next(iter(present.values())):,}" if ok else
                          "  ".join(f"M{m}={v:,}" for m, v in present.items()))
                print(f"  [{mark}] {size:>9,}  {label:<18} {detail}")
                if not ok:
                    failures += 1

        if failures:
            print(f"\n  !! {failures} inconsistencies. DO NOT USE these results.")
            print("     Run first: python verify_data2.py")
        else:
            print("\n  All models return identical values.")
        return failures

    # ---------- summary ----------
    def print_summary(self):
        print("\n" + "=" * 132)
        print(f"RESULTS - CLIENT-SIDE MEDIAN latency (s), the primary metric, "
              f"{self.iterations} iterations, pattern={self.pattern}")
        print("=" * 132)
        cols = [
            ("q1_count_all", "COUNT"),
            ("q2_price_filter", "Price"),
            ("q3_count_lang_filter", "Lang(cnt)"),
            ("q3_limit_lang_filter", "Lang(lim)"),
            ("q4_all_languages", "AllLang"),
            ("q5_update_price", "UpdPrice"),
            ("q6_update_translation", "UpdTrans"),
            ("q7_insert_products", "Insert"),
        ]
        hdr = f"{'M':<3}{'Schema':<11}{'Rows':>10}{'MB':>8}"
        for _, label in cols:
            hdr += f"{label:>11}"
        print(hdr)
        print("-" * 132)
        for r in self.rows:
            line = (f"{r['model']:<3}{r['schema']:<11}"
                    f"{r['num_products']:>10,}"
                    f"{r['storage_total_mb']:>8.0f}")
            for key, _ in cols:
                v = r.get(f"{key}_median")
                line += f"{v:>11.4f}" if v is not None else f"{'n/a':>11}"
            print(line)

        print("\nDRIFT WARNINGS (|drift| > 10% -> measurement may be state-dependent):")
        any_warn = False
        for r in self.rows:
            for key, label in cols:
                d = r.get(f"{key}_drift_pct")
                if d is not None and abs(d) > 10:
                    any_warn = True
                    print(f"  Model {r['model']} {r['schema']:<10} "
                          f"{label:<11} drift = {d:+.1f}%")
        if not any_warn:
            print("  None - all measurements stable.")

        print("\nDEAD TUPLE WARNINGS (bloat present before measurement):")
        any_dead = False
        for r in self.rows:
            dead = r.get("storage_dead_tuples") or 0
            if dead > max(1000, r["num_products"] * 0.01):
                any_dead = True
                print(f"  Model {r['model']} {r['schema']:<10} "
                      f"dead_tup = {dead:,}")
        if not any_dead:
            print("  None - all tables measured in a clean state.")

        print("\nNOTE: server-side times (srv_*) are present in the CSV but come "
              "from a SINGLE EXPLAIN ANALYZE execution per configuration.")

    # ---------- export ----------
    def export(self):
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        os.makedirs(PLAN_DIR, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        csv_path = os.path.join(OUTPUT_DIR, f"benchmark_{stamp}.csv")
        if self.rows:
            keys = []
            for r in self.rows:
                for k in r:
                    if k not in keys:
                        keys.append(k)
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=keys)
                w.writeheader()
                w.writerows(self.rows)

        json_path = os.path.join(OUTPUT_DIR, f"benchmark_{stamp}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({"environment": self.env, "results": self.rows},
                      f, indent=2, ensure_ascii=False)

        # The schema name already carries the model prefix (m1_10k), so it is
        # not repeated here.
        for p in self.plans:
            fn = f"{p['schema']}_{p['query']}.json"
            with open(os.path.join(PLAN_DIR, fn), "w", encoding="utf-8") as f:
                json.dump(p, f, indent=2, ensure_ascii=False)

        print(f"\nOutput: {csv_path}")
        print(f"        {json_path}")
        print(f"        {PLAN_DIR}/  ({len(self.plans)} plans)")
        return csv_path


# =============================================================================

def apply_trgm_indexes(models, sizes):
    """Optional: create pg_trgm GIN indexes before measuring.

    Note that a LIKE pattern shorter than three characters yields no trigrams,
    so such an index cannot be used for it regardless of the model.
    """
    conn = psycopg2.connect(**DATABASE_CONFIG)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
    stmts = {
        1: ["CREATE INDEX IF NOT EXISTS idx_trgm_m1 ON product_translations "
            "USING GIN (name gin_trgm_ops);"],
        2: ["CREATE INDEX IF NOT EXISTS idx_trgm_m2 ON products_tr "
            "USING GIN (name gin_trgm_ops);"],
        3: ["CREATE INDEX IF NOT EXISTS idx_trgm_m3 ON products "
            "USING GIN (name_tr gin_trgm_ops);"],
        4: ["CREATE INDEX IF NOT EXISTS idx_trgm_m4 ON products_json "
            "USING GIN ((translations->'tr'->>'name') gin_trgm_ops);"],
    }
    for m in models:
        for n in sizes:
            schema = schema_name(m, n)
            cur.execute(f"SET search_path TO {schema};")
            for s in stmts[m]:
                try:
                    print(f"  {schema}: {s[:60]}...")
                    cur.execute(s)
                except Exception as e:
                    print(f"    skipped: {str(e)[:80]}")
            cur.execute("ANALYZE;")
    cur.close()
    conn.close()
    print("pg_trgm indexes ready.\n")


def main():
    ap = argparse.ArgumentParser(description="Multilingual DB Benchmark v5")
    ap.add_argument("--models", nargs="+", type=int, default=[1, 2, 3, 4])
    ap.add_argument("--sizes", nargs="+", type=int, default=PRODUCT_COUNTS)
    ap.add_argument("--iterations", type=int, default=BENCHMARK_ITERATIONS)
    ap.add_argument("--warmup", type=int, default=BENCHMARK_WARMUP)
    ap.add_argument("--pattern", type=str, default=LIKE_PATTERN,
                    help="LIKE pattern, e.g. '%%a%%' or '%%computer%%'")
    ap.add_argument("--explain-every", action="store_true",
                    help="Run EXPLAIN ANALYZE on every iteration (more accurate "
                         "server-side timing, considerably slower)")
    ap.add_argument("--no-maintenance", action="store_true",
                    help="Skip the REINDEX + VACUUM step before measurement")
    ap.add_argument("--trgm", action="store_true",
                    help="Create pg_trgm GIN indexes first")
    args = ap.parse_args()

    print("=" * 72)
    print("  Multilingual PostgreSQL Benchmark v5")
    print(f"  models={args.models}  sizes={args.sizes}")
    print(f"  iterations={args.iterations}  warmup={args.warmup}")
    print(f"  pattern={args.pattern}  explain_every={args.explain_every}")
    print(f"  maintenance={not args.no_maintenance}")
    print(f"  schemas: "
          f"{', '.join(schema_name(m, n) for m in args.models for n in args.sizes)}")
    print("=" * 72)

    if args.trgm:
        apply_trgm_indexes(args.models, args.sizes)

    runner = BenchmarkRunner(
        iterations=args.iterations,
        warmup=args.warmup,
        pattern=args.pattern,
        explain_every_iteration=args.explain_every,
        maintenance=not args.no_maintenance,
    )
    runner.run_all(args.models, args.sizes)
    failures = runner.consistency_report()
    runner.print_summary()
    csv_path = runner.export()

    if failures:
        print("\nINCONSISTENCIES DETECTED - do not use these results in the paper.")
        return 1
    print(f"\nNext step:  python visualize_results5.py {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
