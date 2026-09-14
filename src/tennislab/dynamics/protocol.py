"""Past-only yearly fits and selection for two fixed sports representations.

Ported verbatim from the archive's ``references/SR02_models/protocol.py``. Reads
``a_won`` only on rows strictly before the outer year (``prior_rows``) to fit and
select the market procedure; every such read is marked ``# outcome-history read``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json

import numpy as np

from tennislab.dynamics import market
from tennislab.dynamics.dynamic import DynamicsError

PENALTIES = (None, 1.0, 0.1, 0.01, 0.001)
SPORTS = ("dynamic", "unadjusted")


def key_hash(rows):
    return hashlib.sha256(
        json.dumps([r["match_id"] for r in rows], separators=(",", ":")).encode()
    ).hexdigest()


def prior_rows(rows, year, length=3):
    low = dt.date(year - length, 1, 1).isoformat()
    high = (dt.date(year, 1, 1) - dt.timedelta(days=2)).isoformat()
    return [
        r
        for r in rows
        if low <= r["match_date"] <= high
        and r["identity_tier"] == "primary"
        and r["PS_valid"]
        and int(r["source_season"]) == int(r["match_date"][:4])
    ]


def target_rows(rows, year):
    return [
        r
        for r in rows
        if int(r["match_date"][:4]) == year and int(r["source_season"]) == year and r["PS_valid"]
    ]


def values(rows, field):
    return np.array([r[field] for r in rows], dtype=float)


class Store:
    def __init__(self, rows, record_sink=None):
        for row in rows:
            if type(row["PS_valid"]) is not bool or row["identity_tier"] not in (
                "primary",
                "provisional",
            ):
                raise DynamicsError("Invalid market/identity metadata")
            date = dt.date.fromisoformat(row["match_date"])
            if date.isoformat() != row["match_date"]:
                raise DynamicsError("Noncanonical match date")
            if row["PS_valid"]:
                market.probabilities(
                    [
                        row["q"],
                        row["dynamic_match_probability_a"],
                        row["unadjusted_match_probability_a"],
                    ]
                )
        self.rows = sorted(rows, key=lambda r: (r["match_date"], r["match_id"]))
        if len({r["match_id"] for r in rows}) != len(rows):
            raise DynamicsError("Duplicate match identity")
        self.fits = {}
        self.records = []
        self.paths = {}
        self.record_sink = record_sink

    def get(self, year, sports=None, penalty=None):
        if penalty is None:
            sports = None
        elif penalty not in PENALTIES or sports not in SPORTS:
            raise DynamicsError("Unknown candidate")
        key = (year, sports, penalty)
        if key in self.fits:
            return self.fits[key]
        training = prior_rows(self.rows, year)
        if not training:
            raise DynamicsError("No eligible market training rows")
        record = {
            "year": year,
            "sports": sports,
            "penalty": penalty,
            "training_min_date": training[0]["match_date"],
            "training_max_date": training[-1]["match_date"],
            "training_keys_sha256": key_hash(training),
        }
        try:
            product = market.fit(
                values(training, "q"),
                values(training, "a_won"),  # outcome-history read: prior-year fit rows
                values(training, sports + "_match_probability_a") if sports else None,
                penalty,
            )
        except Exception as exc:
            if self.record_sink:
                self.record_sink({**record, "status": "failed", "error": str(exc)})
            raise DynamicsError(
                f"Market fit failed for year={year}, sports={sports}, penalty={penalty}: {exc}"
            ) from exc
        self.fits[key] = product
        record["fit"] = product.record()
        self.records.append(record)
        if self.record_sink:
            self.record_sink({**record, "status": "complete"})
        return product

    def predictions(self, year, sports, penalty):
        key = (year, sports if penalty is not None else None, penalty)
        if key not in self.paths:
            rows = target_rows(self.rows, year)
            if not rows:
                raise DynamicsError("No yearly market targets")
            product = self.get(*key)
            probability = product.predict(
                values(rows, "q"),
                values(rows, sports + "_match_probability_a") if penalty is not None else None,
            )
            if not np.isfinite(probability).all() or np.any(
                (probability <= 0) | (probability >= 1)
            ):
                raise DynamicsError("Invalid fitted market forecast")
            self.paths[key] = dict(zip((r["match_id"] for r in rows), probability, strict=True))
        return self.paths[key]

    def select(self, year, sports):
        trials = []
        available = prior_rows(self.rows, year)
        for penalty in PENALTIES:
            annual = []
            for past_year in range(year - 3, year):
                held = [r for r in available if int(r["match_date"][:4]) == past_year]
                if not held:
                    raise DynamicsError("Missing required market validation year")
                probability = self.predictions(past_year, sports, penalty)
                metric = market.scores(
                    [probability[r["match_id"]] for r in held],
                    values(held, "a_won"),  # outcome-history read: prior-year validation rows
                )
                annual.append({"year": past_year, "keys_sha256": key_hash(held), **metric})
            trials.append(
                {
                    "penalty": penalty,
                    "loss": float(np.mean([a["log_loss"] for a in annual])),
                    "annual": annual,
                }
            )
        choice = market.select(trials)
        return {
            "year": year,
            "sports": sports,
            "penalty": choice["penalty"],
            "loss": choice["loss"],
            "trials": trials,
        }


def run(rows, outer_years=range(2017, 2025), record_sink=None):
    store = Store(rows, record_sink=record_sink)
    predictions, selections = [], []
    for year in outer_years:
        chosen = {sports: store.select(year, sports) for sports in SPORTS}
        selections.extend(chosen.values())
        targets = target_rows(store.rows, year)
        baseline = store.predictions(year, "dynamic", None)
        full = {s: store.predictions(year, s, chosen[s]["penalty"]) for s in SPORTS}
        for row in targets:
            match_id = row["match_id"]
            predictions.append(
                {
                    "match_id": match_id,
                    "year": year,
                    "match_date": row["match_date"],
                    "market_calibrated": float(baseline[match_id]),
                    "dynamic_augmented": float(full["dynamic"][match_id]),
                    "unadjusted_augmented": float(full["unadjusted"][match_id]),
                    "pinnacle_raw_normalized": row["q"],
                    "dynamic_match_probability_a": row["dynamic_match_probability_a"],
                    "unadjusted_match_probability_a": row["unadjusted_match_probability_a"],
                }
            )
    return {"predictions": predictions, "selections": selections, "fits": store.records}
