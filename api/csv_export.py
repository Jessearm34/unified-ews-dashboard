"""CSV export utility — attach ``?format=csv`` to any /_api route to download data.

Usage in a route handler:
    return to_csv_response(df, filename="report.csv")
"""

from __future__ import annotations

import io
import pandas as pd
from fastapi.responses import StreamingResponse


def to_csv_response(df: pd.DataFrame, filename: str = "export.csv") -> StreamingResponse:
    """Return a streaming CSV download from a DataFrame.

    Always returns a CSV file (empty DataFrame -> header-only or blank file),
    never a JSON payload.
    """
    if df is None:
        df = pd.DataFrame()
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
