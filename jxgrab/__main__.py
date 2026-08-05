# Enables `python -m jxgrab` (used by the cron entrypoint and README).
# main.py uses package-relative imports, so it must run as a module, not as a
# bare script (`python main.py` would ImportError on `from .config import ...`).
from .main import main

raise SystemExit(main())
