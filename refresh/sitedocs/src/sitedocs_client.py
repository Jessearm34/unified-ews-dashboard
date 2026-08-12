"""SiteDocs API client — reads HSE data from the SiteDocs REST API.

SiteDocs is EWS's safety documentation system (JSA/safe-work permits,
incidents, equipment inspections, worker certifications, training records).

Endpoints documented at https://api-1.sitedocs.com/swagger/ui/index
Base: https://api-1.sitedocs.com

Authentication: ``Authorization`` header with the API token.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

import requests

from src.config import is_placeholder, settings
from src.models import DataSheet

logger = logging.getLogger(__name__)


class SiteDocsClient:
    def __init__(self) -> None:
        self.session = requests.Session()

    def credentials_ready(self) -> bool:
        return bool(
            settings.sitedocs_api_key
            and not is_placeholder(settings.sitedocs_api_key)
        )

    # ------------------------------------------------------------------ #
    # Generic GET helpers
    # ------------------------------------------------------------------ #

    def _get_paged(
        self, path: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Paginate through a SiteDocs list endpoint.

        SiteDocs uses ``page`` (0-indexed) and ``count`` (max 100).
        The response is an array directly (most endpoints) or wrapped.
        Stops when fewer rows than ``count`` are returned.
        """
        url = f"{settings.sitedocs_api_base}{path}"
        rows: list[dict[str, Any]] = []
        page = 0
        page_size = 100

        while True:
            p = dict(params or {})
            p["page"] = page
            p["count"] = page_size
            resp = self.session.get(
                url, headers=settings.headers, params=p, timeout=30
            )
            resp.raise_for_status()
            data = resp.json()

            # Endpoints either return an array directly or wrap in a response object
            if isinstance(data, list):
                batch = data
            elif isinstance(data, dict):
                batch = data.get("rows") or data.get("data") or []
                if isinstance(batch, dict):
                    batch = batch.get("items") or list(batch.values())[0] if isinstance(batch, dict) else []
            else:
                batch = []

            if not isinstance(batch, list):
                batch = []

            rows.extend(batch)
            if len(batch) < page_size:
                break
            page += 1

        return rows

    def _get_list(self, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Simple GET that returns a list — no pagination."""
        url = f"{settings.sitedocs_api_base}{path}"
        resp = self.session.get(url, headers=settings.headers, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("rows") or data.get("data") or []
        return []

    def _get(self, path: str) -> dict[str, Any]:
        url = f"{settings.sitedocs_api_base}{path}"
        resp = self.session.get(url, headers=settings.headers, timeout=30)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------ #
    # Real fetchers (match the actual Swagger 2.0 spec)
    # ------------------------------------------------------------------ #

    def fetch_workers(self) -> list[dict[str, Any]]:
        """GET /api/v1/workers — returns list of WorkerViewModel.

        Key fields: Id, Active, FirstName, LastName, JobTitle, Email,
        MobileNumber, PhoneNumber, DateHired, ContractorId, ContractorName,
        IsExternal, EmployeeNumber, EmployerId.
        """
        if not self.credentials_ready() or settings.use_stub_data:
            return self._stub_workers()
        return self._get_paged("/api/v1/workers")

    def fetch_equipment(self) -> list[dict[str, Any]]:
        """GET /api/v1/equipments — returns list of EquipmentViewModel.

        Key fields: EquipmentId, Name, EquipmentTypeId, EquipmentTypeName,
        IsDeleted, CreatedOn.
        The GET-only model doesn't include IsActive — that's in details.
        """
        if not self.credentials_ready() or settings.use_stub_data:
            return self._stub_equipment()
        return self._get_paged("/api/v1/equipments")

    def fetch_incidents(self) -> list[dict[str, Any]]:
        """GET /api/v1/incidentfolders — returns list of ProcessFolderViewModelV2.

        Key fields: Id, Name, TypeName, LatestStatus, CreatedOn,
        ModifiedOn, IsActive, CreatedBy.
        SiteDocs stores incidents as "incident folders" (process folders
        of type Incident). No standalone /api/v1/incidents exists.
        """
        if not self.credentials_ready() or settings.use_stub_data:
            return self._stub_incidents()
        return self._get_paged("/api/v1/incidentfolders")

    def fetch_certifications(self) -> list[dict[str, Any]]:
        """GET /api/v1/certifications — returns list of CertificationViewModel.

        Key fields: Id, CertificationTypeId, CertificationTypeName, Issuer,
        WorkerId, Acquired, Expires, IsArchived, Attachments.
        """
        if not self.credentials_ready() or settings.use_stub_data:
            return self._stub_certifications()
        return self._get_paged("/api/v1/certifications")

    def fetch_forms_and_types(self) -> list[dict[str, Any]]:
        """Pull all forms — they already carry DocumentTemplateName."""
        if not self.credentials_ready() or settings.use_stub_data:
            return self._stub_forms()
        forms = self._get_paged("/api/v1/forms")
        logger.info("  %d forms total", len(forms))
        return forms

    def fetch_locations(self) -> list[dict[str, Any]]:
        """GET /api/v1/locations"""
        if not self.credentials_ready() or settings.use_stub_data:
            return self._stub_locations()
        return self._get_list("/api/v1/locations")

    def fetch_company_types(self) -> list[dict[str, Any]]:
        """GET /api/v1/companytypes"""
        if not self.credentials_ready() or settings.use_stub_data:
            return self._stub_company_types()
        return self._get_list("/api/v1/companytypes")

    def fetch_certification_types(self) -> list[dict[str, Any]]:
        """GET /api/v1/certificationtypes"""
        if not self.credentials_ready() or settings.use_stub_data:
            return self._stub_certification_types()
        return self._get_list("/api/v1/certificationtypes")

    def fetch_form_types(self) -> list[dict[str, Any]]:
        """GET /api/v1/formtypes"""
        if not self.credentials_ready() or settings.use_stub_data:
            return self._stub_form_types()
        return self._get_list("/api/v1/formtypes")

    def fetch_signatures(self) -> list[dict[str, Any]]:
        """GET /api/v1/signatures"""
        if not self.credentials_ready() or settings.use_stub_data:
            return self._stub_signatures()
        return self._get_paged("/api/v1/signatures")

    def fetch_schedules(self) -> list[dict[str, Any]]:
        """GET /api/v1/schedules/form/search"""
        if not self.credentials_ready() or settings.use_stub_data:
            return self._stub_schedules()
        return self._get_paged("/api/v1/schedules/form/search")

    # ------------------------------------------------------------------ #
    # Stub data — every dataset gets realistic stubs so the pipeline
    # always has something to ingest and display, even when the API
    # is unreachable.
    # ------------------------------------------------------------------ #

    def _stub_workers(self) -> list[dict[str, Any]]:
        return [
            {"Id": "w1", "Active": True, "FirstName": "Juan", "LastName": "Martinez",
             "Email": "juan.martinez@energywatersolutions.com",
             "MobileNumber": "432-555-0101", "JobTitle": "Field Operator",
             "DateHired": "2022-03-15", "EmployerId": None, "ContractorName": None,
             "IsExternal": False},
            {"Id": "w2", "Active": True, "FirstName": "Sarah", "LastName": "Chen",
             "Email": "sarah.chen@energywatersolutions.com",
             "MobileNumber": "432-555-0102", "JobTitle": "HSE Coordinator",
             "DateHired": "2023-01-10", "EmployerId": None, "ContractorName": None,
             "IsExternal": False},
            {"Id": "w3", "Active": True, "FirstName": "Mike", "LastName": "Gonzalez",
             "Email": "mike.g@officerigger.com",
             "MobileNumber": "432-555-0103", "JobTitle": "Rigger",
             "DateHired": "2024-06-01", "ContractorName": "Office Rigger",
             "IsExternal": True},
            {"Id": "w4", "Active": True, "FirstName": "Lisa", "LastName": "Patel",
             "Email": "lisa.patel@energywatersolutions.com",
             "MobileNumber": "432-555-0104", "JobTitle": "Process Engineer",
             "DateHired": "2021-11-01", "EmployerId": None, "ContractorName": None,
             "IsExternal": False},
            {"Id": "w5", "Active": True, "FirstName": "Tom", "LastName": "Rodriguez",
             "Email": "tom.r@officerigger.com",
             "MobileNumber": "432-555-0105", "JobTitle": "Mechanic",
             "DateHired": "2024-02-15", "ContractorName": "Office Rigger",
             "IsExternal": True},
            {"Id": "w6", "Active": False, "FirstName": "Emily", "LastName": "Johnson",
             "Email": "emily.j@energywatersolutions.com",
             "MobileNumber": "432-555-0106", "JobTitle": "Admin",
             "DateHired": "2023-06-01", "EmployerId": None, "ContractorName": None,
             "IsExternal": False},
        ]

    def _stub_equipment(self) -> list[dict[str, Any]]:
        return [
            {"EquipmentId": "e1", "Name": "Frac Pump #1", "EquipmentTypeName": "Pump",
             "CreatedOn": "2022-01-15", "IsDeleted": False},
            {"EquipmentId": "e2", "Name": "Frac Pump #2", "EquipmentTypeName": "Pump",
             "CreatedOn": "2022-01-15", "IsDeleted": False},
            {"EquipmentId": "e3", "Name": "Evaporator Unit Alpha", "EquipmentTypeName": "Evaporator",
             "CreatedOn": "2024-03-01", "IsDeleted": False},
            {"EquipmentId": "e4", "Name": "Forklift #1", "EquipmentTypeName": "Forklift",
             "CreatedOn": "2023-06-01", "IsDeleted": False},
            {"EquipmentId": "e5", "Name": "Dozer D9", "EquipmentTypeName": "Heavy Equipment",
             "CreatedOn": "2021-11-01", "IsDeleted": False},
        ]

    def _stub_incidents(self) -> list[dict[str, Any]]:
        return [
            {"Id": "i1", "Name": "Slip on wet surface — evaporator area",
             "TypeName": "Near Miss", "LatestStatus": "Closed",
             "CreatedOn": "2025-11-15", "IsActive": False},
            {"Id": "i2", "Name": "Cut from steel strapping",
             "TypeName": "First Aid", "LatestStatus": "Closed",
             "CreatedOn": "2026-01-22", "IsActive": False},
            {"Id": "i3", "Name": "Hydraulic hose burst — frac pump pressure test",
             "TypeName": "Equipment Damage", "LatestStatus": "Investigation",
             "CreatedOn": "2026-03-04", "IsActive": True},
            {"Id": "i4", "Name": "Chemical spill — HCl unloading",
             "TypeName": "Near Miss", "LatestStatus": "Closed",
             "CreatedOn": "2026-04-10", "IsActive": False},
            {"Id": "i5", "Name": "Back strain — 55-gal drum lift",
             "TypeName": "Recordable", "LatestStatus": "Open",
             "CreatedOn": "2026-05-28", "IsActive": True},
        ]

    def _stub_certifications(self) -> list[dict[str, Any]]:
        return [
            {"Id": "c1", "CertificationTypeName": "H2S Awareness", "WorkerId": "w1",
             "Acquired": "2024-01-15", "Expires": "2027-01-15", "IsArchived": False},
            {"Id": "c2", "CertificationTypeName": "Confined Space Entry", "WorkerId": "w1",
             "Acquired": "2024-03-01", "Expires": "2027-03-01", "IsArchived": False},
            {"Id": "c3", "CertificationTypeName": "H2S Awareness", "WorkerId": "w2",
             "Acquired": "2024-02-01", "Expires": "2027-02-01", "IsArchived": False},
            {"Id": "c4", "CertificationTypeName": "Forklift Operator", "WorkerId": "w2",
             "Acquired": "2023-09-01", "Expires": "2026-09-01", "IsArchived": False},
            {"Id": "c5", "CertificationTypeName": "H2S Awareness", "WorkerId": "w3",
             "Acquired": "2024-06-15", "Expires": "2026-06-15", "IsArchived": False},
            {"Id": "c6", "CertificationTypeName": "Rigging & Signaling", "WorkerId": "w3",
             "Acquired": "2024-06-15", "Expires": "2027-06-15", "IsArchived": False},
            {"Id": "c7", "CertificationTypeName": "H2S Awareness", "WorkerId": "w5",
             "Acquired": "2024-03-01", "Expires": "2026-03-01", "IsArchived": False},
            {"Id": "c8", "CertificationTypeName": "Confined Space Entry", "WorkerId": "w5",
             "Acquired": "2024-03-01", "Expires": "2027-03-01", "IsArchived": False},
            {"Id": "c9", "CertificationTypeName": "H2S Awareness", "WorkerId": "w4",
             "Acquired": "2024-05-01", "Expires": "2027-05-01", "IsArchived": False},
            {"Id": "c10", "CertificationTypeName": "First Aid / CPR", "WorkerId": "w4",
             "Acquired": "2024-02-01", "Expires": "2027-02-01", "IsArchived": False},
            {"Id": "c11", "CertificationTypeName": "Forklift Operator", "WorkerId": "w4",
             "Acquired": "2023-10-01", "Expires": "2026-10-01", "IsArchived": False},
        ]

    def _stub_forms(self) -> list[dict[str, Any]]:
        return [
            {"Id": "jsa1", "Label": "Evaporator maintenance — Lot 7",
             "CreatedOn": "2026-01-10", "CreatedBy": "w1",
             "_FormTypeName": "JSA Safe Work Permit", "IsDeleted": False},
            {"Id": "jsa2", "Label": "Frac pump pressure test",
             "CreatedOn": "2026-03-10", "CreatedBy": "w5",
             "_FormTypeName": "JSA Safe Work Permit", "IsDeleted": False},
            {"Id": "jsa3", "Label": "Chemical unloading — HCl",
             "CreatedOn": "2026-04-08", "CreatedBy": "w3",
             "_FormTypeName": "JSA Safe Work Permit", "IsDeleted": False},
            {"Id": "jsa4", "Label": "Routine wellhead inspection",
             "CreatedOn": "2026-05-20", "CreatedBy": "w4",
             "_FormTypeName": "JSA Safe Work Permit", "IsDeleted": False},
        ]

    def _stub_locations(self) -> list[dict[str, Any]]:
        return [
            {"Id": "loc1", "Name": "Evaporator Lot 7", "Description": "Pad",
             "Address": "Vernal, UT", "StartDate": "2022-01-01", "IsArchived": False},
            {"Id": "loc2", "Name": "Frac Pond Alpha", "Description": "Pond",
             "Address": "Jensen, UT", "StartDate": "2022-06-01", "IsArchived": False},
            {"Id": "loc3", "Name": "Tomball Shop", "Description": "Shop",
             "Address": "Tomball, TX", "StartDate": "2020-03-01", "IsArchived": False},
            {"Id": "loc4", "Name": "Cheyenne Yard", "Description": "Yard",
             "Address": "Cheyenne, WY", "StartDate": "2023-01-01", "IsArchived": False},
            {"Id": "loc5", "Name": "West Region Office", "Description": "Office",
             "Address": "Midland, TX", "StartDate": "2021-05-01", "IsArchived": False},
        ]

    def _stub_company_types(self) -> list[dict[str, Any]]:
        return [
            {"Id": "ct1", "Name": "Prime Contractor", "Description": "Direct EWS employees"},
            {"Id": "ct2", "Name": "Subcontractor", "Description": "Third-party contractor"},
            {"Id": "ct3", "Name": "Supplier", "Description": "Equipment/material supplier"},
        ]

    def _stub_certification_types(self) -> list[dict[str, Any]]:
        return [
            {"Id": "cty1", "Name": "H2S Awareness", "Description": "H2S safety training"},
            {"Id": "cty2", "Name": "Confined Space Entry", "Description": "Confined space training"},
            {"Id": "cty3", "Name": "Forklift Operator", "Description": "Forklift certification"},
            {"Id": "cty4", "Name": "First Aid / CPR", "Description": "First aid & CPR training"},
            {"Id": "cty5", "Name": "Rigging & Signaling", "Description": "Rigging safety"},
            {"Id": "cty6", "Name": "Fire Watch", "Description": "Fire watch training"},
            {"Id": "cty7", "Name": "Fall Protection", "Description": "Fall arrest training"},
        ]

    def _stub_form_types(self) -> list[dict[str, Any]]:
        return [
            {"Id": "ft1", "Name": "JSA Safe Work Permit", "Description": "Job Safety Analysis"},
            {"Id": "ft2", "Name": "Pre-Start Safety Review", "Description": "Equipment pre-start check"},
            {"Id": "ft3", "Name": "Incident Report", "Description": "Incident documentation"},
            {"Id": "ft4", "Name": "Equipment Inspection", "Description": "Daily equipment inspection"},
            {"Id": "ft5", "Name": "Tailgate Safety Meeting", "Description": "Daily safety briefing"},
        ]

    def _stub_signatures(self) -> list[dict[str, Any]]:
        return [
            {"Id": "sig1", "FormId": "jsa1", "WorkerId": "w1", "SignedOn": "2026-01-10T08:30:00", "SignatureType": "Electronic"},
            {"Id": "sig2", "FormId": "jsa1", "WorkerId": "w2", "SignedOn": "2026-01-10T08:32:00", "SignatureType": "Electronic"},
            {"Id": "sig3", "FormId": "jsa2", "WorkerId": "w5", "SignedOn": "2026-03-10T07:45:00", "SignatureType": "Electronic"},
            {"Id": "sig4", "FormId": "jsa2", "WorkerId": "w1", "SignedOn": "2026-03-10T07:50:00", "SignatureType": "Electronic"},
            {"Id": "sig5", "FormId": "jsa3", "WorkerId": "w3", "SignedOn": "2026-04-08T09:15:00", "SignatureType": "Electronic"},
            {"Id": "sig6", "FormId": "jsa3", "WorkerId": "w2", "SignedOn": "2026-04-08T09:20:00", "SignatureType": "Electronic"},
            {"Id": "sig7", "FormId": "jsa4", "WorkerId": "w4", "SignedOn": "2026-05-20T08:00:00", "SignatureType": "Electronic"},
            {"Id": "sig8", "FormId": "jsa4", "WorkerId": "w1", "SignedOn": "2026-05-20T08:05:00", "SignatureType": "Electronic"},
        ]

    def _stub_schedules(self) -> list[dict[str, Any]]:
        from datetime import datetime, timedelta
        base = datetime.now()
        return [
            {"id": "sch1", "formTypeName": "JSA Safe Work Permit", "locationName": "Evaporator Lot 7",
             "responsibleEmployeeName": "Juan Martinez", "status": "Completed",
             "formDueOn": (base - timedelta(days=2)).isoformat()},
            {"id": "sch2", "formTypeName": "Equipment Inspection", "locationName": "Frac Pond Alpha",
             "responsibleEmployeeName": "Sarah Chen", "status": "Completed",
             "formDueOn": (base - timedelta(days=1)).isoformat()},
            {"id": "sch3", "formTypeName": "Pre-Start Safety Review", "locationName": "Tomball Shop",
             "responsibleEmployeeName": "Mike Gonzalez", "status": "Late",
             "formDueOn": (base - timedelta(days=5)).isoformat()},
            {"id": "sch4", "formTypeName": "JSA Safe Work Permit", "locationName": "Cheyenne Yard",
             "responsibleEmployeeName": "Lisa Patel", "status": "Scheduled",
             "formDueOn": (base + timedelta(days=1)).isoformat()},
            {"id": "sch5", "formTypeName": "Tailgate Safety Meeting", "locationName": "West Region Office",
             "responsibleEmployeeName": "Tom Rodriguez", "status": "Overdue",
             "formDueOn": (base - timedelta(days=14)).isoformat()},
            {"id": "sch6", "formTypeName": "Equipment Inspection", "locationName": "Tomball Shop",
             "responsibleEmployeeName": "Jared Barrett", "status": "Completed",
             "formDueOn": (base - timedelta(days=0)).isoformat()},
        ]

    # ------------------------------------------------------------------ #
    # Orchestrated fetch
    # ------------------------------------------------------------------ #

    def fetch_all(self) -> list[DataSheet]:
        """Pull all configured SiteDocs datasets and return as DataSheet list."""
        sheets: list[DataSheet] = []

        dataset_map: dict[str, tuple] = {
            "workers": (self.fetch_workers, "workers"),
            "equipment": (self.fetch_equipment, "equipment"),
            "incidents": (self.fetch_incidents, "incidents"),
            "certifications": (self.fetch_certifications, "certifications"),
            "forms": (self.fetch_forms_and_types, "forms"),
            "locations": (self.fetch_locations, "locations"),
            "companytypes": (self.fetch_company_types, "companytypes"),
            "certificationtypes": (self.fetch_certification_types, "certificationtypes"),
            "formtypes": (self.fetch_form_types, "formtypes"),
            "signatures": (self.fetch_signatures, "signatures"),
            "schedules": (self.fetch_schedules, "schedules"),
        }

        for definition in settings.datasets():
            name = definition["name"]
            if name not in dataset_map:
                logger.warning("Unknown dataset %s — skipping", name)
                continue
            fetcher, sheet_name = dataset_map[name]
            try:
                rows = fetcher()
                sheets.append(
                    DataSheet(
                        dataset=name,
                        sheet=sheet_name,
                        rows=rows,
                        metadata={"dataset": name, "row_count": len(rows)},
                    )
                )
                logger.info("✓ %s: %d rows", name, len(rows))
            except Exception as exc:
                logger.error("✗ %s fetch failed: %s", name, exc)
                raise

        return sheets
