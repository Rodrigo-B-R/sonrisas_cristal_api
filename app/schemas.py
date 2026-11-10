"""What goes in and what comes out of the API (Pydantic).

JSON uses camelCase (stayId would be daycareId, startTime, clockInAt...). Python uses snake_case.
Requests reject unknown fields (extra="forbid"), so nobody can slip in a field like "roleId".
"""

import re
from datetime import date as Date
from datetime import datetime, time, timezone
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    PlainSerializer,
    field_validator,
)
from pydantic.alias_generators import to_camel

from app.constants import (
    ATTENDANCE_FROM_DB,
    CORRECTION_FROM_DB,
    MOVEMENT_FROM_DB,
    NOTICE_TYPE_FROM_DB,
    ROLE_FROM_DB,
    SOURCE_FROM_DB,
    WEEKDAY_FROM_DB,
)

# ── Types ────────────────────────────────────────────────────────────


def _iso_utc(value: datetime) -> str:
    """2026-11-04T13:05:00.000Z"""
    utc = value.astimezone(timezone.utc)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}Z"


UtcTimestamp = Annotated[datetime, PlainSerializer(_iso_utc, return_type=str)]
ShortTime = Annotated[time, PlainSerializer(lambda value: value.strftime("%H:%M"), return_type=str)]


def _parse_hhmm(value):
    if isinstance(value, time):
        return value
    if not isinstance(value, str) or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value):
        raise ValueError("Times must be HH:MM")
    return time(int(value[:2]), int(value[3:]))


HHMM = Annotated[time, BeforeValidator(_parse_hhmm)]

RoleName = Literal["employee", "manager", "director"]
AttendanceStatus = Literal["present", "late", "absent", "incident"]
NoticeType = Literal["schedule_change", "meeting", "reminder", "urgent"]
NoticeTarget = Literal["all", "shift", "room", "people"]
Weekday = Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
CorrectionStatus = Literal["pending", "approved", "rejected"]
MovementType = Literal["hire", "termination", "transfer"]

Name = Annotated[str, Field(min_length=1, max_length=255)]
Id = Annotated[int, Field(ge=1)]


# ── Base classes ─────────────────────────────────────────────────────


class Out(BaseModel):
    """Responses. They read ORM objects and dicts, and never include a password."""

    model_config = ConfigDict(alias_generator=to_camel, validate_by_name=True, validate_by_alias=True, from_attributes=True)


class In(BaseModel):
    """Requests: camelCase only, no unknown fields, no stray spaces."""

    model_config = ConfigDict(alias_generator=to_camel, extra="forbid", str_strip_whitespace=True)


def _translate(mapping: dict):
    """Validator that turns a database value (Spanish) into the API value (English)."""
    return lambda value: mapping.get(value, value)


# ── Shared pieces ────────────────────────────────────────────────────


class NameRef(Out):
    id: int
    name: str


class MessageOut(Out):
    message: str


class TemporaryPasswordOut(Out):
    temporary_password: str


class RoleOut(Out):
    id: int
    name: str

    _name = field_validator("name", mode="before")(_translate(ROLE_FROM_DB))


class PositionOut(Out):
    id: int
    name: str


class TerminationReasonOut(Out):
    id: int
    name: str


class AbsenceReasonOut(Out):
    id: int
    description: str


class ShiftOut(Out):
    id: int
    name: str
    start_time: ShortTime
    end_time: ShortTime


class LocationOut(Out):
    id: int
    name: str
    latitude: float
    longitude: float
    radius_meters: int


class RoomOut(Out):
    id: int
    name: str
    min_staff: int
    daycare_id: int


class DaycareBasicOut(Out):
    id: int
    name: str
    location_id: int


class DaycareOut(DaycareBasicOut):
    location: LocationOut
    rooms: list[RoomOut]


class UserOut(Out):
    id: int
    name: str
    username: str
    email: str
    phone: str
    is_active: bool
    role_id: int
    position_id: int
    daycare_id: int
    role: RoleOut
    position: PositionOut
    daycare: DaycareBasicOut


class ProfileOut(UserOut):
    daycare: DaycareOut


# ── Session ──────────────────────────────────────────────────────────


class LoginIn(In):
    username: Annotated[str, Field(min_length=1, max_length=255)]
    password: Annotated[str, Field(min_length=1, max_length=256)]


class LoginUser(Out):
    id: int
    name: str
    daycare_id: int


class LoginOut(Out):
    token: str
    token_type: str = "bearer"
    expires_in: int
    role: RoleName
    user: LoginUser


class PasswordChangeIn(In):
    current_password: Annotated[str, Field(min_length=1, max_length=256)]
    new_password: Annotated[str, Field(min_length=1, max_length=256)]


# ── Catalogs ─────────────────────────────────────────────────────────


class CatalogsOut(Out):
    roles: list[RoleOut]
    positions: list[PositionOut]
    shifts: list[ShiftOut]
    termination_reasons: list[TerminationReasonOut]
    absence_reasons: list[AbsenceReasonOut]


class NameIn(In):
    name: Name


class AbsenceReasonIn(In):
    description: Name


class ShiftUpdateIn(In):
    name: Name | None = None
    start_time: HHMM | None = None
    end_time: HHMM | None = None


# ── Daycares and rooms ───────────────────────────────────────────────

Latitude = Annotated[float, Field(ge=-90, le=90)]
Longitude = Annotated[float, Field(ge=-180, le=180)]
Radius = Annotated[int, Field(ge=0)]


class DaycareIn(In):
    name: Name
    latitude: Latitude
    longitude: Longitude
    radius_meters: Radius = 150


class DaycareUpdateIn(In):
    name: Name | None = None
    latitude: Latitude | None = None
    longitude: Longitude | None = None
    radius_meters: Radius | None = None


class RoomIn(In):
    name: Name
    min_staff: Annotated[int, Field(ge=0)]


class RoomUpdateIn(In):
    name: Name | None = None
    min_staff: Annotated[int, Field(ge=0)] | None = None


# ── Schedules ────────────────────────────────────────────────────────


class ScheduleDayOut(Out):
    id: int
    weekday: str
    schedule_id: int
    shift_id: int
    room_id: int
    shift: ShiftOut
    room: RoomOut

    _weekday = field_validator("weekday", mode="before")(_translate(WEEKDAY_FROM_DB))


class ScheduleOut(Out):
    id: int
    user_id: int
    valid_from: Date
    valid_until: Date
    days: list[ScheduleDayOut]


class PersonBrief(Out):
    id: int
    name: str
    position: PositionOut


class PersonScheduleOut(Out):
    person: PersonBrief
    schedule: ScheduleOut | None


class ScheduleDayIn(In):
    day: Weekday
    shift_id: Id
    room_id: Id


class ScheduleIn(In):
    valid_from: Date | None = None
    days: list[ScheduleDayIn]


# ── Staff and movements ──────────────────────────────────────────────


class MovementOut(Out):
    id: int
    type: str
    date: Date
    notes: str | None
    user_id: int
    done_by_id: int
    termination_reason_id: int | None
    origin_daycare_id: int | None
    destination_daycare_id: int | None
    termination_reason: TerminationReasonOut | None

    _type = field_validator("type", mode="before")(_translate(MOVEMENT_FROM_DB))


class MovementDetailOut(MovementOut):
    user: NameRef
    done_by: NameRef
    origin_daycare: NameRef | None
    destination_daycare: NameRef | None


class StaffDetailOut(UserOut):
    movements: list[MovementOut]
    current_schedule: ScheduleOut | None


class StaffCreatedOut(UserOut):
    temporary_password: str


class StaffCreateIn(In):
    name: Name
    username: Name
    email: EmailStr
    phone: Name
    position_id: Id
    password: Annotated[str, Field(min_length=1, max_length=256)] | None = None
    hire_date: Date | None = None
    # Only a director can send these two. A manager always creates employees in their own daycare.
    role: RoleName | None = None
    daycare_id: Id | None = None


class StaffUpdateIn(In):
    name: Name | None = None
    username: Name | None = None
    email: EmailStr | None = None
    phone: Name | None = None
    position_id: Id | None = None
    role: RoleName | None = None  # only a director


class TerminateIn(In):
    termination_reason_id: Id
    date: Date | None = None
    notes: Annotated[str, Field(max_length=255)] | None = None


class TransferIn(In):
    daycare_id: Id
    date: Date | None = None
    notes: Annotated[str, Field(max_length=255)] | None = None


# ── Time records ─────────────────────────────────────────────────────


class TimeRecordOut(Out):
    id: int
    uuid: UUID
    clock_in_at: UtcTimestamp
    clock_out_at: UtcTimestamp | None
    source: str
    within_zone: bool
    user_id: int
    recorded_by_id: int
    location_id: int
    room_id: int
    shift_id: int
    room: RoomOut
    shift: ShiftOut
    user: NameRef

    _source = field_validator("source", mode="before")(_translate(SOURCE_FROM_DB))


class AttendanceOut(Out):
    id: int
    date: Date
    status: str
    absence_reason_id: int | None
    user_id: int
    recorded_by_id: int
    daycare_id: int
    absence_reason: AbsenceReasonOut | None

    _status = field_validator("status", mode="before")(_translate(ATTENDANCE_FROM_DB))


class ClockInOut(Out):
    record: TimeRecordOut
    attendance: AttendanceOut | None = None
    repeated: bool = False  # true when the phone re-sent a clock-in we already had


class ClockStatusOut(Out):
    inside: bool
    open_record: TimeRecordOut | None
    today_shifts: list[ScheduleDayOut]
    location: LocationOut


class SkippedOut(Out):
    user_id: int
    reason: str


class BatchOut(Out):
    recorded: list[TimeRecordOut]
    skipped: list[SkippedOut]


class ClockInIn(In):
    uuid: UUID | None = None  # made by the phone; sending the same one twice never duplicates
    occurred_at: datetime | None = None  # a clock-in made offline that arrives later
    latitude: Latitude | None = None
    longitude: Longitude | None = None
    within_zone: bool | None = None  # used only when latitude and longitude are not sent
    room_id: Id | None = None
    shift_id: Id | None = None


class ClockOutIn(In):
    occurred_at: datetime | None = None


class BatchIn(In):
    user_ids: Annotated[list[Id], Field(min_length=1, max_length=200)]
    occurred_at: datetime | None = None
    room_id: Id | None = None
    shift_id: Id | None = None


class RecordFixIn(In):
    """The manager fixes a record directly. "clockOutAt": null removes the clock-out."""

    clock_in_at: datetime | None = None
    clock_out_at: datetime | None = None
    reason: Annotated[str, Field(max_length=255)] | None = None


# ── Corrections ──────────────────────────────────────────────────────


class CorrectionOut(Out):
    id: int
    record_id: int
    requested_by_id: int
    previous_clock_in: UtcTimestamp
    proposed_clock_in: UtcTimestamp
    previous_clock_out: UtcTimestamp | None
    proposed_clock_out: UtcTimestamp | None
    reason: str
    status: str
    resolved_by_id: int | None
    resolved_at: UtcTimestamp | None
    created_at: UtcTimestamp
    record: TimeRecordOut
    requested_by: NameRef
    resolved_by: NameRef | None

    _status = field_validator("status", mode="before")(_translate(CORRECTION_FROM_DB))


class CorrectionIn(In):
    record_id: Id
    clock_in_at: datetime | None = None
    clock_out_at: datetime | None = None
    reason: Annotated[str, Field(min_length=1, max_length=255)]


# ── Attendance ───────────────────────────────────────────────────────


class AttendanceIn(In):
    user_id: Id
    date: Date
    status: AttendanceStatus
    absence_reason_id: Id | None = None
    absence_reason: Name | None = None  # the description, as an alternative to the id


class AttendanceUpdateIn(In):
    status: AttendanceStatus | None = None
    absence_reason_id: Id | None = None
    absence_reason: Name | None = None


class DayShiftOut(Out):
    shift_id: int
    shift: str
    start_time: str
    end_time: str
    room: NameRef


class AttendanceDayOut(Out):
    Date: Date
    shifts: list[DayShiftOut]
    clock_in: str | None
    clock_out: str | None
    within_zone: bool
    status: str
    reason: str | None
    reason_id: int | None
    attendance_id: int | None
    late_minutes: int


class AttendanceSummaryOut(Out):
    worked_days: int
    lates: int
    absences: int
    incidents: int


class PersonAttendanceOut(Out):
    person: UserOut
    summary: AttendanceSummaryOut
    days: list[AttendanceDayOut]


class SinglePersonAttendanceOut(PersonAttendanceOut):
    start_date: Date
    end_date: Date


# ── Notices ──────────────────────────────────────────────────────────


class NoticeAuthorOut(Out):
    id: int
    name: str
    daycare_id: int


class NoticeBaseOut(Out):
    id: int
    subject: str
    notice_type: str
    message: str
    requires_confirmation: bool
    author_id: int
    daycare_id: int | None  # null = a general notice, for every daycare
    author: NoticeAuthorOut

    _notice_type = field_validator("notice_type", mode="before")(_translate(NOTICE_TYPE_FROM_DB))


class EmployeeNoticeOut(NoticeBaseOut):
    read: bool
    read_at: UtcTimestamp | None


class ManagerNoticeOut(NoticeBaseOut):
    recipient_count: int
    confirmed_count: int
    read: bool | None = None  # only when the person asking also received it
    read_at: UtcTimestamp | None = None


class ConfirmedRef(NameRef):
    read_at: UtcTimestamp | None


class NoticeDetailOut(NoticeBaseOut):
    recipient_count: int
    confirmed: list[ConfirmedRef]
    pending: list[NameRef]


class ReadReceiptOut(Out):
    notice_id: int
    read: bool
    read_at: UtcTimestamp | None


class NoticeIn(In):
    subject: Annotated[str, Field(min_length=1, max_length=255)]
    message: Annotated[str, Field(min_length=1, max_length=255)]
    notice_type: NoticeType
    target: NoticeTarget = "all"
    shift_id: Id | None = None
    room_id: Id | None = None
    user_ids: Annotated[list[Id], Field(min_length=1, max_length=500)] | None = None
    requires_confirmation: bool = False
    # Only for a director: a daycare, or nothing for a general notice. A manager always writes to their own.
    daycare_id: Id | None = None


# ── Audit ────────────────────────────────────────────────────────────


class AuditOut(Out):
    id: int
    user_id: int | None
    action: str
    table: str
    record_id: int
    previous_data: dict | None
    new_data: dict | None
    created_at: UtcTimestamp
    user: NameRef | None


# ── Reports ──────────────────────────────────────────────────────────


class CoverageShiftOut(Out):
    shift_id: int
    shift: str
    scheduled: int
    present: int
    started: bool
    uncovered: bool
    missing: int
    below_minimum: bool


class CoverageRoomOut(Out):
    room: NameRef
    minimum: int
    shifts: list[CoverageShiftOut]


class CoverageOut(Out):
    daycare: NameRef
    date: Date
    present: int
    scheduled: int
    pending: int
    complete: bool
    alerts: list[str]
    rooms: list[CoverageRoomOut]


class SummaryDaycareOut(Out):
    id: int
    name: str
    complete: bool
    alerts: list[str]
    present: int
    scheduled: int


class SummaryOut(Out):
    Date: Date
    complete_count: int
    understaffed_count: int
    daycares: list[SummaryDaycareOut]


class DaycareStatisticsOut(Out):
    daycare: NameRef
    hires: int
    terminations: int
    transfers_in: int
    transfers_out: int
    understaffed_days: int
    absences: int
    lates: int
    scheduled_days: int


class StatisticsOut(Out):
    start_date: Date
    end_date: Date
    hires: int
    terminations: int
    absences: int
    lates: int
    understaffed_days: int
    absenteeism: float  # percent, one decimal
    by_daycare: list[DaycareStatisticsOut]
