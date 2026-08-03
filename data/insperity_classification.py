"""Direct/Indirect classification — source of truth from Vrutika Patel (Controller & HR).

H = Direct (field operators).  S = Indirect (SGA / support / management).
All names in UPPERCASE for matching against Insperity's familyName + givenName.
"""

# Keyed by LASTNAME FIRSTNAME (uppercase) as returned by Insperity
CLASSIFICATION = {
    # Direct — Field Operators (H)
    "PERRYMAN ADAM": "direct",
    "KEEL COLBY": "direct",
    "BARRETT JARED": "direct",
    "CANTU JOSE": "direct",        # Joey
    "LONG DAVID": "direct",
    "NEWBOLD CARTER": "direct",
    "HOWER HAILEN": "direct",
    "MUNOZ RAUL": "direct",

    # Indirect — SGA / Support / Management (S)
    "BLAKEMAN BRADLEY": "indirect",
    "MCBRYANT JAMES": "indirect",
    "ELLIS JUSTIN": "indirect",
    "KEYSER JUSTIN": "indirect",
    "COHEE LONNY": "indirect",
    "SKRBICH MIKE": "indirect",
    "NOUREDDINE SCOTT-ALI": "indirect",
    "PATEL VRUTIKA": "indirect",
    "CARMODY CASEY": "indirect",   # CEO
}
