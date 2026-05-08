"""issue #18: 子域名词表扩到 SecLists top-2000 的回归。"""

from __future__ import annotations

from tools._subdomains_seclists import SECLISTS_TOP2000
from tools.recon_wordlists import LEGACY_SUBDOMAINS, SUBDOMAINS


def test_subdomains_is_seclists_top2000() -> None:
    assert SUBDOMAINS is SECLISTS_TOP2000
    assert len(SUBDOMAINS) == 2000


def test_subdomains_starts_with_well_known_entries() -> None:
    head = set(SUBDOMAINS[:50])
    assert "www" in head
    assert "mail" in head


def test_seclists_top2000_no_blanks_or_dupes() -> None:
    assert all(s.strip() == s and s for s in SECLISTS_TOP2000)
    assert len(set(SECLISTS_TOP2000)) == len(SECLISTS_TOP2000)


def test_legacy_subdomains_still_available() -> None:
    """旧字典留存为 LEGACY_SUBDOMAINS，避免外部代码导入断裂。"""
    assert isinstance(LEGACY_SUBDOMAINS, list)
    assert "www" in LEGACY_SUBDOMAINS
    # 旧列表大小：~218
    assert 200 <= len(LEGACY_SUBDOMAINS) <= 250
