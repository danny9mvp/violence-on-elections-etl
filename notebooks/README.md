# Notebooks

Exploratory and validation notebooks for the Violence on Elections ETL.

## How to run them

The intended way to run these notebooks is the PyCharm IDE Managed Jupyter
server:

1. Open the project in PyCharm and go to `Settings > Project > Python Interpreter`.
2. Select the project virtualenv `.venv` as the interpreter.
3. Install the Jupyter section when PyCharm offers it. PyCharm then starts and
   manages the Jupyter server for you.
4. Open any `.ipynb` file and run the cells. The kernel is the project `.venv`.

No separate `jupyter notebook` process is required. The notebook stack
(`jupyterlab`, `notebook`, `ipykernel`) lives in `requirements-dev.txt` so it
does not leak into the production environment.

## Notes

- Every notebook starts with a bootstrap cell that inserts the repository root
  on `sys.path` and sets `ETL_DB_BACKEND=sqlite`, so notebooks never touch
  PostgreSQL by accident.
- Notebook 01 downloads the source dataset, so it needs network access.
- Notebooks 02 and 03 need the SQLite database under `data/warehouse/` and the
  landing file produced by notebook 01 or by `python -m violence_etl.cli download`.
- `.ipynb_checkpoints/` is gitignored, and the committed notebooks are stored
  without outputs.

## Notebooks

- `01_bronze_profiling.ipynb`: download or reuse the landing file, profile the
  raw CSV, and confirm the planning facts and the mirrored bronze table.
- `02_silver_validation.ipynb`: build silver, show the deduplication effect
  (15,696 to 14,212), the rejected-row breakdown, and the electoral-period
  distribution per year.
- `03_gold_analysis.ipynb`: build and query the four `gold_*` tables, including
  the top 5 departments and the crimes-by-electoral-period share.
