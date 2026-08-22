from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import get_balance_sheet
from app.api.schemas import BalanceSheetSummary
from app.domain.balance_sheet import BalanceSheet


router = APIRouter()


@router.get("/balance-sheet", response_model=BalanceSheetSummary)
def get_balance_sheet_summary(
    balance_sheet: BalanceSheet = Depends(get_balance_sheet),
) -> BalanceSheetSummary:
    return BalanceSheetSummary(
        total_assets=balance_sheet.total_assets(),
        total_liabilities=balance_sheet.total_liabilities(),
        counts={
            "mortgages": len(balance_sheet.mortgages),
            "bonds": len(balance_sheet.bonds),
            "term_deposits": len(balance_sheet.term_deposits),
            "nmd": len(balance_sheet.nmd),
            "issued_debt": len(balance_sheet.issued_debt),
            "swaps": len(balance_sheet.swaps),
        },
    )
