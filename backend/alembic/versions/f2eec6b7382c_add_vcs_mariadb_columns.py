"""add vcs mariadb columns

Revision ID: f2eec6b7382c
Revises: 60d37f6b264b
Create Date: 2026-07-31 00:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2eec6b7382c'
down_revision: Union[str, Sequence[str], None] = '60d37f6b264b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('vcs_settings', sa.Column('vcs_mariadb_user', sa.String(length=255), nullable=True))
    op.add_column('vcs_settings', sa.Column('vcs_mariadb_password', sa.String(length=255), nullable=True))
    op.add_column('vcs_settings', sa.Column('vcs_mariadb_database', sa.String(length=255), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('vcs_settings', 'vcs_mariadb_database')
    op.drop_column('vcs_settings', 'vcs_mariadb_password')
    op.drop_column('vcs_settings', 'vcs_mariadb_user')
