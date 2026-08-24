from app.database import Base
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB

# ── Junction table: which users can access which businesses ────────────────────
user_business = Table(
    "user_business",
    Base.metadata,
    Column("user_id",     Integer, ForeignKey("users.id"),      primary_key=True),
    Column("business_id", Integer, ForeignKey("businesses.id"), primary_key=True),
)


class Organization(Base):
    """
    An isolated enterprise workspace containment layer. 
    Limits are derived dynamically from the owner's active plan tier.
    """
    __tablename__ = "organizations"

    id            = Column(Integer, primary_key=True, index=True)
    name          = Column(String, nullable=False)
    owner_id      = Column(Integer, ForeignKey("users.id"), nullable=False)
    is_active     = Column(Boolean, nullable=False, default=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    owner         = relationship("User", foreign_keys=[owner_id], back_populates="owned_orgs")
    businesses    = relationship("Business", back_populates="organization", cascade="all, delete-orphan")
    members       = relationship("OrgMember", back_populates="organization", cascade="all, delete-orphan")
    query_logs    = relationship("QueryLog", back_populates="organization")


class OrgMember(Base):
    """
    Tracks every user who belongs to an org (admin or not).
    """
    __tablename__ = "org_members"
    __table_args__ = (
        UniqueConstraint("org_id", "user_id", name="uq_org_members_org_user"),
    )

    id              = Column(Integer, primary_key=True, index=True)
    org_id          = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    user_id         = Column(Integer, ForeignKey("users.id"),         nullable=False, index=True)
    role            = Column(String, nullable=False, default="member")  # admin / member
    invited_by_id   = Column(Integer, ForeignKey("users.id"),         nullable=True)
    joined_at       = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    organization    = relationship("Organization", back_populates="members")
    user            = relationship("User", foreign_keys=[user_id], back_populates="org_memberships")
    invited_by      = relationship("User", foreign_keys=[invited_by_id])


class User(Base):
    """
    The main billing and access entity. Subscription tiers live here, 
    controlling global organization creation caps.
    """
    __tablename__ = "users"
    __table_args__ = (
        Index(
            "uq_users_email_lower",
            text("lower(email)"),
            unique=True,
            postgresql_where=text("email IS NOT NULL"),
        ),
        Index(
            "uq_users_stripe_customer_id",
            "stripe_customer_id",
            unique=True,
            postgresql_where=text("stripe_customer_id IS NOT NULL"),
        ),
        Index(
            "uq_users_stripe_subscription_id",
            "stripe_subscription_id",
            unique=True,
            postgresql_where=text("stripe_subscription_id IS NOT NULL"),
        ),
    )

    id              = Column(Integer, primary_key=True, index=True)
    email           = Column(String, unique=True, nullable=False)
    name            = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)
    role            = Column(String, default="user")   # global role: superadmin / user
    created_at      = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    email_verified_at = Column(DateTime(timezone=True), nullable=True)
    email_verification_token_hash = Column(String(64), nullable=True, unique=True, index=True)
    email_verification_expires_at = Column(DateTime(timezone=True), nullable=True)
    mfa_secret_encrypted = Column(Text, nullable=True)
    mfa_recovery_code_hashes = Column(Text, nullable=True)
    mfa_enabled_at = Column(DateTime(timezone=True), nullable=True)
    mfa_last_counter = Column(Integer, nullable=True)

    # Subscription properties shifted to the User level
    plan                    = Column(String, nullable=False, default="free")  # free/starter/pro/business
    stripe_customer_id      = Column(String, nullable=True)
    stripe_subscription_id  = Column(String, nullable=True)
    stripe_current_period_start = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    # Changed uselist=True since an upgraded plan allows owning multiple workspaces
    owned_orgs      = relationship("Organization", foreign_keys="Organization.owner_id", back_populates="owner")
    org_memberships = relationship("OrgMember", foreign_keys="OrgMember.user_id", back_populates="user")
    businesses      = relationship("Business", secondary=user_business, back_populates="users")


class UserSession(Base):
    __tablename__ = "user_sessions"

    jti        = Column(String(32), primary_key=True)
    user_id    = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PasswordReset(Base):
    __tablename__ = "password_resets"

    id         = Column(Integer, primary_key=True)
    user_id    = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class MfaLoginChallenge(Base):
    __tablename__ = "mfa_login_challenges"

    jti        = Column(String(32), primary_key=True)
    user_id    = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class EmailOutbox(Base):
    __tablename__ = "email_outbox"

    id             = Column(Integer, primary_key=True)
    recipient      = Column(String, nullable=False)
    subject        = Column(String, nullable=False)
    encrypted_html = Column(Text, nullable=False)
    kind           = Column(String, nullable=False, index=True)
    attempts       = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    expires_at     = Column(DateTime(timezone=True), nullable=False, index=True)
    sent_at        = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at     = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Business(Base):
    __tablename__ = "businesses"

    id              = Column(Integer, primary_key=True, index=True)
    org_id          = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    name            = Column(String, nullable=False)
    rag_data        = Column(String, nullable=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    query_allocation = Column(Integer, nullable=False, default=25) # Default cap per business location
    organization    = relationship("Organization", back_populates="businesses")
    users           = relationship("User", secondary=user_business, back_populates="businesses")
    documents       = relationship("Document", back_populates="business", cascade="all, delete-orphan")
    query_logs      = relationship("QueryLog", back_populates="business")


class Document(Base):
    __tablename__ = "documents"

    id              = Column(Integer, primary_key=True, index=True)
    business_id     = Column(Integer, ForeignKey("businesses.id"), nullable=False, index=True)
    filename        = Column(String, nullable=False)
    content         = Column(Text, nullable=True)
    description     = Column(Text, nullable=True)  # Stores spreadsheet context / user notes
    status          = Column(String, nullable=False, default="ready")
    created_at      = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    business        = relationship("Business", back_populates="documents")
    chunks          = relationship("Chunk", back_populates="document", cascade="all, delete-orphan")


class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(Integer, primary_key=True, index=True)

    business_id = Column(
        Integer,
        ForeignKey("businesses.id"),
        nullable=False,
        index=True,
    )

    document_id = Column(
        Integer,
        ForeignKey("documents.id"),
        nullable=False,
        index=True,
    )

    chunk_index = Column(Integer, nullable=False)

    # Small chunk used for embedding
    text = Column(Text, nullable=False)

    # Parent context sent to LLM
    parent_text = Column(Text, nullable=True)

    #
    # Hierarchy ONLY
    #
    chunk_type = Column(
        String,
        nullable=False,
        default="child",
    )

    #
    # Semantic meaning
    #
    content_type = Column(
        String,
        nullable=False,
        default="text",
    )

    parent_chunk_id = Column(
        Integer,
        ForeignKey("chunks.id"),
        nullable=True,
    )

    embedding = Column(Vector(384), nullable=False)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    document = relationship("Document", back_populates="chunks")


class QueryLog(Base):
    __tablename__ = "query_logs"

    id              = Column(Integer, primary_key=True, index=True)
    org_id          = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    business_id     = Column(Integer, ForeignKey("businesses.id"),    nullable=False, index=True)
    user_id         = Column(Integer, ForeignKey("users.id"),         nullable=False, index=True)
    query_text      = Column(Text, nullable=False)
    hyde_response   = Column(Text, nullable=True) # Stored raw hypothetical text expansion
    answer          = Column(JSONB, nullable=False)
    retrieval_plan  = Column(String, nullable=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    organization    = relationship("Organization", back_populates="query_logs")
    business        = relationship("Business",     back_populates="query_logs")
    user            = relationship("User")

class Invitation(Base):
    __tablename__ = "invitations"

    id          = Column(Integer, primary_key=True, index=True)
    org_id      = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"),    nullable=False, index=True)
    email       = Column(String, nullable=False)
    role        = Column(String, nullable=False, default="member")
    status      = Column(String, nullable=False, default="pending")  # pending / accepted / revoked
    # ``token`` is retained temporarily for migration compatibility only. New
    # invitations never store the bearer credential itself.
    token       = Column(String, nullable=True)
    token_hash  = Column(String(64), nullable=True, index=True)
    expires_at  = Column(DateTime(timezone=True), nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    organization = relationship("Organization")
    business     = relationship("Business")


class StripeWebhookEvent(Base):
    """A durable receipt used to make Stripe webhook handling idempotent."""

    __tablename__ = "stripe_webhook_events"

    event_id = Column(String, primary_key=True)
    processed_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
