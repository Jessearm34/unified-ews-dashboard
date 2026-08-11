"""Classification rules — driven entirely by Insperity's own department field.

FIELD → Direct.  SHOP → Indirect.  That's it.
"""


def classify(department_name: str | None) -> str:
    if department_name and str(department_name).strip().upper() == "FIELD":
        return "direct"
    return "indirect"
