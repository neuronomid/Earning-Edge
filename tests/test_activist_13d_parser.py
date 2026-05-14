from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.sec.activist_13d_parser import parse_filing
from app.services.sec.filings_client import FilingHeader


def _header(
    *,
    form_type: str = "SC 13D",
    accession: str = "0001234567-25-000001",
    cik: str = "0000111111",
    ticker: str | None = "ACME",
) -> FilingHeader:
    return FilingHeader(
        cik=cik,
        filer_name="Activist Partners LP",
        accession=accession,
        form_type=form_type,  # type: ignore[arg-type]
        filing_date=date(2026, 5, 10),
        primary_doc="primary.htm",
        subject_ticker=ticker,
        subject_name="Acme Corp",
    )


_ACTIVE_BODY = """
<html><body>
<p>Cover page: The Reporting Person beneficially owns 7.4% of the outstanding shares.</p>
<h2>Item 4. Purpose of Transaction</h2>
<p>The Reporting Persons intend to engage in engagement with management regarding
strategic alternatives, including potential operational changes and board representation.
The Reporting Persons may propose value-enhancing initiatives.</p>
<h2>Item 5. Interest in Securities of the Issuer</h2>
<p>...</p>
</body></html>
"""


_PASSIVE_BODY = """
<html><body>
<p>Cover page: The Reporting Person beneficially owns 6.1% of the outstanding shares.</p>
<h2>Item 4. Purpose of Transaction</h2>
<p>The shares were acquired for investment purposes only. The Reporting Persons have no
plans or proposals which relate to the Issuer.</p>
<h2>Item 5. Interest in Securities of the Issuer</h2>
</body></html>
"""


_AMENDMENT_BODY = """
<html><body>
<p>Cover page: The Reporting Person now beneficially owns 9.3% of the outstanding shares,
an increase from the 7.4% previously disclosed.</p>
<h2>Item 4. Purpose of Transaction</h2>
<p>This amendment reports continued engagement with management on operational changes
and proposals for strategic alternatives.</p>
<h2>Item 5. Interest in Securities of the Issuer</h2>
</body></html>
"""


_SHALLOW_AMENDMENT_BODY = """
<html><body>
<p>Cover page: The Reporting Person beneficially owns 7.4% of the outstanding shares.</p>
<h2>Item 4. Purpose of Transaction</h2>
<p>This amendment reports continued engagement with management regarding strategic
alternatives and operational changes.</p>
<h2>Item 5. Interest in Securities of the Issuer</h2>
</body></html>
"""


_ITEM4_CHANGED_AMENDMENT_BODY = """
<html><body>
<p>Cover page: The Reporting Person beneficially owns 7.4% of the outstanding shares.</p>
<p>Item 4 is hereby amended and supplemented as follows.</p>
<h2>Item 4. Purpose of Transaction</h2>
<p>The Reporting Persons intend to engage with the Issuer's board and may seek changes
to the capital allocation policy.</p>
<h2>Item 5. Interest in Securities of the Issuer</h2>
</body></html>
"""


_UNPARSEABLE_STAKE_BODY = """
<html><body>
<p>Cover page: The Reporting Person beneficially owns shares.</p>
<h2>Item 4. Purpose of Transaction</h2>
<p>The Reporting Persons intend to seek board representation and propose strategic
alternatives.</p>
<h2>Item 5. Interest in Securities of the Issuer</h2>
</body></html>
"""


def test_parses_initial_sc_13d_with_active_item4() -> None:
    parsed = parse_filing(_header(), _ACTIVE_BODY)

    assert parsed is not None
    assert parsed.form_type == "SC 13D"
    assert parsed.ticker == "ACME"
    assert parsed.stake_percent == Decimal("7.4")
    assert parsed.item4_active_intent is True
    assert parsed.is_substantive is True
    assert parsed.primary_doc_url.endswith("primary.htm")


def test_parses_sc_13d_a_amendment_with_stake_change() -> None:
    parsed = parse_filing(_header(form_type="SC 13D/A"), _AMENDMENT_BODY)

    assert parsed is not None
    assert parsed.form_type == "SC 13D/A"
    assert parsed.stake_percent == Decimal("9.3")
    assert parsed.is_substantive is True


def test_sc_13d_a_active_intent_without_substantive_change_is_not_substantive() -> None:
    parsed = parse_filing(_header(form_type="SC 13D/A"), _SHALLOW_AMENDMENT_BODY)

    assert parsed is not None
    assert parsed.item4_active_intent is True
    assert parsed.is_substantive is False


def test_sc_13d_a_item4_change_and_escalation_is_substantive() -> None:
    parsed = parse_filing(_header(form_type="SC 13D/A"), _ITEM4_CHANGED_AMENDMENT_BODY)

    assert parsed is not None
    assert parsed.item4_active_intent is True
    assert parsed.is_substantive is True


def test_active_intent_catches_board_engagement_and_capital_allocation() -> None:
    body = """
    <html><body>
    <p>Cover page: The Reporting Person beneficially owns 6.4% of the outstanding shares.</p>
    <h2>Item 4. Purpose of Transaction</h2>
    <p>The Reporting Persons intend to engage with the Issuer's board and may seek
    changes to the capital allocation policy.</p>
    <h2>Item 5. Interest in Securities of the Issuer</h2>
    </body></html>
    """

    parsed = parse_filing(_header(), body)

    assert parsed is not None
    assert parsed.item4_active_intent is True


def test_excludes_sc_13g_passive_filings() -> None:
    # Parser refuses an SC 13D with no active intent — same outcome any 13G-style
    # filing would produce when it lacks Item 4 active language.
    parsed = parse_filing(_header(), _PASSIVE_BODY)

    assert parsed is None


def test_excludes_filings_with_no_active_intent_language() -> None:
    body = _ACTIVE_BODY.replace(
        "engagement with management regarding\nstrategic alternatives,"
        " including potential operational changes and board representation.\n"
        "The Reporting Persons may propose value-enhancing initiatives.",
        "The shares are held for general investment, with no specific plans.",
    )
    parsed = parse_filing(_header(), body)

    assert parsed is None


def test_unparseable_stake_returns_none_and_drops_filing() -> None:
    parsed = parse_filing(_header(), _UNPARSEABLE_STAKE_BODY)

    assert parsed is None
