"""FDD-OBS-001 H-001 (CISO review) — `_validate_obs_master_key`.

Validates the Pydantic model_validator on `Settings`:
  - Empty default is accepted (R2 development).
  - Set + ≥32 chars is accepted.
  - Set + <32 chars raises ValueError at startup (fail-fast).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config import Settings


class TestObsMasterKeyValidator:
    def test_empty_default_accepted(self):
        """Empty `PULSE_OBS_MASTER_KEY` is fine — R2 dev phase before
        PR 2 ships any encryption."""
        s = Settings(pulse_obs_master_key="")
        assert s.pulse_obs_master_key == ""

    def test_strong_key_accepted(self):
        """32-char key is the minimum; longer is fine."""
        strong_32 = "a" * 32
        s = Settings(pulse_obs_master_key=strong_32)
        assert s.pulse_obs_master_key == strong_32

        strong_64 = "B" * 64
        s = Settings(pulse_obs_master_key=strong_64)
        assert s.pulse_obs_master_key == strong_64

    def test_weak_key_rejected_at_startup(self):
        """<32 chars raises ValidationError (Pydantic wraps ValueError).

        This is the fail-fast contract: a developer who deploys with
        `dev123` cannot start the application, period."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(pulse_obs_master_key="dev123")
        # Verify error message is actionable.
        assert "32 characters" in str(exc_info.value)
        assert "openssl rand" in str(exc_info.value)

    def test_31_char_key_at_boundary_rejected(self):
        """Exact boundary — 31 chars rejected, 32 accepted."""
        with pytest.raises(ValidationError):
            Settings(pulse_obs_master_key="x" * 31)

        # 32 chars passes
        s = Settings(pulse_obs_master_key="x" * 32)
        assert s.pulse_obs_master_key == "x" * 32
