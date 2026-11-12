"""Values the API speaks (English) and the values stored in the database (Spanish).

The database has CHECK constraints on these columns (see sonrisas_cristal_db/init/01-init.sql),
so what is stored stays in Spanish. The API translates at its edge: anything that comes in
is English, anything that goes out is English. Never compare an API value with a DB value.
"""

from datetime import date

# ── Roles ────────────────────────────────────────────────────────────
ROLE_TO_DB = {"employee": "empleada", "manager": "responsable", "director": "direccion"}
ROLE_FROM_DB = {db: api for api, db in ROLE_TO_DB.items()}

# ── Attendance status stored in the database ─────────────────────────
ATTENDANCE_TO_DB = {"present": "presente", "late": "retardo", "absent": "falta", "incident": "incidencia"}
ATTENDANCE_FROM_DB = {db: api for api, db in ATTENDANCE_TO_DB.items()}

# Statuses that only exist in reports (they are computed, never stored):
#   no_record        had a shift and nobody recorded anything
#   pending          today, has a shift and has not arrived yet
#   day_off          no shift
#   outside_schedule clocked in without a shift
#   scheduled        a future day with a shift

# ── Notices ──────────────────────────────────────────────────────────
NOTICE_TYPE_TO_DB = {
    "schedule_change": "cambio_horario",
    "meeting": "reunion",
    "reminder": "recordatorio",
    "urgent": "urgente",
}
NOTICE_TYPE_FROM_DB = {db: api for api, db in NOTICE_TYPE_TO_DB.items()}

# ── Staff movements ──────────────────────────────────────────────────
MOVEMENT_TO_DB = {"hire": "alta", "termination": "baja", "transfer": "traslado"}
MOVEMENT_FROM_DB = {db: api for api, db in MOVEMENT_TO_DB.items()}

# ── Time record source ───────────────────────────────────────────────
SOURCE_TO_DB = {"app": "app", "manager": "responsable"}
SOURCE_FROM_DB = {db: api for api, db in SOURCE_TO_DB.items()}

# ── Weekdays (Monday is index 0, like date.weekday()) ────────────────
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
WEEKDAYS_DB = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
WEEKDAY_TO_DB = dict(zip(WEEKDAYS, WEEKDAYS_DB))
WEEKDAY_FROM_DB = dict(zip(WEEKDAYS_DB, WEEKDAYS))

# ── Audit ────────────────────────────────────────────────────────────
# Tables the database triggers write to the audit log for.
AUDITED_TABLES = ["registro_entradas", "asistencia"]

# A schedule with no end date is stored until this date (valid_until does not accept NULL).
NO_END = date(2099, 12, 31)

# A client clock may be a little ahead of ours; beyond this a timestamp is "in the future".
CLOCK_SKEW_SECONDS = 5 * 60
