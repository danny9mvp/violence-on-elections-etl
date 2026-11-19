# Notebooks

Exploratory and validation notebooks for the Violence on Elections ETL.

## How to run them

The intended way to run these notebooks is the PyCharm IDE Managed Jupyter
server, with the project `.venv` as the kernel:

1. Open the project in PyCharm and go to `Settings > Project > Python Interpreter`.
2. Select the project virtualenv `.venv` as the interpreter.
3. If PyCharm offers to install the Jupyter section, accept. PyCharm then starts
   and manages the Jupyter server for you.
4. Open a notebook. In the notebook toolbar, choose the managed server as the
   Jupyter server and select the project `.venv` interpreter as the kernel.
5. Run the cells, starting with the bootstrap cell.

No separate `jupyter notebook` process is required. The notebook stack
(`jupyterlab`, `notebook`, `ipykernel`) lives in `requirements-dev.txt` so it
does not leak into the production environment. `README.md` has the same steps.

## Notes

- Every notebook starts with a bootstrap cell that adds the project to
  `sys.path` and sets `ENV=DEV`, so notebooks use the local SQLite database
  and never touch PostgreSQL by accident.
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
