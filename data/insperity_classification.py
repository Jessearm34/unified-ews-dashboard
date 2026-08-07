"""Classification rules — driven entirely by Insperity's own department field.

FIELD or SHOP → Direct.  Everything else → Indirect.

Vrutika updates someone's department in Insperity → the next sync
picks it up automatically.  No separate table, no manual steps.
"""

DIRECT_DEPT_NAMES = {"FIELD", "SHOP"}


def classify(department_name: str | None) -> str:
    if department_name and str(department_name).strip().upper() in DIRECT_DEPT_NAMES:
        return "direct"
    return "indirect"
