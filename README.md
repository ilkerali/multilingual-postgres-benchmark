# multilingual-postgres-benchmark
Exploring Multilingual Data Modeling in PostgreSQL through Normalization, Denormalization and JSONB

This repository contains the complete benchmarking suite for the paper:  
**"Benchmarking Multilingual Data Models in PostgreSQL: A Comparative Analysis of Normalization, Denormalization, and JSONB"**

## Models Evaluated
- **Model 1:** Row-based translation table (normalized)
- **Model 2:** Table-per-language
- **Model 3:** Column-per-language (wide table)
- **Model 4:** JSONB column

## Requirements
- Python 3.14+
- PostgreSQL 16 (Docker recommended)
- See `requirements.txt` for Python dependencies.

## Setup
1. Clone this repository.
2. Create a virtual environment: `python3 -m venv .venv`
3. Activate it: `source .venv/bin/activate`
4. Install dependencies: `pip install -r requirements.txt`
5. Copy `config.example.py` to `config.py` and update database credentials.
6. Run data generation: `python3 generate_data.py`
7. Run benchmarks: `python3 benchmark_runner_3.py --models 1 2 3 4 --sizes 10000 100000 1000000 --iterations 30`
8. Visualize results: `python3 visualize_results2.py`

## License
MIT
