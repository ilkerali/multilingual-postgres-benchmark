#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_data2.py
===============
Before starting the measurement, it proves that the four models share the same logical content.

Why it's necessary
-------------
The previous run had two silent errors:
* The four models shared the same schema, and the base table of Models 1/2/3 had the same name; measurements were unknowingly made to a single physical table.
* Model 2 consumed random numbers in a different order than the others; it produced different data even with the same seed.
Neither was visible in the measurement output. This script catches both.

Checks
----------
1. Schema content: Does each schema contain ONLY tables belonging to that model?
2. Is the number of products equal in all four models?
3. Are the total price and the number of products in the 100-500 range equal?
4. Is the number of translations per language equal? ​​(detects empty language tables)
5. Is the total number of name and description characters per language equal?
6. Do all of these match the values ​​that generate_data2.py expects from the database independently?

If the exit code is 0, the measurement can proceed. Otherwise, 1.

Usage
--------
    python verify_data2.py
    python verify_data2.py --sizes 10000
    python verify_data2.py --skip-expected      
"""

import argparse
import sys

import psycopg2

from config2 import DATABASE_CONFIG, LANGUAGES, PRODUCT_COUNTS, schema_name
from generate_data2 import build_word_pools, expected_fingerprint

BASE = {1: "products", 2: "products", 3: "products", 4: "products_json"}

EXPECTED_TABLES = {
    1: {"products", "product_translations"},
    2: {"products"} | {f"products_{l}" for l in LANGUAGES},
    3: {"products"},
    4: {"products_json"},
}

PRICE_LO, PRICE_HI = 100, 500
TOL = 0.01          # acceptable rounding difference in total price


# ---------------------------------------------------------------------------

def tables_in(cur, schema):
    cur.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = %s AND table_type = 'BASE TABLE';", (schema,))
    return {r[0] for r in cur.fetchall()}


def base_stats(cur, schema, model):
    tbl = BASE[model]
    cur.execute(
        f"SELECT COUNT(*), COALESCE(SUM(price), 0), "
        f"COUNT(*) FILTER (WHERE price BETWEEN {PRICE_LO} AND {PRICE_HI}) "
        f"FROM {schema}.{tbl};")
    n, psum, pband = cur.fetchone()
    return {"num_products": n, "price_sum": round(float(psum), 2),
            "price_100_500": pband}


def lang_stats(cur, schema, model):
    out = {}
    if model == 1:
        cur.execute(
            f"SELECT lang_code, COUNT(*), "
            f"COALESCE(SUM(length(name)), 0), "
            f"COALESCE(SUM(length(description)), 0) "
            f"FROM {schema}.product_translations GROUP BY lang_code;")
        rows = {r[0]: (r[1], r[2], r[3]) for r in cur.fetchall()}
        for lang in LANGUAGES:
            c, nl, dl = rows.get(lang, (0, 0, 0))
            out[lang] = {"count": c, "name_len": int(nl), "desc_len": int(dl)}

    elif model == 2:
        for lang in LANGUAGES:
            cur.execute(
                f"SELECT COUNT(*), COALESCE(SUM(length(name)), 0), "
                f"COALESCE(SUM(length(description)), 0) "
                f"FROM {schema}.products_{lang};")
            c, nl, dl = cur.fetchone()
            out[lang] = {"count": c, "name_len": int(nl), "desc_len": int(dl)}

    elif model == 3:
        for lang in LANGUAGES:
            cur.execute(
                f"SELECT COUNT(name_{lang}), "
                f"COALESCE(SUM(length(name_{lang})), 0), "
                f"COALESCE(SUM(length(description_{lang})), 0) "
                f"FROM {schema}.products;")
            c, nl, dl = cur.fetchone()
            out[lang] = {"count": c, "name_len": int(nl), "desc_len": int(dl)}

    elif model == 4:
        for lang in LANGUAGES:
            #  We are using jsonb_exists: the '?' operator is confused with the psycopg2 parameter.
            cur.execute(
                f"SELECT COUNT(*) FILTER (WHERE jsonb_exists(translations, %s)), "
                f"COALESCE(SUM(length(translations->%s->>'name')), 0), "
                f"COALESCE(SUM(length(translations->%s->>'description')), 0) "
                f"FROM {schema}.products_json;", (lang, lang, lang))
            c, nl, dl = cur.fetchone()
            out[lang] = {"count": c, "name_len": int(nl), "desc_len": int(dl)}
    return out


# ---------------------------------------------------------------------------

class Report:
    def __init__(self):
        self.fail = 0

    def check(self, ok, label, detail=""):
        mark = "  OK  " if ok else " FAIL "
        print(f"[{mark}] {label}" + (f"   {detail}" if detail else ""))
        if not ok:
            self.fail += 1
        return ok


def compare_across_models(rep, size, stats, langs):
    models = sorted(stats)

    for field in ("num_products", "price_sum", "price_100_500"):
        vals = {m: stats[m][field] for m in models}
        uniq = set(round(v, 2) if isinstance(v, float) else v for v in vals.values())
        if field == "price_sum":
            ok = max(vals.values()) - min(vals.values()) <= TOL
        else:
            ok = len(uniq) == 1
        rep.check(ok, f"{size:>9,} | {field} four models are equal",
                  "" if ok else " ".join(f"M{m}={vals[m]}" for m in models))

    for lang in LANGUAGES:
        for field in ("count", "name_len", "desc_len"):
            vals = {m: langs[m][lang][field] for m in models}
            ok = len(set(vals.values())) == 1
            rep.check(ok, f"{size:>9,} | {lang}.{field} four models are equal",
                      "" if ok else " ".join(f"M{m}={vals[m]:,}" for m in models))


def compare_with_expected(rep, size, stats, langs, fp):
    for m in sorted(stats):
        ok = stats[m]["num_products"] == fp["num_products"]
        rep.check(ok, f"{size:>9,} | M{m} product count matches expected",
                  "" if ok else f"{stats[m]['num_products']} != {fp['num_products']}")
        ok = abs(stats[m]["price_sum"] - fp["price_sum"]) <= max(TOL, size * 0.005)
        rep.check(ok, f"{size:>9,} | M{m} total price matches expected",
                  "" if ok else f"{stats[m]['price_sum']} != {fp['price_sum']}")
        for lang in LANGUAGES:
            ok = langs[m][lang]["count"] == fp["per_lang"][lang]["count"]
            rep.check(ok, f"{size:>9,} | M{m}.{lang} translation count matches expected",
                      "" if ok else
                      f"{langs[m][lang]['count']:,} != {fp['per_lang'][lang]['count']:,}")


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", type=int, nargs="+", default=PRODUCT_COUNTS)
    ap.add_argument("--skip-expected", action="store_true",
                    help="Do not recalculate expected values (slow for 1M).")
    args = ap.parse_args()

    rep = Report()
    pools = None
    if not args.skip_expected:
        print("Building word pools (for expected values)...")
        pools = build_word_pools(verbose=False)

    conn = psycopg2.connect(**DATABASE_CONFIG)
    cur = conn.cursor()

    for size in args.sizes:
        print(f"\n{'='*70}\n{size:,} urun\n{'='*70}")
        stats, langs = {}, {}

        for model in (1, 2, 3, 4):
            schema = schema_name(model, size)
            found = tables_in(cur, schema)
            if not found:
                rep.check(False, f"{size:>9,} | schema {schema} mevcut", "schema is empty or does not exist")
                continue

            extra = found - EXPECTED_TABLES[model]
            missing = EXPECTED_TABLES[model] - found
            rep.check(not extra and not missing,
                      f"{size:>9,} | {schema} only contains its own tables",
                      "" if not (extra or missing) else
                      f"extra={sorted(extra)} missing={sorted(missing)}")

            stats[model] = base_stats(cur, schema, model)
            langs[model] = lang_stats(cur, schema, model)

        if len(stats) == 4:
            compare_across_models(rep, size, stats, langs)
            if pools is not None:
                compare_with_expected(rep, size, stats, langs,
                                      expected_fingerprint(size, pools))
        else:
            rep.check(False, f"{size:>9,} | four models' data is not available",
                      f"available models: {sorted(stats)}")

    cur.close()
    conn.close()

    print(f"\n{'='*70}")
    if rep.fail == 0:
        print(" ALL CHECKS PASSED — you can proceed with the measurement:")
        print("  python benchmark_runner_5.py")
        return 0
    print(f"{rep.fail} CHECKS FAILED — do not proceed with the measurement.")
    print("Once generated_data2.py is ready, run it again for the relevant model/size.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
