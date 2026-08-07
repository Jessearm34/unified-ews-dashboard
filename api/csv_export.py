"""CSV export utility — attach ``?format=csv`` to any /_api route to download data.

Usage in a route handler:
    return _csv(df, filename="report.csv")
"""

from __future__ import annotations

import io
import pandas as pd
from fastapi.responses import StreamingResponse, JSONResponse


def to_csv_response(df: pd.DataFrame, filename: str = "export.csv") -> StreamingResponse:
    """Return a streaming CSV download from a DataFrame."""
    if df.empty:
        return JSONResponse(
            {"error": "No data", "rows": 0}, status_code=200
        )
    output = io.StringIO()
    df.to_csv(output, index=False)
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
