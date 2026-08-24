from datetime import datetime, timezone

import bcrypt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import (
    create_token,
    decode_access_token,
    hash_password,
    validate_password,
    verify_password,
)
from app.database import Base
from app.email_outbox import enqueue_email
from app.mfa import (
    consume_recovery_code,
    create_mfa_challenge,
    decode_mfa_challenge,
    encrypt_secret,
    generate_recovery_codes,
    verify_totp,
)
from app.models import EmailOutbox
import pyotp


def test_new_passwords_use_argon2_and_legacy_bcrypt_still_verifies() -> None:
    password = "a sufficiently long passphrase"
    new_hash = hash_password(password)
    old_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    assert new_hash.startswith("$argon2id$")
    assert verify_password(password, new_hash)
    assert verify_password(password, old_hash)


def test_password_policy_rejects_short_and_common_values() -> None:
    for candidate in ("too short", "correcthorsebatterystaple"):
        try:
            validate_password(candidate)
        except ValueError:
            pass
        else:
            raise AssertionError("weak password was accepted")


def test_access_and_mfa_challenges_include_validated_one_time_identifiers() -> None:
    access_token, access_jti, expires_at = create_token(7)
    assert decode_access_token(access_token) == (7, None, access_jti)
    assert expires_at > datetime.now(timezone.utc)

    challenge, challenge_jti, _challenge_expiry = create_mfa_challenge(7)
    assert decode_mfa_challenge(challenge) == (7, challenge_jti)


def test_recovery_codes_are_stored_as_hashes_and_consumed_once() -> None:
    codes, serialized = generate_recovery_codes()
    assert codes[0] not in serialized
    valid, updated = consume_recovery_code(serialized, codes[0])
    assert valid
    assert consume_recovery_code(updated, codes[0])[0] is False


def test_totp_codes_cannot_be_replayed() -> None:
    secret = pyotp.random_base32()
    encrypted = encrypt_secret(secret)
    code = pyotp.TOTP(secret).now()

    matched_counter = verify_totp(encrypted, code)
    assert matched_counter is not None
    assert verify_totp(encrypted, code, last_counter=matched_counter) is None


def test_email_outbox_encrypts_message_bodies() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[EmailOutbox.__table__])
    db = sessionmaker(bind=engine)()
    try:
        enqueue_email(
            db,
            recipient="person@example.com",
            subject="Verify",
            html="secret bearer link",
            kind="test",
            expires_at=datetime.now(timezone.utc).replace(year=2099),
        )
        db.commit()
        row = db.query(EmailOutbox).one()
        assert "secret bearer link" not in row.encrypted_html
    finally:
        db.close()
        engine.dispose()
