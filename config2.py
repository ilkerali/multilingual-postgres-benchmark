
#   export PGPASSWORD=...
import os

DATABASE_CONFIG = {
    "host":     os.environ.get("PGHOST", "localhost"),
    "port":     int(os.environ.get("PGPORT", 3333)),
    "database": os.environ.get("PGDATABASE", "multilingual_db_v4"),
    "user":     os.environ.get("PGUSER", "benchmark"),
    "password": os.environ.get("PGPASSWORD", "********"),
}

# --- Experimental parameters -----------------------------------------------------
PRODUCT_COUNTS = [10_000, 100_000, 1_000_000]
LANGUAGES = ["tr", "en", "de", "fr", "mk"]      # ORDER MATTERS: It determines the order of RNG consumption.
TRANSLATION_COVERAGE = 0.95                    
BENCHMARK_ITERATIONS = 30
BENCHMARK_WARMUP = 3
LIKE_PATTERN = "%a%"

# ---------------------------------------------------------------
# The `content` is a pure function of product_id it is not dependent on the model or the loop order.
SEED = 42
PID_STRIDE = 1_000_003       
POOL_SIZE = 20_000            
NAME_WORDS = 2
DESC_WORDS_MIN, DESC_WORDS_MAX = 20, 80

# ---The name -------------------------------------------------------

SIZE_TAGS = {10_000: "10k", 100_000: "100k", 1_000_000: "1m"}


def schema_name(model: int, num_products: int) -> str:
    """Ornek: schema_name(2, 1_000_000) -> 'm2_1m'"""
    return f"m{model}_{SIZE_TAGS[num_products]}"


def all_schemas():
    return [schema_name(m, n) for m in (1, 2, 3, 4) for n in PRODUCT_COUNTS]


# --------------------------------------------------------------------
SCHEMA_DIR = "models"
RESULTS_DIR = "results2"
PLANS_DIR = "results2/plans"
