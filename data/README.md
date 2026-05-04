# Data Directory

Data is split by processing stage:

- `raw/`: immutable source files. Never edit files here in place.
- `interim/`: cleaned and normalized tables derived from raw data.
- `processed/`: contract-horizon panels and modeling datasets.
- `artifacts/`: cached model outputs, metrics, run metadata, and generated research results.

No data is included in the scaffold.

