"""Начальная схема: пользователи, справочники, помещения, обмеры, дисциплины

Этап 1 (ЛР №1). Состав сущностей — по подразделу 4.1.5 ТЗ.

Revision ID: 0001_initial
Revises: 
Создана: 2026-09-18 18:18:15.889545
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('app_user',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('username', sa.String(length=50), nullable=False),
    sa.Column('full_name', sa.String(length=150), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('role', sa.Enum('SYS_ADMIN', 'FUND_ADMIN', 'DISPATCHER', 'OBSERVER', 'SERVICE', name='user_role'), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('failed_attempts', sa.Integer(), nullable=False),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('char_length(username) >= 3', name='ck_app_user_username_len'),
    sa.CheckConstraint('failed_attempts >= 0', name='ck_app_user_attempts'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('username', name='uq_app_user_username')
    )
    op.create_table('building',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('code', sa.String(length=20), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('address', sa.String(length=300), nullable=False),
    sa.Column('floors_count', sa.SmallInteger(), nullable=False),
    sa.Column('has_basement', sa.Boolean(), nullable=False),
    sa.Column('passport_area', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('floors_count BETWEEN 1 AND 100', name='ck_building_floors'),
    sa.CheckConstraint('passport_area IS NULL OR passport_area > 0', name='ck_building_area_positive'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code', name='uq_building_code')
    )
    op.create_table('department',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('code', sa.String(length=30), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('parent_id', sa.BigInteger(), nullable=True),
    sa.Column('head_fio', sa.String(length=150), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('parent_id IS NULL OR parent_id <> id', name='ck_department_not_self_parent'),
    sa.ForeignKeyConstraint(['parent_id'], ['department.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code', name='uq_department_code')
    )
    op.create_table('discipline',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('code', sa.String(length=30), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('note', sa.String(length=300), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code', name='uq_discipline_code')
    )
    op.create_table('room_type',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('code', sa.String(length=30), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('area_norm', sa.Numeric(precision=6, scale=2), nullable=True),
    sa.Column('is_teaching', sa.Boolean(), nullable=False),
    sa.Column('note', sa.String(length=300), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('area_norm IS NULL OR area_norm > 0', name='ck_room_type_norm_positive'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code', name='uq_room_type_code')
    )
    op.create_table('discipline_room_type',
    sa.Column('discipline_id', sa.BigInteger(), nullable=False),
    sa.Column('room_type_id', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['discipline_id'], ['discipline.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['room_type_id'], ['room_type.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('discipline_id', 'room_type_id')
    )
    op.create_table('room',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('building_id', sa.BigInteger(), nullable=False),
    sa.Column('number', sa.String(length=30), nullable=False),
    sa.Column('floor', sa.SmallInteger(), nullable=False),
    sa.Column('room_type_id', sa.BigInteger(), nullable=False),
    sa.Column('department_id', sa.BigInteger(), nullable=True),
    sa.Column('area', sa.Numeric(precision=9, scale=2), nullable=False),
    sa.Column('seats', sa.Integer(), nullable=False),
    sa.Column('staff_seats', sa.Integer(), nullable=False),
    sa.Column('volume', sa.Integer(), sa.Computed('seats + staff_seats', persisted=True), nullable=False),
    sa.Column('is_usable', sa.Boolean(), nullable=False),
    sa.Column('note', sa.String(length=500), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('area > 0', name='ck_room_area_positive'),
    sa.CheckConstraint('floor <> 0', name='ck_room_floor_not_zero'),
    sa.CheckConstraint('seats >= 0', name='ck_room_seats_non_negative'),
    sa.CheckConstraint('staff_seats >= 0', name='ck_room_staff_seats_non_negative'),
    sa.ForeignKeyConstraint(['building_id'], ['building.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['department_id'], ['department.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['room_type_id'], ['room_type.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('building_id', 'number', name='uq_room_building_number')
    )
    op.create_table('room_measurement',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('room_id', sa.BigInteger(), nullable=False),
    sa.Column('area', sa.Numeric(precision=9, scale=2), nullable=False),
    sa.Column('seats', sa.Integer(), nullable=False),
    sa.Column('staff_seats', sa.Integer(), nullable=False),
    sa.Column('measured_on', sa.Date(), nullable=False),
    sa.Column('measured_by_id', sa.Integer(), nullable=True),
    sa.Column('source', sa.Enum('MANUAL', 'IMPORT', 'INITIAL', name='measurement_source'), nullable=False),
    sa.Column('note', sa.String(length=300), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('area > 0', name='ck_measurement_area_positive'),
    sa.CheckConstraint('seats >= 0', name='ck_measurement_seats'),
    sa.CheckConstraint('staff_seats >= 0', name='ck_measurement_staff_seats'),
    sa.ForeignKeyConstraint(['measured_by_id'], ['app_user.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['room_id'], ['room.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_room_measurement_room_id'), 'room_measurement', ['room_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_room_measurement_room_id'), table_name='room_measurement')
    op.drop_table('room_measurement')
    op.drop_table('room')
    op.drop_table('discipline_room_type')
    op.drop_table('room_type')
    op.drop_table('discipline')
    op.drop_table('department')
    op.drop_table('building')
    op.drop_table('app_user')
    # Перечисления PostgreSQL живут отдельно от таблиц: без этого повторный
    # накат упадёт с «type already exists», а ТЗ требует полного отката
    sa.Enum(name='measurement_source').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='user_role').drop(op.get_bind(), checkfirst=True)
