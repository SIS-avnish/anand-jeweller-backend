"""make customer user fields nullable and remove email unique"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '7f1f61efa707'
down_revision: Union[str, Sequence[str], None] = 'f3eb1b2c10a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # New table create (without email unique + nullable fields)
    op.create_table(
        'customer_users_new',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('mobile_number', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=True),
        sa.Column('address', sa.String(), nullable=True),
        sa.Column('nearby_store', sa.String(), nullable=True),
        sa.Column('password_hash', sa.String(), nullable=False),
        sa.Column('is_deleted', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('mobile_number')
    )

    # Old data copy
    op.execute("""
        INSERT INTO customer_users_new
        (id, name, mobile_number, email, address, nearby_store, password_hash, is_deleted, deleted_at, created_at)
        SELECT
        id, name, mobile_number, email, address, nearby_store, password_hash,
        COALESCE(is_deleted, 0), deleted_at, created_at
        FROM customer_users
    """)

    # Old table drop
    op.drop_table('customer_users')

    # Rename new table
    op.rename_table('customer_users_new', 'customer_users')

    # Index recreate
    op.create_index('ix_customer_users_id', 'customer_users', ['id'], unique=False)
    op.create_index('ix_customer_users_mobile_number', 'customer_users', ['mobile_number'], unique=False)
    op.create_index('ix_customer_users_email', 'customer_users', ['email'], unique=False)


def downgrade():
    # Old structure recreate (with NOT NULL + UNIQUE email)
    op.create_table(
        'customer_users_old',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('mobile_number', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('address', sa.String(), nullable=False),
        sa.Column('nearby_store', sa.String(), nullable=False),
        sa.Column('password_hash', sa.String(), nullable=False),
        sa.Column('is_deleted', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('mobile_number'),
        sa.UniqueConstraint('email')
    )

    op.execute("""
        INSERT INTO customer_users_old
        (id, name, mobile_number, email, address, nearby_store, password_hash, is_deleted, deleted_at, created_at)
        SELECT
        id, name, mobile_number,
        COALESCE(email, ''),
        COALESCE(address, ''),
        COALESCE(nearby_store, ''),
        password_hash, COALESCE(is_deleted, 0), deleted_at, created_at
        FROM customer_users
    """)

    op.drop_table('customer_users')

    op.rename_table('customer_users_old', 'customer_users')

    op.create_index('ix_customer_users_id', 'customer_users', ['id'], unique=False)
    op.create_index('ix_customer_users_mobile_number', 'customer_users', ['mobile_number'], unique=False)
    op.create_index('ix_customer_users_email', 'customer_users', ['email'], unique=False)
    