"""Create the complete application schema.

Revision ID: ad2e1df4ce24
Revises: None
Create Date: 2026-08-10

This revision replaces an incomplete historical chain which could not build a
database from scratch. The revision ID deliberately matches the previous head
so an existing database already stamped at that head remains recognizable.
See alembic/README before adopting this baseline on an existing database.
"""

from collections.abc import Sequence

from alembic import op
from pgvector.sqlalchemy import Vector
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "ad2e1df4ce24"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the PostgreSQL extension, tables, constraints, and indexes."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("hashed_password", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("plan", sa.String(), nullable=False),
        sa.Column("stripe_customer_id", sa.String(), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(), nullable=True),
        sa.Column("stripe_current_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_id", "users", ["id"])

    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name="fk_organizations_owner_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_organizations"),
    )
    op.create_index("ix_organizations_id", "organizations", ["id"])

    op.create_table(
        "businesses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("rag_data", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("query_allocation", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name="fk_businesses_org_id_organizations"),
        sa.PrimaryKeyConstraint("id", name="pk_businesses"),
    )
    op.create_index("ix_businesses_id", "businesses", ["id"])
    op.create_index("ix_businesses_org_id", "businesses", ["org_id"])

    op.create_table(
        "org_members",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("invited_by_id", sa.Integer(), nullable=True),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name="fk_org_members_org_id_organizations"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_org_members_user_id_users"),
        sa.ForeignKeyConstraint(["invited_by_id"], ["users.id"], name="fk_org_members_invited_by_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_org_members"),
    )
    op.create_index("ix_org_members_id", "org_members", ["id"])
    op.create_index("ix_org_members_org_id", "org_members", ["org_id"])
    op.create_index("ix_org_members_user_id", "org_members", ["user_id"])

    op.create_table(
        "user_business",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_user_business_user_id_users"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], name="fk_user_business_business_id_businesses"),
        sa.PrimaryKeyConstraint("user_id", "business_id", name="pk_user_business"),
    )

    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], name="fk_documents_business_id_businesses"),
        sa.PrimaryKeyConstraint("id", name="pk_documents"),
    )
    op.create_index("ix_documents_id", "documents", ["id"])
    op.create_index("ix_documents_business_id", "documents", ["business_id"])

    op.create_table(
        "chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("parent_text", sa.Text(), nullable=True),
        sa.Column("chunk_type", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("parent_chunk_id", sa.Integer(), nullable=True),
        sa.Column("embedding", Vector(dim=384), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], name="fk_chunks_business_id_businesses"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], name="fk_chunks_document_id_documents"),
        sa.ForeignKeyConstraint(["parent_chunk_id"], ["chunks.id"], name="fk_chunks_parent_chunk_id_chunks"),
        sa.PrimaryKeyConstraint("id", name="pk_chunks"),
    )
    op.create_index("ix_chunks_id", "chunks", ["id"])
    op.create_index("ix_chunks_business_id", "chunks", ["business_id"])
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])

    op.create_table(
        "query_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("hyde_response", sa.Text(), nullable=True),
        sa.Column("answer", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("retrieval_plan", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name="fk_query_logs_org_id_organizations"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], name="fk_query_logs_business_id_businesses"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_query_logs_user_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_query_logs"),
    )
    op.create_index("ix_query_logs_id", "query_logs", ["id"])
    op.create_index("ix_query_logs_org_id", "query_logs", ["org_id"])
    op.create_index("ix_query_logs_business_id", "query_logs", ["business_id"])
    op.create_index("ix_query_logs_user_id", "query_logs", ["user_id"])

    op.create_table(
        "invitations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("token", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name="fk_invitations_org_id_organizations"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], name="fk_invitations_business_id_businesses"),
        sa.PrimaryKeyConstraint("id", name="pk_invitations"),
    )
    op.create_index("ix_invitations_id", "invitations", ["id"])
    op.create_index("ix_invitations_org_id", "invitations", ["org_id"])
    op.create_index("ix_invitations_business_id", "invitations", ["business_id"])


def downgrade() -> None:
    """Remove application-owned objects; keep the shared vector extension."""
    op.drop_index("ix_invitations_business_id", table_name="invitations")
    op.drop_index("ix_invitations_org_id", table_name="invitations")
    op.drop_index("ix_invitations_id", table_name="invitations")
    op.drop_table("invitations")

    op.drop_index("ix_query_logs_user_id", table_name="query_logs")
    op.drop_index("ix_query_logs_business_id", table_name="query_logs")
    op.drop_index("ix_query_logs_org_id", table_name="query_logs")
    op.drop_index("ix_query_logs_id", table_name="query_logs")
    op.drop_table("query_logs")

    op.drop_index("ix_chunks_document_id", table_name="chunks")
    op.drop_index("ix_chunks_business_id", table_name="chunks")
    op.drop_index("ix_chunks_id", table_name="chunks")
    op.drop_table("chunks")

    op.drop_index("ix_documents_business_id", table_name="documents")
    op.drop_index("ix_documents_id", table_name="documents")
    op.drop_table("documents")

    op.drop_table("user_business")

    op.drop_index("ix_org_members_user_id", table_name="org_members")
    op.drop_index("ix_org_members_org_id", table_name="org_members")
    op.drop_index("ix_org_members_id", table_name="org_members")
    op.drop_table("org_members")

    op.drop_index("ix_businesses_org_id", table_name="businesses")
    op.drop_index("ix_businesses_id", table_name="businesses")
    op.drop_table("businesses")

    op.drop_index("ix_organizations_id", table_name="organizations")
    op.drop_table("organizations")

    op.drop_index("ix_users_id", table_name="users")
    op.drop_table("users")
