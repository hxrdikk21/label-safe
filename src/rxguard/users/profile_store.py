"""
Clinical profile persistence (checklist Task 10.1).

``SqlProfileStore`` stores a user's active regimen, allergies and conditions in
the canonical PostgreSQL tables (``user_active_medications``, ``user_allergies``,
``user_conditions``); ``InMemoryProfileStore`` wraps the in-process
``UserService`` for tests and offline runs. Both return the shared
``UserContext`` contract, so the safety engine and chatbot are unaffected.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.rxguard.core.contracts.user_context import (
    DoctorRecord,
    HospitalRecord,
    MedicalVisitRecord,
    PrescriptionRecord,
    UserAllergyRecord,
    UserConditionRecord,
    UserContext,
)
from src.rxguard.database.models import (
    User,
    UserActiveMedication,
    UserAllergy,
    UserCondition,
    UserDoctor,
    UserHospital,
    UserMedicalVisit,
    UserPrescription,
)
from src.rxguard.users.service import UserService


class ProfileStore(Protocol):
    async def get(self, user_id: str) -> UserContext | None: ...

    async def save(self, context: UserContext) -> UserContext:
        """Replaces the stored profile with ``context``."""
        ...

    async def delete(self, user_id: str) -> bool: ...


class InMemoryProfileStore:
    def __init__(self, service: UserService) -> None:
        self._service = service

    async def get(self, user_id: str) -> UserContext | None:
        return self._service.get_user_context(user_id)

    async def save(self, context: UserContext) -> UserContext:
        self._service.clear_clinical_profile(context.user_id)
        stored = self._service.get_or_create_user(context.user_id, roles=list(context.roles))
        for medication in context.active_medications:
            self._service.add_active_medication(context.user_id, medication)
        for allergy in context.allergies:
            self._service.add_allergy_record(context.user_id, allergy)
        for condition in context.conditions:
            self._service.add_condition_record(context.user_id, condition)
        stored.hospitals = list(context.hospitals)
        stored.doctors = list(context.doctors)
        stored.medical_visits = list(context.medical_visits)
        stored.prescriptions = list(context.prescriptions)
        stored.emergency_contacts_enabled = context.emergency_contacts_enabled
        return stored

    async def delete(self, user_id: str) -> bool:
        return self._service.clear_clinical_profile(user_id)


class SqlProfileStore:
    """Profiles keyed by the ``users.user_id`` UUID issued at registration."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @staticmethod
    def _uuid(user_id: str) -> uuid.UUID | None:
        try:
            return uuid.UUID(user_id)
        except ValueError:
            return None

    async def get(self, user_id: str) -> UserContext | None:
        uid = self._uuid(user_id)
        if uid is None:
            return None
        async with self._session_factory() as session:
            user = await session.get(User, uid)
            if user is None:
                return None
            meds = await session.scalars(
                select(UserActiveMedication.medication)
                .where(UserActiveMedication.user_id == uid)
                .order_by(UserActiveMedication.added_at, UserActiveMedication.medication)
            )
            allergies = await session.scalars(
                select(UserAllergy).where(UserAllergy.user_id == uid).order_by(UserAllergy.created_at)
            )
            conditions = await session.scalars(
                select(UserCondition).where(UserCondition.user_id == uid).order_by(UserCondition.created_at)
            )
            hospitals = await session.scalars(
                select(UserHospital).where(UserHospital.user_id == uid).order_by(UserHospital.created_at)
            )
            doctors = await session.scalars(
                select(UserDoctor).where(UserDoctor.user_id == uid).order_by(UserDoctor.created_at)
            )
            visits = await session.scalars(
                select(UserMedicalVisit)
                .where(UserMedicalVisit.user_id == uid)
                .order_by(UserMedicalVisit.created_at)
            )
            prescriptions = await session.scalars(
                select(UserPrescription)
                .where(UserPrescription.user_id == uid)
                .order_by(UserPrescription.created_at)
            )
            return UserContext(
                user_id=user_id,
                roles=[user.role],
                active_medications=list(meds),
                allergies=[
                    UserAllergyRecord(
                        allergy_id=str(a.allergy_id),
                        substance_name=a.substance_name,
                        unii=a.unii,
                        allergy_class=a.allergy_class,
                        severity=a.severity,
                        verification_source=a.verification_source,
                    )
                    for a in allergies
                ],
                conditions=[
                    UserConditionRecord(
                        condition_id=str(c.condition_id),
                        condition_name=c.condition_name,
                        icd10_code=c.icd10_code,
                        diagnosed_date=c.diagnosed_date,
                    )
                    for c in conditions
                ],
                hospitals=[
                    HospitalRecord(
                        hospital_id=str(h.hospital_id),
                        name=h.name,
                        department=h.department,
                        address=h.address,
                        phone=h.phone,
                    )
                    for h in hospitals
                ],
                doctors=[
                    DoctorRecord(
                        doctor_id=str(d.doctor_id),
                        name=d.name,
                        specialty=d.specialty,
                        hospital_affiliation=d.hospital_affiliation,
                        contact_phone=d.contact_phone,
                    )
                    for d in doctors
                ],
                medical_visits=[
                    MedicalVisitRecord(
                        visit_id=str(v.visit_id),
                        visit_date=v.visit_date,
                        hospital_name=v.hospital_name,
                        doctor_name=v.doctor_name,
                        reason_for_visit=v.reason_for_visit,
                        clinical_notes=v.clinical_notes,
                    )
                    for v in visits
                ],
                prescriptions=[
                    PrescriptionRecord(
                        prescription_id=str(p.prescription_id),
                        medication_name=p.medication_name,
                        dosage=p.dosage,
                        prescribed_by=p.prescribed_by,
                        prescribed_date=p.prescribed_date,
                        status=p.status,
                        instructions=p.instructions,
                    )
                    for p in prescriptions
                ],
            )

    async def save(self, context: UserContext) -> UserContext:
        uid = self._uuid(context.user_id)
        if uid is None:
            raise ValueError(f"Unknown user id {context.user_id!r}")
        async with self._session_factory() as session, session.begin():
            if await session.get(User, uid) is None:
                raise ValueError(f"Unknown user id {context.user_id!r}")
            for model in (
                UserActiveMedication,
                UserAllergy,
                UserCondition,
                UserHospital,
                UserDoctor,
                UserMedicalVisit,
                UserPrescription,
            ):
                await session.execute(delete(model).where(model.user_id == uid))
            session.add_all(
                UserActiveMedication(user_id=uid, medication=m)
                for m in dict.fromkeys(context.active_medications)
            )
            session.add_all(
                UserAllergy(
                    user_id=uid,
                    substance_name=a.substance_name,
                    unii=a.unii,
                    allergy_class=a.allergy_class,
                    severity=a.severity,
                    verification_source=a.verification_source,
                )
                for a in context.allergies
            )
            session.add_all(
                UserCondition(
                    user_id=uid,
                    condition_name=c.condition_name,
                    icd10_code=c.icd10_code,
                    diagnosed_date=c.diagnosed_date,
                )
                for c in context.conditions
            )
            session.add_all(
                UserHospital(
                    user_id=uid,
                    name=h.name,
                    department=h.department,
                    address=h.address,
                    phone=h.phone,
                )
                for h in context.hospitals
            )
            session.add_all(
                UserDoctor(
                    user_id=uid,
                    name=d.name,
                    specialty=d.specialty,
                    hospital_affiliation=d.hospital_affiliation,
                    contact_phone=d.contact_phone,
                )
                for d in context.doctors
            )
            session.add_all(
                UserMedicalVisit(
                    user_id=uid,
                    visit_date=v.visit_date,
                    hospital_name=v.hospital_name,
                    doctor_name=v.doctor_name,
                    reason_for_visit=v.reason_for_visit,
                    clinical_notes=v.clinical_notes,
                )
                for v in context.medical_visits
            )
            session.add_all(
                UserPrescription(
                    user_id=uid,
                    medication_name=p.medication_name,
                    dosage=p.dosage,
                    prescribed_by=p.prescribed_by,
                    prescribed_date=p.prescribed_date,
                    status=p.status,
                    instructions=p.instructions,
                )
                for p in context.prescriptions
            )
        stored = await self.get(context.user_id)
        if stored is None:
            raise RuntimeError(f"Profile for {context.user_id!r} vanished after save")
        return stored

    async def delete(self, user_id: str) -> bool:
        uid = self._uuid(user_id)
        if uid is None:
            return False
        async with self._session_factory() as session, session.begin():
            removed = 0
            for model in (
                UserActiveMedication,
                UserAllergy,
                UserCondition,
                UserHospital,
                UserDoctor,
                UserMedicalVisit,
                UserPrescription,
            ):
                result = await session.execute(delete(model).where(model.user_id == uid))
                removed += int(getattr(result, "rowcount", 0) or 0)
            return removed > 0
