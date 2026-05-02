"""End-to-end test: Finviz → top 5 CandidateRecord objects."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.finviz.browser import FinvizBrowserClient
from app.services.finviz.extractor import FinvizExtractor


async def main() -> None:
    browser = FinvizBrowserClient(headless=True, timeout_ms=30000)
    extractor = FinvizExtractor(browser)
    records = await extractor.get_top_five()

    print(f"Got {len(records)} candidates:\n")
    for i, r in enumerate(records, 1):
        print(
            f"  #{i}  {r.ticker:8}  {(r.company_name or '')[:35]:35}"
            f"  cap={r.market_cap}  price={r.current_price}"
            f"  chg={r.daily_change_percent}%  vol={r.volume}"
            f"  sector={r.sector}  sources={r.sources}"
        )


asyncio.run(main())
