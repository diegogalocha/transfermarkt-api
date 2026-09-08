from datetime import date
from typing import Optional

from app.schemas.base import AuditMixin, TransfermarktBaseModel


class PlayerTransferClub(TransfermarktBaseModel):
    id: str
    name: str


class PlayerTransfer(TransfermarktBaseModel):
    id: str
    club_from: PlayerTransferClub
    club_to: PlayerTransferClub
    date: date
    upcoming: bool
    season: str
    market_value: Optional[int]
    fee: Optional[int]
    # Raw fee label from Transfermarkt (e.g. "End of loan", "loan transfer",
    # "free transfer", "€4.50m"). Preserved because `fee` is parsed to int and
    # loses the loan / end-of-loan distinction.
    fee_text: Optional[str] = None
    # Derived transfer type: "permanent" | "loan" | "loan_return" | "free".
    # None when it cannot be determined from the fee label.
    transfer_type: Optional[str] = None


class PlayerTransfers(TransfermarktBaseModel, AuditMixin):
    id: str
    transfers: list[PlayerTransfer]
    youth_clubs: Optional[list[str]]
