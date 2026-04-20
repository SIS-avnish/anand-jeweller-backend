"""add soft delete fields to customer_users

Revision ID: f3eb1b2c10a2
Revises: d72e2caff89b
Create Date: 2026-04-15 14:58:39.983715
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3eb1b2c10a2'
down_revision: Union[str, Sequence[str], None] = 'd72e2caff89b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # columns already exist in customer_users
    pass


def downgrade() -> None:
    # nothing to downgrade
    pass