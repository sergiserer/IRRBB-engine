from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from app.domain.instruments import (
    Bond,
    IssuedDebt,
    Mortgage,
    NonMaturingDeposit,
    Swap,
    TermDeposit,
)


@dataclass
class BalanceSheet:
    mortgages: List[Mortgage] = field(default_factory=list)
    term_deposits: List[TermDeposit] = field(default_factory=list)
    nmd: List[NonMaturingDeposit] = field(default_factory=list)
    bonds: List[Bond] = field(default_factory=list)
    issued_debt: List[IssuedDebt] = field(default_factory=list)
    swaps: List[Swap] = field(default_factory=list)

    def total_assets(self) -> float:
        return sum(m.notional for m in self.mortgages) + sum(b.notional for b in self.bonds)

    def total_liabilities(self) -> float:
        return (
            sum(d.notional for d in self.term_deposits)
            + sum(n.notional for n in self.nmd)
            + sum(i.notional for i in self.issued_debt)
        )

    def by_currency(self, currency: str) -> "BalanceSheet":
        return BalanceSheet(
            mortgages=[i for i in self.mortgages if i.currency == currency],
            term_deposits=[i for i in self.term_deposits if i.currency == currency],
            nmd=[i for i in self.nmd if i.currency == currency],
            bonds=[i for i in self.bonds if i.currency == currency],
            issued_debt=[i for i in self.issued_debt if i.currency == currency],
            swaps=[i for i in self.swaps if i.currency == currency],
        )
