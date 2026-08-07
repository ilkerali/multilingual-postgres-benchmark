# multilingual-postgres-benchmark
Exploring Multilingual Data Modeling in PostgreSQL through Normalization, Denormalization and JSONB
This repository contains the complete benchmarking suite for the paper: "Benchmarking Multilingual Data Models in PostgreSQL: A Comparative Analysis of Normalization, Denormalization, and JSONB"

Models Evaluated
| Model | Design | Relations |
| --- | --- | --- |
| **Model 1** | Row-based translation table (normalized) | `products` + `product_translations` |
| **Model 2** | Table-per-language | `products` + `products_tr` … `products_mk` |
| **Model 3** | Column-per-language (wide table) | `products` |
| **Model 4** | JSONB column | `products_json` |

Eight operations are measured across three dataset sizes (10K, 100K, 1M products) and five languages (Turkish, English, German, French, Macedonian): four reads, three writes, and the on-disk storage footprint. The primary metric is client-side median latency over 30 iterations after 3 discarded warm-up runs.

Requirements
Python 3.10 or later
PostgreSQL 16 (Docker recommended; measurements were taken on 16.14)
Roughly 30 GB of free disk space for the 1M datasets across all four models
See requirements.txt for Python dependencies
Setup
1. Clone and install

git clone https://github.com/ilkerali/multilingual-postgres-benchmark.git
cd multilingual-postgres-benchmark
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

2. Configure the database connection

Connection settings are read from the standard PostgreSQL environment variables, so no credential is stored in this repository and no file needs to be copied:


export PGHOST=localhost
export PGPORT=5432
export PGDATABASE=multilingual_db
export PGUSER=benchmark
export PGPASSWORD=...

On Windows PowerShell use $env:PGHOST = "localhost" and so on.

Create the database before continuing:

CREATE DATABASE multilingual_db OWNER benchmark;

3. Generate the data

python generate_data2.py

This creates twelve isolated schemas (m1_10k … m4_1m) and loads each with content that is a deterministic function of product_id, so all four models hold identical data. Add --dry-run to exercise the generator without touching the database.

4. Verify equivalence — do not skip this

python verify_data2.py

This compares product counts, price sums, per-language translation counts and total text lengths across all four models. It must report that all checks passed before you proceed; otherwise the benchmark would be comparing datasets that are not equivalent.

5. Run the benchmark

python benchmark_runner_5.py

Defaults are all four models, all three dataset sizes, 30 iterations and 3 warm-up runs. The runner performs its own run-time consistency check and exits with status 1 if the four models disagree. Results are written to results2/.

6. Generate the figures

python visualize_results5.py

The most recent CSV in results2/ is used automatically. Figures are written to figures/.

Quick trial

To exercise the whole pipeline cheaply before committing to the 1M datasets, restrict every step to the smallest size:

python generate_data2.py --sizes 10000
python verify_data2.py  --sizes 10000
python benchmark_runner_5.py --sizes 10000
Repository layout

.
├── models/                       Schema definitions (DDL), one file per model
│   ├── model1_schema.sql
│   ├── model2_schema.sql
│   ├── model3_schema.sql
│   └── model4_schema.sql
├── config2.py                    Connection settings, schema naming, experiment parameters
├── generate_data2.py             Deterministic data generator
├── verify_data2.py               Pre-benchmark equivalence checks
├── benchmark_runner_5.py         Benchmark driver
├── visualize_results5.py         Figure generation
├── results2/
│   ├── benchmark_<timestamp>.csv     Results reported in the paper
│   ├── benchmark_<timestamp>.json    Same data plus environment metadata
│   ├── plans/                        96 EXPLAIN (ANALYZE, BUFFERS) plans
│   └── control_no_composite_index/   Control run — see "Index experiment" below
├── figures/                      Figures 5–11 as published
├── requirements.txt
└── README.md

Design decisions that affect reproducibility

Twelve isolated schemas. Each (model, dataset size) pair lives in its own schema, created with DROP SCHEMA … CASCADE. This is not cosmetic: Models 1, 2 and 3 all name their base table products, so a shared schema cannot hold more than one of them at a time.

Content is a pure function of product_id. Each product's price and translations are generated from a per-product RNG seeded as SEED * PID_STRIDE + product_id. Whichever model generates it, in whatever order and batch size, the content is identical. Faker is used only once at start-up to build a word pool per language, so its global state cannot influence the generated rows.

Equivalence is verified, not assumed. verify_data2.py compares content across all four models before measurement. benchmark_runner_5.py additionally records the values returned by the count, price-filter and substring-count queries and asserts that they agree across models — they must, if and only if the four models hold the same data.

Measurement starts from a clean physical state. Each schema is vacuumed and reindexed before its queries run, and the storage footprint is captured at that point, before the write workload.

Writes are non-destructive. Every write iteration runs inside BEGIN … ROLLBACK, so all 30 repetitions start from the same logical state. Note the limitation this leaves: rolled-back tuple versions remain in the heap as dead rows, which affects the dispersion of the translation-update measurement at 1M. This is discussed in the paper and visible in the drift column of the results CSV.

Index parity. Every model carries a B-tree index on the column its substring search targets, so no design is disadvantaged by index configuration alone.

Index experiment

results2/control_no_composite_index/ holds an earlier run that is identical in every respect except one: Model 1 carried a single-column index on product_translations(lang_code) instead of the composite (lang_code, name) index used in the published run.

Comparing the two isolates the effect of that single change. Model 1's full substring scan at 1M drops from 1.128 s to 0.158 s, its other seven measurements move by at most 8%, and Models 2, 3 and 4 are unchanged within an average of 5%. The comparison also establishes the run-to-run noise floor quoted in the paper.

Data and results

results2/benchmark_<timestamp>.csv holds one row per (model, dataset size) with, for each query, the client-side mean, median, standard deviation, IQR, p95 and drift, plus the server-side time from a single EXPLAIN ANALYZE execution, plus storage figures and per-relation detail.

results2/plans/ holds the full EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) plan for each of the 96 (model, size, query) combinations. These are the evidence behind the plan-level claims in the paper — for instance that Models 1 and 2 satisfy the substring search with an index-only scan and zero heap fetches, while Model 4 falls back to a sequential scan.

Citation

If you use this code or data, please cite the paper. A CITATION.cff file will be added on publication.

License

MIT for the code. The generated datasets and result files are released under CC BY 4.0.
