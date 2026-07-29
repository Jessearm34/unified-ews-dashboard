"""FastHTML data layer — imports from the existing modular data packages.

All three platforms (QuickBooks, SiteDocs, GeoTab) are available through
the same interfaces as the FastAPI backend.  No duplication.
"""

from __future__ import annotations

from data import qb_data as QB
from data import sd_data as SD
from data import gt_data as GT

# Re-export for convenience
load_qb_dataset = QB.qb_load_dataset
load_sd_dataset = SD.sd_load_dataset
