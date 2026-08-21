"""add secure invitation fields and Stripe webhook receipts

Revision ID: b7c3d91e5a42
Revises: ad2e1df4ce24
Create Date: 2026-08-20

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7c3d91e5a42"
down_revision: Union[str, Sequence[str], None] = "ad2e1df4ce24"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable fields preserve legacy invitation rows while all newly issued
    # tokens use the hash/expiry contract in app.models.Invitation.
    op.add_column(
        "invitations",
        sa.Column("token_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "invitations",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_invitations_token_hash",
        "invitations",
        ["token_hash"],
        unique=False,
    )

    # The plaintext token is a bearer credential. Existing pending invitations
    # cannot be converted to hashes because their original token would still be
    # usable, so revoke them before irreversibly scrubbing every legacy value.
    op.execute(
        """
        UPDATE invitations
        SET status = 'revoked'
        WHERE status = 'pending'
          AND token_hash IS NULL
        """
    )
    op.execute(
        """
        UPDATE invitations
        SET token = NULL
        WHERE token IS NOT NULL
        """
    )

    op.create_table(
        "stripe_webhook_events",
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("event_id"),
    )

    # Authentication and Stripe webhooks resolve these identifiers
    # case-insensitively/exactly. Abort rather than silently choosing one row
    # when a legacy database contains ambiguous identities.
    op.execute(
        """
        DO $identity_audit$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM users GROUP BY lower(email) HAVING COUNT(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'Cannot add identity uniqueness indexes: duplicate emails require manual reconciliation';
            END IF;
            IF EXISTS (
                SELECT 1 FROM users
                WHERE stripe_customer_id IS NOT NULL
                GROUP BY stripe_customer_id HAVING COUNT(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'Cannot add Stripe customer uniqueness index: duplicate IDs require manual reconciliation';
            END IF;
            IF EXISTS (
                SELECT 1 FROM users
                WHERE stripe_subscription_id IS NOT NULL
                GROUP BY stripe_subscription_id HAVING COUNT(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'Cannot add Stripe subscription uniqueness index: duplicate IDs require manual reconciliation';
            END IF;
        END
        $identity_audit$;
        """
    )
    op.create_index(
        "uq_users_email_lower",
        "users",
        [sa.text("lower(email)")],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
    )
    op.create_index(
        "uq_users_stripe_customer_id",
        "users",
        ["stripe_customer_id"],
        unique=True,
        postgresql_where=sa.text("stripe_customer_id IS NOT NULL"),
    )
    op.create_index(
        "uq_users_stripe_subscription_id",
        "users",
        ["stripe_subscription_id"],
        unique=True,
        postgresql_where=sa.text("stripe_subscription_id IS NOT NULL"),
    )

    # Older databases predate the model's org/user uniqueness constraint. Add
    # an equivalent migration-owned constraint only when existing data proves
    # that doing so is non-destructive. Fresh databases already have the model-
    # named constraint and therefore skip this block.
    op.execute(
        """
        DO $migration$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = 'org_members'::regclass
                  AND conname IN (
                      'uq_org_members_org_user',
                      'uq_org_members_org_user_existing'
                  )
            ) THEN
                LOCK TABLE org_members IN SHARE ROW EXCLUSIVE MODE;

                -- Recheck after taking the lock so two deployers cannot race.
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conrelid = 'org_members'::regclass
                      AND conname IN (
                          'uq_org_members_org_user',
                          'uq_org_members_org_user_existing'
                      )
                ) THEN
                    IF EXISTS (
                        SELECT 1
                        FROM org_members
                        GROUP BY org_id, user_id
                        HAVING COUNT(*) > 1
                    ) THEN
                        RAISE EXCEPTION
                            'Cannot add org_members uniqueness constraint: duplicate rows require manual reconciliation';
                    ELSE
                        ALTER TABLE org_members
                        ADD CONSTRAINT uq_org_members_org_user_existing
                        UNIQUE (org_id, user_id);
                    END IF;
                END IF;
            END IF;
        END
        $migration$;
        """
    )


def downgrade() -> None:
    # Plaintext bearer tokens were intentionally destroyed during upgrade and
    # must never be reconstructed during downgrade.
    # Only remove the migration-owned compatibility constraint. The constraint
    # created by the initial schema, when present, belongs to that revision.
    op.drop_index("uq_users_stripe_subscription_id", table_name="users")
    op.drop_index("uq_users_stripe_customer_id", table_name="users")
    op.drop_index("uq_users_email_lower", table_name="users")
    op.execute(
        """
        ALTER TABLE org_members
        DROP CONSTRAINT IF EXISTS uq_org_members_org_user_existing
        """
    )
    op.drop_table("stripe_webhook_events")
    op.drop_index("ix_invitations_token_hash", table_name="invitations")
    op.drop_column("invitations", "expires_at")
    op.drop_column("invitations", "token_hash")
