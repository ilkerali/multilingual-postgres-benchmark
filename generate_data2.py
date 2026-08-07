#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_data2.py
=================
Generates IDENTICAL content for the four multilingual storage models.

Two fundamental differences from the previous version
-----------------------------------------------------
1.  Each (model, size) resides in its own schema: m1_10k, m2_1m, ...
    In the previous version, all four models shared the same schema, and the base
    tables of Models 1, 2, and 3 also had the same name (products). Consequently,
    the last generated model overwrote the tables of the previous ones, causing all
    measurements to be performed on the same physical table.

2.  Content is a PURE FUNCTION of product_id.
    A separate RNG is seeded per product (SEED * PID_STRIDE + product_id),
    ensuring that regardless of which model or generation order is used, the same
    price and text are produced. In the previous version, Model 2 consumed random
    numbers in a different order (all prices first, then language by language), so
    even with the same seed it generated different data.

Faker is used only once at the beginning to create a word pool per language.
Product texts are deterministically selected from this pool; Faker's global state
does not affect the generation order.

Usage
-----
    python generate_data2.py                      # 4 models x 3 sizes
    python generate_data2.py --models 1 2         # only Models 1 and 2
    python generate_data2.py --sizes 10000        # only 10k (pilot)
    python generate_data2.py --dry-run            # does not touch the database
"""

import argparse
import json
import random
import sys
import time
from pathlib import Path

from config2 import (
    DATABASE_CONFIG, LANGUAGES, PRODUCT_COUNTS, TRANSLATION_COVERAGE,
    SEED, PID_STRIDE, POOL_SIZE, NAME_WORDS, DESC_WORDS_MIN, DESC_WORDS_MAX,
    SCHEMA_DIR, schema_name,
)

CHUNK = 5_000          # How many products can be inserted together?
FAKER_LOCALES = {"tr": "tr_TR", "en": "en_US", "de": "de_DE",
                 "fr": "fr_FR", "mk": "mk_MK"}


# ---------------------------------------------------------------------------
# 1. Word pools
# ---------------------------------------------------------------------------

def build_word_pools(verbose=True):
    """Deterministic word pool per language.

The pool is generated once and shared by all models. .
    """
    from faker import Faker

    pools = {}
    for lang in LANGUAGES:
        locale = FAKER_LOCALES.get(lang, "en_US")
        try:
            fake = Faker(locale)
        except Exception:
            if verbose:
                print(f"  ! '{locale}' No locale setting available, en_US is being used. ({lang})")
            fake = Faker("en_US")
            locale = "en_US (fallback)"

        Faker.seed(SEED)
        fake.seed_instance(SEED)

        words = set()
        guard = 0
        while len(words) < POOL_SIZE and guard < POOL_SIZE * 60:
            guard += 1
            try:
                token = fake.word()
            except Exception:
                token = fake.sentence(nb_words=1).strip(" .")
            token = token.strip()
            if token:
                words.add(token)
            if guard % (POOL_SIZE * 6) == 0 and len(words) < 50:
                break   

        pool = sorted(words)          
        if len(pool) < 50:           
            filler = set()
            while len(filler) < POOL_SIZE and len(filler) < 20_000:
                for t in fake.sentence(nb_words=20).replace(".", "").split():
                    filler.add(t)
                if len(filler) > POOL_SIZE:
                    break
            pool = sorted(filler)

        pools[lang] = pool
        if verbose:
            print(f"  {lang}: {len(pool):,} kelime  ({locale})")
    return pools

# 2. Pure function of product_id

def slugify(name):
    s = "".join(c if c.isalnum() else "-" for c in name.lower())
    return "-".join(p for p in s.split("-") if p)[:100]


def product_record(pid, pools):
    """Price plus translations for pid. Independent of model and call sequence.."""
    rng = random.Random(SEED * PID_STRIDE + pid)

    rec = {
        "product_id": pid,
        "sku": f"SKU-{pid:08d}",
        "price": round(rng.uniform(10, 5000), 2),
        "translations": {},
    }

    for lang in LANGUAGES:                      
        if rng.random() >= TRANSLATION_COVERAGE:
            continue                           
        pool = pools[lang]
        name = " ".join(rng.choice(pool) for _ in range(NAME_WORDS))
        n_words = rng.randint(DESC_WORDS_MIN, DESC_WORDS_MAX)
        description = " ".join(rng.choice(pool) for _ in range(n_words))
        description = description[:1].upper() + description[1:] + "."
        rec["translations"][lang] = {
            "name": name[:200],
            "description": description,
            "slug": slugify(name),
            "meta_title": name[:60],
            "meta_description": description[:160],
        }
    return rec


# ---------------------------------------------------------------------------
# 3. Model-based row transformations
# ---------------------------------------------------------------------------

TRANS_COLS = ("name", "description", "slug", "meta_title", "meta_description")


def rows_model1(batch):
    base = [(r["product_id"], r["price"], r["sku"]) for r in batch]
    trans = [
        (r["product_id"], lang, *(t[c] for c in TRANS_COLS))
        for r in batch for lang, t in r["translations"].items()
    ]
    return base, trans


def rows_model2(batch):
    base = [(r["product_id"], r["price"], r["sku"]) for r in batch]
    per_lang = {lang: [] for lang in LANGUAGES}
    for r in batch:
        for lang, t in r["translations"].items():
            per_lang[lang].append((r["product_id"], *(t[c] for c in TRANS_COLS)))
    return base, per_lang


def rows_model3(batch):
    out = []
    for r in batch:
        row = [r["product_id"], r["price"], r["sku"]]
        for lang in LANGUAGES:
            t = r["translations"].get(lang)
            row.extend([t[c] for c in TRANS_COLS] if t else [None] * len(TRANS_COLS))
        out.append(tuple(row))
    return out


def rows_model4(batch):
    return [
        (r["product_id"], r["price"], r["sku"],
         json.dumps(r["translations"], ensure_ascii=False, sort_keys=True))
        for r in batch
    ]


def model3_columns():
    cols = ["product_id", "price", "sku"]
    for lang in LANGUAGES:
        cols.extend(f"{c}_{lang}" for c in TRANS_COLS)
    return cols


# ---------------------------------------------------------------------------
# 4. Database operations
# ---------------------------------------------------------------------------

def rebuild_schema(conn, schema, model):
    """It completely erases and rebuilds the schema, then runs the model DDL.

    DROP SCHEMA ... CASCADE is used; thus, it is physically impossible to find a table left over from another model..
    """
    path = Path(SCHEMA_DIR) / f"model{model}_schema.sql"
    if not path.exists():
        path = Path(f"model{model}_schema.sql")
    ddl = path.read_text(encoding="utf-8")

    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE;")
        cur.execute(f"CREATE SCHEMA {schema};")
        cur.execute(f"SET search_path TO {schema};")
        try:
            cur.execute(ddl)
        except Exception as exc:
            raise RuntimeError(f"{path.name} could not be started:\n  {exc}")
    conn.autocommit = False


def fix_sequence(cur, table):
    cur.execute(
        f"SELECT setval(pg_get_serial_sequence('{table}', 'product_id'), "
        f"COALESCE((SELECT MAX(product_id) FROM {table}), 1));"
    )


def load_model(conn, schema, model, num_products, pools, progress):
    from psycopg2.extras import execute_values

    cur = conn.cursor()
    cur.execute(f"SET search_path TO {schema};")

    m3cols = ", ".join(model3_columns())
    done = 0
    for start in range(1, num_products + 1, CHUNK):
        stop = min(start + CHUNK - 1, num_products)
        batch = [product_record(pid, pools) for pid in range(start, stop + 1)]

        if model == 1:
            base, trans = rows_model1(batch)
            execute_values(cur, "INSERT INTO products (product_id, price, sku) VALUES %s",
                           base, page_size=CHUNK)
            if trans:
                execute_values(cur,
                               "INSERT INTO product_translations "
                               "(product_id, lang_code, name, description, slug, "
                               "meta_title, meta_description) VALUES %s",
                               trans, page_size=CHUNK)
        elif model == 2:
            base, per_lang = rows_model2(batch)
            execute_values(cur, "INSERT INTO products (product_id, price, sku) VALUES %s",
                           base, page_size=CHUNK)
            for lang, rows in per_lang.items():
                if rows:
                    execute_values(cur,
                                   f"INSERT INTO products_{lang} "
                                   "(product_id, name, description, slug, "
                                   "meta_title, meta_description) VALUES %s",
                                   rows, page_size=CHUNK)
        elif model == 3:
            execute_values(cur, f"INSERT INTO products ({m3cols}) VALUES %s",
                           rows_model3(batch), page_size=CHUNK)
        elif model == 4:
            execute_values(cur,
                           "INSERT INTO products_json "
                           "(product_id, price, sku, translations) VALUES %s",
                           rows_model4(batch), page_size=CHUNK)

        conn.commit()
        done = stop
        progress(done, num_products)

    fix_sequence(cur, "products_json" if model == 4 else "products")
    conn.commit()
    cur.close()
    return done


def vacuum_analyze(conn, schema):
    """VACUUM ANALYZE: The statistics are up-to-date; measurements begin when the inflation level is at zero."""
    conn.commit()
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f"SET search_path TO {schema};")
        cur.execute("VACUUM (ANALYZE);")
    conn.autocommit = False


# ---------------------------------------------------------------------------
# 5. Validation criteria (for comparison with verify_data2.py)
# ---------------------------------------------------------------------------

def expected_fingerprint(num_products, pools):
    """Expected values independent of the database.

    verify_data2.py compares these values against queries for each model.
    """
    fp = {
        "num_products": num_products,
        "price_sum": 0.0,
        "price_100_500": 0,
        "per_lang": {l: {"count": 0, "name_len": 0, "desc_len": 0} for l in LANGUAGES},
    }
    for pid in range(1, num_products + 1):
        r = product_record(pid, pools)
        fp["price_sum"] += r["price"]
        if 100 <= r["price"] <= 500:
            fp["price_100_500"] += 1
        for lang, t in r["translations"].items():
            d = fp["per_lang"][lang]
            d["count"] += 1
            d["name_len"] += len(t["name"])
            d["desc_len"] += len(t["description"])
    fp["price_sum"] = round(fp["price_sum"], 2)
    return fp


# ---------------------------------------------------------------------------
# 6. Main
# ---------------------------------------------------------------------------

def make_progress(label):
    last = [-1]

    def report(done, total):
        pct = int(done * 100 / total)
        if pct != last[0] and pct % 10 == 0:
            last[0] = pct
            print(f"    {label}: {pct:3d}%  ({done:,}/{total:,})", flush=True)
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", type=int, nargs="+", default=[1, 2, 3, 4])
    ap.add_argument("--sizes", type=int, nargs="+", default=PRODUCT_COUNTS)
    ap.add_argument("--dry-run", action="store_true",
                    help="Does not connect to the database; shows determinism and sample content.")
    args = ap.parse_args()

    print("Building word pools...")
    pools = build_word_pools()

    if args.dry_run:
        print("\n--- DRY RUN: determinism check ---")
        a = product_record(1, pools)
        b = product_record(1, pools)
        c = product_record(2, pools)
        print(f"  product_record(1) Are the two calls the same? : {a == b}")
        print(f"  product_record(1) != product_record(2): {a != c}")
        print(f"\n  Example record (pid=1): price={a['price']}, sku={a['sku']}")
        for lang, t in a["translations"].items():
            print(f"    {lang}: {t['name'][:44]!r}  desc={len(t['description'])} char")
        eksik = [l for l in LANGUAGES if l not in a["translations"]]
        print(f"    eksik diller: {eksik or '(yok)'}")

        n = min(args.sizes)
        print(f"\n  {n:,} products for expected fingerprint calculation...")
        fp = expected_fingerprint(min(n, 10_000), pools)
        print(f"    product count        : {fp['num_products']:,}")
        print(f"    total price      : {fp['price_sum']:,.2f}")
        print(f"    100-500 range products : {fp['price_100_500']:,}")
        for lang, d in fp["per_lang"].items():
            print(f"    {lang}: {d['count']:,} translation, "
                  f"ad {d['name_len']:,} char, explanation {d['desc_len']:,} char")
        print("\nDry run ok. Nothing was written to the database..")
        return

    import psycopg2
    t0 = time.time()
    conn = psycopg2.connect(**DATABASE_CONFIG)
    try:
        for num_products in args.sizes:
            for model in args.models:
                schema = schema_name(model, num_products)
                print(f"\n=== Model {model} | {num_products:,} products | schema {schema} ===")
                rebuild_schema(conn, schema, model)
                print("  schema built")
                t = time.time()
                n = load_model(conn, schema, model, num_products, pools,
                               make_progress(f"M{model}"))
                print(f"  {n:,} products loaded ({time.time()-t:.1f} s)")
                vacuum_analyze(conn, schema)
                print("  VACUUM ANALYZE completed")
    finally:
        conn.close()

    print(f"\nAll data generated: {time.time()-t0:.1f} s")
    print("Now run: python verify_data2.py")


if __name__ == "__main__":
    sys.exit(main())
