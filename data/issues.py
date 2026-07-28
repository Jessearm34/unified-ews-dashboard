"""Cross-platform issues aggregation — "Issues Needing Attention" panel.

Aggregates items from SiteDocs and GeoTab that need attention.
Designed to be extensible for Phase 2 alert thresholds and Phase 3
cross-platform correlations.

Each issue: {
    "platform": "SD" | "GT",
    "severity": "high" | "medium" | "low",
    "category": str,  # e.g. "Overdue Schedule", "Expired Cert", "Open Incident"
    "label": str,     # short human-readable description
    "detail": str,    # additional context
    "link": str,      # dashboard path to drill into
}
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from data import sd_data as SD
from data import gt_data as GT


def collect_issues(ds: SD.SdDataset | None = None,
                   gt_since: datetime | None = None,
                   gt_until: datetime | None = None,
                   max_items: int = 20) -> list[dict[str, Any]]:
    """Collect issues from all available platforms, sorted by severity.

    Args:
        ds: Loaded SdDataset (if None, SD issues are skipped).
        gt_since/gt_until: Time range for GT queries.
        max_items: Max issues to return.

    Returns:
        List of issue dicts sorted: high severity first, then medium, then low.
    """
    issues: list[dict[str, Any]] = []

    # ── SiteDocs Issues ──────────────────────────────────────────────

    if ds is not None:
        # Overdue & late schedule items
        if hasattr(ds, 'schedules') and not ds.schedules.empty:
            overdue = SD.overdue_items(ds.schedules)
            if not overdue.empty:
                for _, r in overdue.head(10).iterrows():
                    status = str(r.get("status", "Overdue"))
                    days = int(r.get("daysOverdue", 0))
                    form = str(r.get("formTypeName", "—"))[:50]
                    loc = str(r.get("locationName", "—"))[:20]
                    worker = str(r.get("responsibleEmployeeName", "—"))[:20]
                    sev = "high" if days > 30 else ("medium" if days > 7 else "low")
                    issues.append({
                        "platform": "SD",
                        "severity": sev,
                        "category": "Overdue Schedule" if status == "Overdue" else "Late Schedule",
                        "label": f"{form} — {loc}",
                        "detail": f"{worker} · {days}d overdue",
                        "sort_key": days,
                    })

        # Expired certifications
        if hasattr(ds, 'certifications') and not ds.certifications.empty:
            today = pd.Timestamp(date.today())
            certs = ds.certifications
            has_expires = certs["Expires"].notna()
            if has_expires.any():
                expired = certs[has_expires & (certs["Expires"] < today)]
                if not expired.empty:
                    count = len(expired)
                    issues.append({
                        "platform": "SD",
                        "severity": "high" if count > 5 else ("medium" if count > 2 else "low"),
                        "category": "Expired Certifications",
                        "label": f"{count} expired certification{'s' if count != 1 else ''}",
                        "detail": "Needs immediate renewal",
                        "sort_key": count * 10,
                    })
                expiring_soon = certs[has_expires & (certs["Expires"] >= today) & (certs["Expires"] <= today + timedelta(days=30))]
                if not expiring_soon.empty:
                    count = len(expiring_soon)
                    issues.append({
                        "platform": "SD",
                        "severity": "medium" if count > 10 else "low",
                        "category": "Certifications Expiring Soon",
                        "label": f"{count} certification{'s' if count != 1 else ''} expiring within 30 days",
                        "detail": "Schedule renewals",
                        "sort_key": count,
                    })

        # Open incidents >30 days
        if hasattr(ds, 'incidents') and not ds.incidents.empty:
            inc = ds.incidents
            if "LatestStatus" in inc.columns:
                open_mask = inc["LatestStatus"].astype(str).str.lower().isin(["open", "investigation"])
                if open_mask.any() and "CreatedOn" in inc.columns:
                    old_open = inc[open_mask].copy()
                    old_open["_age"] = (pd.Timestamp.now() - pd.to_datetime(old_open["CreatedOn"], errors="coerce")).dt.days
                    old_open = old_open.dropna(subset=["_age"])
                    old_open = old_open[old_open["_age"] > 30].sort_values("_age", ascending=False)
                    for _, r in old_open.head(5).iterrows():
                        days = int(r["_age"])
                        desc = str(r.get("Name", r.get("TypeName", "Incident")))[:60]
                        status = str(r.get("LatestStatus", "Open"))
                        sev = "high" if days > 90 else "medium"
                        issues.append({
                            "platform": "SD",
                            "severity": sev,
                            "category": f"Open {status}",
                            "label": f"{desc} — {days}d old",
                            "detail": f"Status: {status}",
                            "sort_key": days,
                        })

    # ── GeoTab Issues ────────────────────────────────────────────────

    if gt_since is None:
        gt_since = datetime.now() - timedelta(days=365)
    if gt_until is None:
        gt_until = datetime.now()

    try:
        eng = GT.gt_engine()
        if eng is not None:
            # Fault codes
            try:
                fl = GT.maintenance_metrics(gt_since, gt_until)
                if fl:
                    freq = fl.get("fault_frequency", [])
                    if freq:
                        total_faults = sum(f["count"] for f in freq)
                        issues.append({
                            "platform": "GT",
                            "severity": "high" if total_faults > 20 else ("medium" if total_faults > 5 else "low"),
                            "category": "Vehicle Fault Codes",
                            "label": f"{total_faults} fault code{'s' if total_faults != 1 else ''} recorded",
                            "detail": f"Top: {freq[0]['fault_code']} ({freq[0]['count']}x)",
                            "sort_key": total_faults * 2,
                        })
            except Exception:
                pass

            # Low-scoring drivers
            try:
                sd_rank = GT.safety_driver_rankings(gt_since, gt_until)
                if sd_rank:
                    low = [d for d in sd_rank if d["score"] < 60 and d["trip_count"] > 0]
                    if low:
                        worst = low[0]
                        issues.append({
                            "platform": "GT",
                            "severity": "high" if worst["score"] < 40 else "medium",
                            "category": "Low Driver Safety Score",
                            "label": f"{len(low)} driver{'s' if len(low) != 1 else ''} below 60",
                            "detail": f"Worst: {worst['name']} ({worst['score']})",
                            "sort_key": (60 - worst["score"]) * 3,
                        })
            except Exception:
                pass
    except Exception:
        pass

    # ── Threshold-based alerts (computed from SD data) ─────────────

    if ds is not None:
        try:
            # Schedule compliance dropped below threshold
            sched_c = SD.schedule_counts(ds.schedules)
            comp_pct = sched_c.get("completion_pct", 100)
            if 0 < comp_pct < 70:
                issues.append({
                    "platform": "SD", "severity": "high",
                    "category": "Compliance Alert",
                    "label": f"Schedule compliance at {comp_pct:.0f}% (below 70% threshold)",
                    "detail": f"{sched_c.get('overdue', 0)} overdue · {sched_c.get('late', 0)} late",
                    "sort_key": 100,
                })
        except Exception:
            pass

        try:
            # No BBSO submissions in 30+ days
            brc = SD.bbso_rir_counts(ds.forms)
            if brc["bbso_this_month"] == 0 and brc["total_bbso"] > 0:
                # Check last BBSO date
                bbso_forms = SD._filter_bbso(ds.forms)  # type: ignore
                if not bbso_forms.empty:
                    date_col = "CreatedOn" if "CreatedOn" in bbso_forms.columns else "createdOn"
                    if date_col in bbso_forms.columns:
                        last_date = pd.to_datetime(bbso_forms[date_col]).max()
                        days_since = (pd.Timestamp.now() - last_date).days
                        if days_since > 30:
                            issues.append({
                                "platform": "SD", "severity": "medium",
                                "category": "BBSO Stale",
                                "label": f"No BBSO submissions in {days_since} days",
                                "detail": "Schedule observations to maintain safety engagement",
                                "sort_key": days_since,
                            })
        except Exception:
            pass

        try:
            # Incident close time above threshold
            ct = SD.incident_close_time(ds.incidents)
            if ct["mean_days"] > 30 and ct["closed_count"] > 0:
                issues.append({
                    "platform": "SD", "severity": "medium",
                    "category": "Slow Incident Resolution",
                    "label": f"Avg close time {ct['mean_days']}d (above 30d threshold)",
                    "detail": f"Median {ct['median_days']}d · {ct['closed_count']} closed",
                    "sort_key": int(ct["mean_days"]),
                })
        except Exception:
            pass

    # Sort: high → medium → low, then by sort_key descending
    severity_order = {"high": 0, "medium": 1, "low": 2}
    issues.sort(key=lambda i: (severity_order.get(i["severity"], 9), -i.get("sort_key", 0)))

    return issues[:max_items]


# ── Unified Safety Score ────────────────────────────────────────────


def unified_safety_score(sd_ds: SD.SdDataset | None = None,
                         gt_since: datetime | None = None,
                         gt_until: datetime | None = None) -> dict[str, Any]:
    """Composite safety score from SiteDocs engagement + GeoTab driver safety.

    Components (each 0-100):
    - Worker Participation (40%): % of active workers submitting safety forms
    - Schedule Compliance (20%): schedule completion rate
    - BBSO-to-Incident Ratio (20%): normalized, 5:1 = 100, 0 = 0
    - Avg Driver Safety Score (20%): average of driver scores from GT

    Returns:
        {"score": float, "components": {...}, "trend": [...]}
    """
    components: dict[str, float] = {}
    weights = {"participation": 0.4, "compliance": 0.2, "bbso_ratio": 0.2, "driver_score": 0.2}
    used_weights = 0.0
    weighted_sum = 0.0

    if sd_ds is not None:
        # Worker Participation (0-100)
        part = SD.worker_participation(sd_ds.workers, sd_ds.forms)
        participation = part["pct"]
        components["participation"] = participation
        weighted_sum += participation * weights["participation"]
        used_weights += weights["participation"]

        # Schedule Compliance (0-100)
        sched_c = SD.schedule_counts(sd_ds.schedules)
        compliance = sched_c["completion_pct"]
        components["compliance"] = compliance
        weighted_sum += compliance * weights["compliance"]
        used_weights += weights["compliance"]

        # BBSO-to-Incident Ratio (normalized to 0-100)
        bir = SD.bbso_incident_ratio(sd_ds.forms, sd_ds.incidents)
        raw_ratio = bir["ratio"]
        # 5:1 = 100, 2:1 = 40, 0 = 0, linear in between
        bbso_score = min(100, max(0, raw_ratio * 20))
        components["bbso_score"] = bbso_score
        weighted_sum += bbso_score * weights["bbso_ratio"]
        used_weights += weights["bbso_ratio"]

    # GeoTab driver safety
    if gt_since is None:
        gt_since = datetime.now() - timedelta(days=365)
    if gt_until is None:
        gt_until = datetime.now()
    try:
        eng = GT.gt_engine()
        if eng is not None:
            sd_rank = GT.safety_driver_rankings(gt_since, gt_until)
            if sd_rank:
                active = [d for d in sd_rank if d["trip_count"] > 0]
                if active:
                    avg_score = sum(d["score"] for d in active) / len(active)
                    components["driver_score"] = avg_score
                    weighted_sum += avg_score * weights["driver_score"]
                    used_weights += weights["driver_score"]
    except Exception:
        pass

    score = round(weighted_sum / used_weights, 1) if used_weights > 0 else 0.0
    return {"score": score, "components": components}


# ── Person-Level Cross-Platform Join ─────────────────────────────────


def cross_person_profiles(sd_ds: SD.SdDataset | None = None,
                          gt_since: datetime | None = None,
                          gt_until: datetime | None = None) -> list[dict[str, Any]]:
    """Match SiteDocs workers with GeoTab drivers by name.

    Returns combined safety profile per person. Matching is approximate —
    by first+last name. Drivers not found in SD workers appear as
    "driver-only" profiles.

    Each profile: {
        "name": str, "matched": bool,
        "sd_worker_id": str | None, "sd_active": bool, "sd_role": str,
        "sd_bbso": int, "sd_rir": int, "sd_participation_pct": float,
        "gt_driver_name": str | None, "gt_trip_count": int,
        "gt_miles": float, "gt_safety_score": float | None,
    }
    """
    profiles: dict[str, dict] = {}

    # Collect SD workers
    if sd_ds is not None and not sd_ds.workers.empty:
        active = sd_ds.workers.copy()
        if "Active" in active.columns:
            active = active[active["Active"].astype(bool)]
        for _, w in active.iterrows():
            name = f"{w.get('FirstName','')} {w.get('LastName','')}".strip().lower()
            if not name:
                continue
            wid = str(w.get("Id", ""))
            is_ext = bool(w.get("IsExternal", False)) if "IsExternal" in active.columns else False
            profiles[name] = {
                "name": f"{w.get('FirstName','')} {w.get('LastName','')}".strip(),
                "matched": False,
                "sd_worker_id": wid,
                "sd_active": True,
                "sd_role": "Contractor" if is_ext else "Employee",
                "sd_bbso": 0, "sd_rir": 0, "sd_participation_pct": 0.0,
                "gt_driver_name": None, "gt_trip_count": 0,
                "gt_miles": 0.0, "gt_safety_score": None,
            }

    # Enrich SD profiles with BBSO/RIR counts
    if sd_ds is not None and not sd_ds.forms.empty:
        bbso = SD._filter_bbso(sd_ds.forms)  # type: ignore
        rir = SD._filter_rir(sd_ds.forms)  # type: ignore
        created_col = "CreatedBy" if "CreatedBy" in sd_ds.forms.columns else "createdBy"

        if created_col in bbso.columns:
            bbso_by_wid = bbso[created_col].value_counts().to_dict()
        else:
            bbso_by_wid = {}
        if created_col in rir.columns:
            rir_by_wid = rir[created_col].value_counts().to_dict()
        else:
            rir_by_wid = {}

        for name, prof in profiles.items():
            wid = prof["sd_worker_id"]
            prof["sd_bbso"] = int(bbso_by_wid.get(wid, 0))
            prof["sd_rir"] = int(rir_by_wid.get(wid, 0))
            # Participation rate = has at least some form activity
            if prof["sd_bbso"] > 0 or prof["sd_rir"] > 0:
                prof["sd_participation_pct"] = 100.0

    # Collect GT drivers and match
    if gt_since is None:
        gt_since = datetime.now() - timedelta(days=365)
    if gt_until is None:
        gt_until = datetime.now()
    try:
        eng = GT.gt_engine()
        if eng is not None:
            dm = GT.driver_metrics(gt_since, gt_until)
            for d in dm:
                d_name = str(d.get("name", "")).strip().lower()
                if not d_name:
                    continue

                # Try to match
                display_name = str(d.get("name", "")).strip()
                if d_name in profiles:
                    prof = profiles[d_name]
                    prof["matched"] = True
                    prof["gt_driver_name"] = display_name
                    prof["gt_trip_count"] = int(d.get("trip_count", 0))
                    prof["gt_miles"] = round(float(d.get("distance_driven", 0)), 1)
                else:
                    # Driver-only — not in SD
                    profiles[d_name] = {
                        "name": display_name, "matched": False,
                        "sd_worker_id": None, "sd_active": False,
                        "sd_role": "", "sd_bbso": 0, "sd_rir": 0,
                        "sd_participation_pct": 0.0,
                        "gt_driver_name": display_name,
                        "gt_trip_count": int(d.get("trip_count", 0)),
                        "gt_miles": round(float(d.get("distance_driven", 0)), 1),
                        "gt_safety_score": None,
                    }

            # Add safety scores to matched profiles
            sr = GT.safety_driver_rankings(gt_since, gt_until)
            score_map = {str(r["name"]).strip().lower(): r["score"] for r in sr}
            for name, prof in profiles.items():
                if prof.get("gt_driver_name"):
                    dl = prof["gt_driver_name"].strip().lower()
                    if dl in score_map:
                        prof["gt_safety_score"] = score_map[dl]
    except Exception:
        pass

    # Sort: matched profiles first, then by name
    result = sorted(profiles.values(),
                    key=lambda p: (not p.get("matched", False), p.get("name", "")))
    return result
