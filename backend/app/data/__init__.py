"""Checked-in reference data: brokers, companies, breach sources and the demo fixtures.

Load a file with load_json("brokers.json"). Don't hard-code broker lists or company
domains in Python; add them to these JSON files instead. Fixtures use fictional people
and .example domains only.
"""

import json
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent


def load_json(name: str) -> Any:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))
