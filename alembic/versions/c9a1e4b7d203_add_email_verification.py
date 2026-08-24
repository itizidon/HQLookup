"""add email verification state

Revision ID: c9a1e4b7d203
Revises: b7c3d91e5a42
Create Date: 2026-08-24
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9a1e4b7d203"
down_revision: Union[str, Sequence[str], None] = "b7c3d91e5a42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("email_verification_token_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("email_verification_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_users_email_verification_token_hash",
        "users",
        ["email_verification_token_hash"],
        unique=True,
    )

    # Preserve access only for accounts with evidence of an established,
    # trusted workspace relationship. Unattached public-signup accounts remain
    # unverified and receive a fresh link after proving their password.
    op.execute(
        """
        UPDATE users AS u
        SET email_verified_at = now()
        WHERE u.email_verified_at IS NULL
          AND (
              u.role = 'superadmin'
              OR EXISTS (SELECT 1 FROM organizations o WHERE o.owner_id = u.id)
              OR EXISTS (SELECT 1 FROM org_members m WHERE m.user_id = u.id)
              OR EXISTS (
                  SELECT 1 FROM invitations i
                  WHERE lower(i.email) = lower(u.email)
                    AND i.status = 'accepted'
              )
          )
        """
    )


def downgrade() -> None:
    op.drop_index("ix_users_email_verification_token_hash", table_name="users")
    op.drop_column("users", "email_verification_expires_at")
    op.drop_column("users", "email_verification_token_hash")
    op.drop_column("users", "email_verified_at")
