"""No-file streaming feature worker for a separately frozen empirical controller.

Input: one initialization JSON line, then one complete release batch per cutoff.
Output: one acknowledgement/feature JSON line per input. No estimator fit here.
"""

import datetime
import json
import math
import sys

import numpy as np
import pandas as pd
from released_state import ReleasedState


def clean(value):
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (pd.Timestamp, datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float):
        if math.isinf(value):
            raise ValueError("infinite native feature")
        if math.isnan(value):
            return None
    return value


def emit(value):
    print(json.dumps(clean(value), allow_nan=False, separators=(",", ":")), flush=True)


initial = json.loads(sys.stdin.readline())
if set(initial) != {"reference_date", "ioc_buckets"}:
    raise ValueError("unexpected initialization fields")
state = ReleasedState(initial["reference_date"], initial["ioc_buckets"])
emit({"ready": True})
for line in sys.stdin:
    batch = json.loads(line)
    if set(batch) != {"cutoff", "history", "rankings", "targets"}:
        raise ValueError("unexpected release fields")
    outputs = state.step(**batch)
    emit({"outputs": outputs, "receipt": state.receipts[-1]})
