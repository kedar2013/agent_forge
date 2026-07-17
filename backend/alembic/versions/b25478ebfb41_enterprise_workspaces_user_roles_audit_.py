"""enterprise: workspaces, user roles, audit hash chain

Revision ID: b25478ebfb41
Revises: 6a08ac63aeaa
Create Date: 2026-07-06 22:05:50.443731

"""
from alembic import op
import sqlalchemy as sa

from app.audit_hash import compute_row_hash

revision = 'b25478ebfb41'
down_revision = '6a08ac63aeaa'
branch_labels = None
depends_on = None

DEFAULT_WORKSPACE_ID = '00000000-0000-0000-0000-000000000001'


def upgrade() -> None:
    op.create_table('workspaces',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name'),
    schema='agent_forge'
    )

    conn = op.get_bind()
    conn.execute(
        sa.text("INSERT INTO agent_forge.workspaces (id, name) VALUES (:id, 'Default')"),
        {"id": DEFAULT_WORKSPACE_ID},
    )

    # Backfill every pre-existing row that predates multi-tenancy into the
    # default workspace, rather than leaving them workspace-less.
    for table in ("agents", "tools", "skills", "invocation_log"):
        conn.execute(
            sa.text(f"UPDATE agent_forge.{table} SET workspace_id = :ws WHERE workspace_id IS NULL"),
            {"ws": DEFAULT_WORKSPACE_ID},
        )

    op.add_column('users', sa.Column('role', sa.String(), nullable=True), schema='agent_forge')
    op.add_column('users', sa.Column('workspace_id', sa.UUID(), nullable=True), schema='agent_forge')
    conn.execute(sa.text("UPDATE agent_forge.users SET role = 'admin', workspace_id = :ws"), {"ws": DEFAULT_WORKSPACE_ID})
    op.alter_column('users', 'role', nullable=False, schema='agent_forge')
    op.alter_column('users', 'workspace_id', nullable=False, schema='agent_forge')
    op.create_check_constraint(
        'users_role_check', 'users', "role IN ('admin', 'viewer', 'chat_user')", schema='agent_forge'
    )

    op.add_column('config_audit_log', sa.Column('seq', sa.BigInteger(), autoincrement=True, nullable=True), schema='agent_forge')
    op.add_column('config_audit_log', sa.Column('workspace_id', sa.UUID(), nullable=True), schema='agent_forge')
    op.add_column('config_audit_log', sa.Column('prev_hash', sa.String(), nullable=True), schema='agent_forge')
    op.add_column('config_audit_log', sa.Column('row_hash', sa.String(), nullable=True), schema='agent_forge')

    # seq needs real values before it can be made unique/not-null — assign by
    # existing chronological order (there is no seq yet to order by).
    conn.execute(sa.text("""
        WITH ordered AS (
            SELECT id, ROW_NUMBER() OVER (ORDER BY created_at, id) AS rn
            FROM agent_forge.config_audit_log
        )
        UPDATE agent_forge.config_audit_log t
        SET seq = ordered.rn
        FROM ordered WHERE t.id = ordered.id
    """))

    # Compute the hash chain for whatever audit rows already exist, in seq order.
    existing_rows = conn.execute(sa.text("""
        SELECT id, entity_type, entity_id, action, actor, diff, created_at
        FROM agent_forge.config_audit_log ORDER BY seq
    """)).fetchall()
    prev_hash = None
    for row in existing_rows:
        row_hash = compute_row_hash(
            prev_hash=prev_hash,
            entity_type=row.entity_type,
            entity_id=str(row.entity_id),
            action=row.action,
            actor=row.actor,
            diff=row.diff,
            created_at_iso=row.created_at.isoformat(),
        )
        conn.execute(
            sa.text("UPDATE agent_forge.config_audit_log SET prev_hash = :prev, row_hash = :cur WHERE id = :id"),
            {"prev": prev_hash, "cur": row_hash, "id": row.id},
        )
        prev_hash = row_hash

    op.alter_column('config_audit_log', 'seq', nullable=False, schema='agent_forge')
    op.alter_column('config_audit_log', 'row_hash', nullable=False, schema='agent_forge')
    op.create_unique_constraint(None, 'config_audit_log', ['seq'], schema='agent_forge')


def downgrade() -> None:
    op.drop_constraint(None, 'config_audit_log', schema='agent_forge', type_='unique')
    op.drop_column('config_audit_log', 'row_hash', schema='agent_forge')
    op.drop_column('config_audit_log', 'prev_hash', schema='agent_forge')
    op.drop_column('config_audit_log', 'workspace_id', schema='agent_forge')
    op.drop_column('config_audit_log', 'seq', schema='agent_forge')
    op.drop_constraint('users_role_check', 'users', schema='agent_forge', type_='check')
    op.drop_column('users', 'workspace_id', schema='agent_forge')
    op.drop_column('users', 'role', schema='agent_forge')
    op.drop_table('workspaces', schema='agent_forge')
