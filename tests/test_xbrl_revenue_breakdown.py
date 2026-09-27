"""Tests for the SEC XBRL segment / geography revenue parser.

The Revenue Breakdown tab used to be permanently empty because every wired
provider (yfinance, companyfacts, frames) exposes no dimensioned facts. The
filing's own instance document does -- via contexts on the
ProductOrServiceAxis / StatementBusinessSegmentsAxis /
StatementGeographicalAxis. These tests pin the parsing contract against a
fixture shaped like a real 10-K instance + label linkbase; nothing here hits
the network.
"""
from __future__ import annotations

import pytest

from edge.tools.sentiment_anomalies import (
    _extract_segment_revenue_from_instance,
    _iter_filing_documents,
    _member_pretty_name,
    _parse_label_linkbase,
)

INSTANCE_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
            xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
            xmlns:us-gaap="http://fasb.org/us-gaap/2024"
            xmlns:acme="http://www.acme.com/2024">
  <xbrli:context id="c-total">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000320193</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2024-09-29</xbrli:startDate><xbrli:endDate>2025-09-27</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:context id="c-prod">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000320193</xbrli:identifier>
      <xbrli:segment>
        <xbrldi:explicitMember dimension="srt:ProductOrServiceAxis">us-gaap:ProductMember</xbrldi:explicitMember>
      </xbrli:segment>
    </xbrli:entity>
    <xbrli:period><xbrli:startDate>2024-09-29</xbrli:startDate><xbrli:endDate>2025-09-27</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:context id="c-americas">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000320193</xbrli:identifier>
      <xbrli:segment>
        <xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">acme:AmericasSegmentMember</xbrldi:explicitMember>
      </xbrli:segment>
    </xbrli:entity>
    <xbrli:period><xbrli:startDate>2024-09-29</xbrli:startDate><xbrli:endDate>2025-09-27</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:context id="c-us">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000320193</xbrli:identifier>
      <xbrli:segment>
        <xbrldi:explicitMember dimension="srt:StatementGeographicalAxis">country:US</xbrldi:explicitMember>
      </xbrli:segment>
    </xbrli:entity>
    <xbrli:period><xbrli:instant>2025-09-27</xbrli:instant></xbrli:period>
  </xbrli:context>
  <us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax contextRef="c-total" unitRef="usd">400000000000</us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax>
  <us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax contextRef="c-prod" unitRef="usd">300000000000</us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax>
  <us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax contextRef="c-americas" unitRef="usd">178353000000</us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax>
  <us-gaap:Revenues contextRef="c-us" unitRef="usd">151790000000</us-gaap:Revenues>
</xbrli:xbrl>
"""

LABELS_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<linkbase xmlns="http://www.xbrl.org/2003/linkbase"
          xmlns:xlink="http://www.w3.org/1999/xlink">
  <labelLink>
    <loc xlink:type="locator" xlink:label="loc_acme_AmericasSegmentMember"
         xlink:href="acme.xsd#acme_AmericasSegmentMember"/>
    <label xlink:type="resource" xlink:label="lab_acme_AmericasSegmentMember"
           xlink:role="http://www.xbrl.org/2003/role/terseLabel" xml:lang="en-US">Americas</label>
    <labelArc xlink:type="arc" xlink:from="loc_acme_AmericasSegmentMember"
              xlink:to="lab_acme_AmericasSegmentMember"/>
    <loc xlink:type="locator" xlink:label="loc_country_US"
         xlink:href="country.xsd#country_US"/>
    <label xlink:type="resource" xlink:label="lab_country_US"
           xlink:role="http://www.xbrl.org/2003/role/label" xml:lang="en-US">United States [Member]</label>
    <labelArc xlink:type="arc" xlink:from="loc_country_US" xlink:to="lab_country_US"/>
  </labelLink>
</linkbase>
"""


def test_instance_parser_groups_dimensioned_revenue_by_axis():
    parsed = _extract_segment_revenue_from_instance(INSTANCE_XML, {})
    seg = parsed.get("us-gaap:StatementBusinessSegmentsAxis") or {}
    prod = parsed.get("srt:ProductOrServiceAxis") or {}
    geo = parsed.get("srt:StatementGeographicalAxis") or {}
    assert seg.get("Americas Segment", (None, None))[0] == pytest.approx(178_353_000_000.0)
    assert prod.get("Product", (None, None))[0] == pytest.approx(300_000_000_000.0)
    assert geo.get("US", (None, None))[0] == pytest.approx(151_790_000_000.0)


def test_consolidated_total_never_enters_the_breakdown():
    """The un-dimensioned total must not appear as a fake 'segment'."""
    parsed = _extract_segment_revenue_from_instance(INSTANCE_XML, {})
    for members in parsed.values():
        assert all(label != "Total" for label in members)
        assert len(members) <= 2


def test_label_linkbase_maps_qnames_to_terse_labels():
    labels = _parse_label_linkbase(LABELS_XML)
    assert labels["acme:AmericasSegmentMember"] == "Americas"
    # "[Member]" suffix is stripped from standard labels too.
    assert labels["country:US"] == "United States"


def test_member_pretty_name_handles_common_filings():
    assert _member_pretty_name("aapl:IPhoneMember") == "iPhone"
    assert _member_pretty_name("aapl:AmericasSegmentMember") == "Americas Segment"
    assert " " in _member_pretty_name("acme:WearablesHomeandAccessoriesMember")


def test_iter_filing_documents_only_lists_periodic_reports():
    submission = {
        "filings": {
            "recent": {
                "form": ["10-Q", "8-K", "10-K", "S-1"],
                "filingDate": ["2025-08-01", "2025-07-02", "2024-11-01", "2024-03-01"],
                "accessionNumber": ["0001-26", "0002-26", "0003-25", "0004-24"],
                "primaryDocument": ["q.htm", "k8.htm", "annual.htm", "s1.htm"],
            }
        }
    }
    docs = _iter_filing_documents(submission, "0000320193")
    forms = [d["form"] for d in docs]
    assert forms == ["10-Q", "10-K"]
    for doc in docs:
        assert doc["instance_url"].endswith("_htm.xml")
        assert doc["accession_nodash"].isalnum()
