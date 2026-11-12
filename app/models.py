"""Database tables, described for SQLAlchemy.

The tables are created by sonrisas_cristal_db/init/01-init.sql (see scripts/create_tables.py),
not by SQLAlchemy. Here they only get English names: the first argument of mapped_column is the
real column name in PostgreSQL.
"""

import datetime as dt
import uuid as uuid_lib

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Time,
    TypeDecorator,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.constants import ROLE_FROM_DB
from app.database import Base

# BIGINT in PostgreSQL. SQLite (used in tests) only auto-increments a plain INTEGER key.
BigId = BigInteger().with_variant(Integer(), "sqlite")


class UTCDateTime(TypeDecorator):
    """timestamptz that always comes back as an aware UTC datetime (also on SQLite)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt.timezone.utc)
        return value.astimezone(dt.timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=dt.timezone.utc)
        return value.astimezone(dt.timezone.utc)


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# ── Catalogs ─────────────────────────────────────────────────────────


class Role(Base):
    __tablename__ = "rol"

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    name: Mapped[str] = mapped_column("nombre", String(255))  # stored in Spanish, see constants.py


class Position(Base):
    __tablename__ = "puesto"

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    name: Mapped[str] = mapped_column("nombre", String(255))


class TerminationReason(Base):
    __tablename__ = "causa_baja"

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    name: Mapped[str] = mapped_column("nombre", String(255))


class AbsenceReason(Base):
    __tablename__ = "motivo_ausencia"

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    description: Mapped[str] = mapped_column("descripcion", String(255), unique=True)


class Shift(Base):
    __tablename__ = "turno"

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    name: Mapped[str] = mapped_column("nombre", String(255))
    start_time: Mapped[dt.time] = mapped_column("hora_entrada", Time)
    end_time: Mapped[dt.time] = mapped_column("hora_salida", Time)


# ── Daycares and rooms ───────────────────────────────────────────────


class Location(Base):
    """Where a daycare is. radius_meters is the circle that counts as "inside the daycare"."""

    __tablename__ = "ubicacion"

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    name: Mapped[str] = mapped_column("nombre", String(255))
    latitude: Mapped[float] = mapped_column("latitud", Float)
    longitude: Mapped[float] = mapped_column("longitud", Float)
    radius_meters: Mapped[int] = mapped_column("precision", Integer)


class Daycare(Base):
    __tablename__ = "estancia"

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    name: Mapped[str] = mapped_column("nombre", String(255))
    location_id: Mapped[int] = mapped_column("id_ubicacion", ForeignKey("ubicacion.id"))

    location: Mapped[Location] = relationship()
    rooms: Mapped[list["Room"]] = relationship(order_by="Room.id")


class Room(Base):
    __tablename__ = "sala"

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    name: Mapped[str] = mapped_column("nombre", String(255))
    min_staff: Mapped[int] = mapped_column("minimo_personal", Integer)
    daycare_id: Mapped[int] = mapped_column("id_estancia", ForeignKey("estancia.id"))


# ── People ───────────────────────────────────────────────────────────


class User(Base):
    __tablename__ = "usuario"

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    name: Mapped[str] = mapped_column("nombre", String(255))
    password_hash: Mapped[str] = mapped_column("password_hash", String(255))  # bcrypt, never the text
    username: Mapped[str] = mapped_column("usuario_login", String(255), unique=True)
    email: Mapped[str] = mapped_column("correo", String(255), unique=True)
    phone: Mapped[str] = mapped_column("celular", String(255))
    is_active: Mapped[bool] = mapped_column("esta_activo", Boolean)
    role_id: Mapped[int] = mapped_column("id_rol", ForeignKey("rol.id"))
    position_id: Mapped[int] = mapped_column("id_puesto", ForeignKey("puesto.id"))
    daycare_id: Mapped[int] = mapped_column("id_estancia", ForeignKey("estancia.id"))

    role: Mapped[Role] = relationship()
    position: Mapped[Position] = relationship()
    daycare: Mapped[Daycare] = relationship()
    schedules: Mapped[list["Schedule"]] = relationship(back_populates="user", order_by="Schedule.id")
    movements: Mapped[list["Movement"]] = relationship(
        back_populates="user",
        foreign_keys="Movement.user_id",
        order_by=lambda: (Movement.date, Movement.id),
    )

    @property
    def role_code(self) -> str:
        """employee | manager | director"""
        return ROLE_FROM_DB.get(self.role.name, self.role.name)


class Movement(Base):
    """Every hire, termination or transfer. Nothing is ever deleted: this is the history."""

    __tablename__ = "movimiento_usuario"

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    type: Mapped[str] = mapped_column("tipo", String(255))  # alta | baja | traslado
    date: Mapped[dt.date] = mapped_column("fecha", Date)
    notes: Mapped[str | None] = mapped_column("observaciones", String(255))
    user_id: Mapped[int] = mapped_column("id_usuario_del_movimiento", ForeignKey("usuario.id"))
    done_by_id: Mapped[int] = mapped_column("id_usuario_que_movio", ForeignKey("usuario.id"))
    termination_reason_id: Mapped[int | None] = mapped_column("id_causa_baja", ForeignKey("causa_baja.id"))
    origin_daycare_id: Mapped[int | None] = mapped_column("id_estancia_origen", ForeignKey("estancia.id"))
    destination_daycare_id: Mapped[int | None] = mapped_column("id_estancia_destino", ForeignKey("estancia.id"))

    user: Mapped[User] = relationship(foreign_keys=[user_id], back_populates="movements")
    done_by: Mapped[User] = relationship(foreign_keys=[done_by_id])
    termination_reason: Mapped[TerminationReason | None] = relationship()
    origin_daycare: Mapped[Daycare | None] = relationship(foreign_keys=[origin_daycare_id])
    destination_daycare: Mapped[Daycare | None] = relationship(foreign_keys=[destination_daycare_id])


# ── Notices ──────────────────────────────────────────────────────────


class Notice(Base):
    __tablename__ = "aviso"

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    subject: Mapped[str] = mapped_column("asunto", String(255))
    notice_type: Mapped[str] = mapped_column("tipo_aviso", String(255))
    message: Mapped[str] = mapped_column("mensaje", String(255))
    requires_confirmation: Mapped[bool] = mapped_column("requiere_confirmacion", Boolean, default=False)
    author_id: Mapped[int] = mapped_column("id_usuario_envia", ForeignKey("usuario.id"))
    daycare_id: Mapped[int | None] = mapped_column("id_estancia", ForeignKey("estancia.id"))  # NULL = general

    author: Mapped[User] = relationship()
    recipients: Mapped[list["NoticeRecipient"]] = relationship(back_populates="notice")


class NoticeRecipient(Base):
    __tablename__ = "aviso_usuario"

    notice_id: Mapped[int] = mapped_column("id_aviso", ForeignKey("aviso.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column("id_usuario", ForeignKey("usuario.id"), primary_key=True)
    is_read: Mapped[bool] = mapped_column("leido", Boolean, default=False)
    read_at: Mapped[dt.datetime | None] = mapped_column("leido_en", UTCDateTime)

    notice: Mapped[Notice] = relationship(back_populates="recipients")
    user: Mapped[User] = relationship()


# ── Schedules ────────────────────────────────────────────────────────


class Schedule(Base):
    """A person's week, valid between two dates. Changing it closes the old one and opens a new one."""

    __tablename__ = "horario"

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    user_id: Mapped[int] = mapped_column("id_usuario", ForeignKey("usuario.id"))
    valid_from: Mapped[dt.date] = mapped_column("vigente_desde", Date)
    valid_until: Mapped[dt.date] = mapped_column("vigente_hasta", Date)

    user: Mapped[User] = relationship(back_populates="schedules")
    days: Mapped[list["ScheduleDay"]] = relationship(back_populates="schedule", order_by="ScheduleDay.id")


class ScheduleDay(Base):
    __tablename__ = "horario_dia"
    __table_args__ = (UniqueConstraint("id_horario", "dia_de_semana", "id_turno", "id_sala", name="horario_dia_unico"),)

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    weekday: Mapped[str] = mapped_column("dia_de_semana", String(255))  # lunes ... domingo
    schedule_id: Mapped[int] = mapped_column("id_horario", ForeignKey("horario.id"))
    shift_id: Mapped[int] = mapped_column("id_turno", ForeignKey("turno.id"))
    room_id: Mapped[int] = mapped_column("id_sala", ForeignKey("sala.id"))

    schedule: Mapped[Schedule] = relationship(back_populates="days")
    shift: Mapped[Shift] = relationship()
    room: Mapped[Room] = relationship()


# ── Time records and attendance ─────────────────────────


class TimeRecord(Base):
    """One clock-in. The clock-out is filled in on the same row."""

    __tablename__ = "registro_entradas"

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    uuid: Mapped[uuid_lib.UUID] = mapped_column("uuid", Uuid, unique=True)  # made by the phone: no duplicates on retry
    clock_in_at: Mapped[dt.datetime] = mapped_column("fecha_hora_entrada", UTCDateTime)
    clock_out_at: Mapped[dt.datetime | None] = mapped_column("fecha_hora_salida", UTCDateTime)
    source: Mapped[str] = mapped_column("origen_registro", String(255))  # app | responsable
    within_zone: Mapped[bool] = mapped_column("dentro_de_zona", Boolean)
    user_id: Mapped[int] = mapped_column("id_usuario_entrada", ForeignKey("usuario.id"))
    recorded_by_id: Mapped[int] = mapped_column("id_usuario_registro", ForeignKey("usuario.id"))
    location_id: Mapped[int] = mapped_column("id_ubicacion", ForeignKey("ubicacion.id"))
    room_id: Mapped[int] = mapped_column("id_sala", ForeignKey("sala.id"))
    shift_id: Mapped[int] = mapped_column("id_turno", ForeignKey("turno.id"))

    user: Mapped[User] = relationship(foreign_keys=[user_id])
    room: Mapped[Room] = relationship()
    shift: Mapped[Shift] = relationship()


class Attendance(Base):
    __tablename__ = "asistencia"
    __table_args__ = (UniqueConstraint("id_usuario_que_asistio", "id_estancia", "fecha", name="asistencia_unica"),)

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    date: Mapped[dt.date] = mapped_column("fecha", Date)
    status: Mapped[str] = mapped_column("estado", String(255))  # presente | retardo | falta | incidencia
    absence_reason_id: Mapped[int | None] = mapped_column("id_motivo_ausencia", ForeignKey("motivo_ausencia.id"))
    user_id: Mapped[int] = mapped_column("id_usuario_que_asistio", ForeignKey("usuario.id"))
    recorded_by_id: Mapped[int] = mapped_column("id_usuario_registro", ForeignKey("usuario.id"))
    daycare_id: Mapped[int] = mapped_column("id_estancia", ForeignKey("estancia.id"))

    absence_reason: Mapped[AbsenceReason | None] = relationship()


class AuditLog(Base):
    """Filled by database triggers. The API only reads it."""

    __tablename__ = "auditoria"

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    user_id: Mapped[int | None] = mapped_column("id_usuario", ForeignKey("usuario.id"))
    action: Mapped[str] = mapped_column("accion", String(255))  # INSERT | UPDATE | DELETE
    table_name: Mapped[str] = mapped_column("tabla", String(255))
    record_id: Mapped[int] = mapped_column("id_registro", BigId)
    previous_data: Mapped[dict | None] = mapped_column("datos_anteriores", JSON)
    new_data: Mapped[dict | None] = mapped_column("datos_nuevos", JSON)
    created_at: Mapped[dt.datetime] = mapped_column("creado_en", UTCDateTime, default=_utcnow)

    user: Mapped[User | None] = relationship()
