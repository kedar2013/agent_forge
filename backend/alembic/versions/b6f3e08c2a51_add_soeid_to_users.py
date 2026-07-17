"""add soeid to users

Revision ID: b6f3e08c2a51
Revises: a9e21c6b4f7d
Create Date: 2026-07-11 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'b6f3e08c2a51'
down_revision = 'a9e21c6b4f7d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('soeid', sa.String(), nullable=True), schema='agent_forge')
    op.create_unique_constraint('uq_users_soeid', 'users', ['soeid'], schema='agent_forge')


def downgrade() -> None:
    op.drop_constraint('uq_users_soeid', 'users', schema='agent_forge', type_='unique')
    op.drop_column('users', 'soeid', schema='agent_forge')
