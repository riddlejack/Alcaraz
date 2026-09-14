"""Cell readers for the retained annual Tennis-Data workbooks.

Ported from the archive's ``work/MULTI01_market_acquisition/profile_annual.py``. That
file is an *acquisition-time* program: its ``main`` rewrites the acquisition manifest in
its own directory and writes ``profiles.json``, ``headers_by_year.json`` and
``year_inventory.csv`` beside it. No chain stage calls it; what the chain reads from it
is the workbook-cell vocabulary the ``join`` stage loads by path -- ``blank``,
``finite_native``, ``stringify``, ``date_value`` and the two pinned workbook adapters.
Those are ported here verbatim; the acquisition driver and the profiling report it
writes are not, because they would write into the archive and nothing in the package
runs them.

The archive's copy put ``ROOT/vendor`` on ``sys.path`` to reach its bundled ``openpyxl``
and ``xlrd``; here both are declared dependencies and imported by name.
"""

from __future__ import annotations

import datetime as dt
import math
from typing import Any

import openpyxl
import xlrd

__all__ = ["blank", "date_value", "finite_native", "openpyxl", "stringify", "xlrd"]


def blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def finite_native(value: Any) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    return str(value)


def date_value(value: Any, kind: str, datemode: int | None = None) -> dt.datetime | None:
    if kind == "xls_date" and finite_native(value) and datemode is not None:
        try:
            return xlrd.xldate.xldate_as_datetime(value, datemode)
        except ValueError, xlrd.xldate.XLDateError:
            return None
    if isinstance(value, dt.datetime):
        return value
    if isinstance(value, dt.date):
        return dt.datetime.combine(value, dt.time())
    if isinstance(value, str):
        text = value.strip()
        for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
            try:
                return dt.datetime.strptime(text, fmt)
            except ValueError:
                pass
    return None
