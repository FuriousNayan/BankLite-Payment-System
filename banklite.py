"""
BankLite — starter code for the Stubs & Mocks exercise.
DO NOT modify this file. Write all tests in test_banklite.py.
"""
from dataclasses import dataclass, field
from typing import List, Optional



# ── Data models ─────────────────────────────────────────────
@dataclass
class Transaction:
    tx_id:    str
    user_id:  int
    amount:   float
    currency: str = "USD"
    status:   str = "pending"

@dataclass
class FraudCheckResult:
    approved:     bool
    risk_score:   float       # 0.0 (safe) – 1.0 (certain fraud)
    reason:       str = ""


# ── Collaborator interfaces (the real ones hit external systems)
class PaymentGateway:
    def charge(self, tx: Transaction) -> bool:
        """Returns True if charge succeeded, False otherwise."""
        raise NotImplementedError

class FraudDetector:
    def check(self, tx: Transaction) -> FraudCheckResult:
        """Returns fraud check result. May raise ConnectionError."""
        raise NotImplementedError

class EmailClient:
    def send_receipt(self, user_id: int, tx_id: str, amount: float) -> None:
        """Sends an email receipt to the user."""
        raise NotImplementedError

    def send_fraud_alert(self, user_id: int, tx_id: str) -> None:
        """Sends a fraud alert email."""
        raise NotImplementedError

class AuditLog:
    def record(self, event: str, tx_id: str, details: dict) -> None:
        """Persists an audit event to the database."""
        raise NotImplementedError


# ── Task 1: PaymentProcessor ─────────────────────────────────
class PaymentProcessor:
    """Processes a payment: validates, charges, and records."""

    MAX_AMOUNT = 10_000.00

    def __init__(self, gateway: PaymentGateway, audit: AuditLog):
        self._gateway = gateway
        self._audit   = audit

    def process(self, tx: Transaction) -> str:
        """
        Processes the transaction.
        Returns: "success", "declined", or raises ValueError.
        """
        if tx.amount <= 0:
            raise ValueError(f"Invalid amount: {tx.amount}")
        if tx.amount > self.MAX_AMOUNT:
            raise ValueError(f"Amount exceeds limit: {tx.amount}")

        success = self._gateway.charge(tx)

        if success:
            self._audit.record("CHARGED", tx.tx_id, {"amount": tx.amount})
            return "success"
        else:
            self._audit.record("DECLINED", tx.tx_id, {"amount": tx.amount})
            return "declined"


# ── Task 2: FraudAwareProcessor ──────────────────────────────
class FraudAwareProcessor:
    """Extends payment processing with fraud checking."""

    FRAUD_THRESHOLD = 0.75

    def __init__(
        self,
        gateway:  PaymentGateway,
        detector: FraudDetector,
        mailer:   EmailClient,
        audit:    AuditLog,
    ):
        self._gateway  = gateway
        self._detector = detector
        self._mailer   = mailer
        self._audit    = audit

    def process(self, tx: Transaction) -> str:
        """
        Checks for fraud first. If risk score >= FRAUD_THRESHOLD:
          - Does NOT charge the card
          - Sends a fraud alert email
          - Audits the block
          - Returns "blocked"
        Otherwise:
          - Charges the card
          - Sends a receipt email on success
          - Audits the result
          - Returns "success" or "declined"
        """
        result = self._detector.check(tx)

        if result.risk_score >= self.FRAUD_THRESHOLD:
            self._mailer.send_fraud_alert(tx.user_id, tx.tx_id)
            self._audit.record("BLOCKED", tx.tx_id, {"risk": result.risk_score})
            return "blocked"

        charged = self._gateway.charge(tx)
        if charged:
            self._mailer.send_receipt(tx.user_id, tx.tx_id, tx.amount)
            self._audit.record("CHARGED", tx.tx_id, {"amount": tx.amount})
            return "success"
        else:
            self._audit.record("DECLINED", tx.tx_id, {"amount": tx.amount})
            return "declined"


# ── Task 3: StatementBuilder ─────────────────────────────────
class TransactionRepository:
    def find_by_user(self, user_id: int) -> List[Transaction]:
        raise NotImplementedError

class StatementBuilder:
    """Builds a financial statement for a user."""

    def __init__(self, repo: TransactionRepository):
        self._repo = repo

    def build(self, user_id: int) -> dict:
        """
        Returns a dict with:
          - transactions: list of Transaction objects
          - total_charged: sum of amounts for status == "success"
          - count: total number of transactions
        """
        txs = self._repo.find_by_user(user_id)
        total = sum(t.amount for t in txs if t.status == "success")
        return {
            "transactions":  txs,
            "total_charged": round(total, 2),
            "count":         len(txs),
        }

# ── Task 4: FeeCalculator + CheckoutService ──────────────────
class FeeCalculator:
    """Pure fee logic. No I/O. Safe to call in tests."""

    BASE_FEE_RATE   = 0.029   # 2.9%
    FIXED_FEE       = 0.30    # $0.30 per transaction
    INTL_SURCHARGE  = 0.015   # extra 1.5% for non-USD

    def processing_fee(self, amount: float, currency: str = "USD") -> float:
        """Returns the total processing fee for a transaction."""
        rate = self.BASE_FEE_RATE
        if currency != "USD":
            rate += self.INTL_SURCHARGE
        return round(amount * rate + self.FIXED_FEE, 2)

    def net_amount(self, amount: float, currency: str = "USD") -> float:
        """Returns the amount after fees are deducted."""
        fee = self.processing_fee(amount, currency)
        return round(amount - fee, 2)


class CheckoutService:
    """Orchestrates checkout: computes fees and builds a receipt."""

    def __init__(self, fee_calc: FeeCalculator, gateway: PaymentGateway):
        self._fee_calc = fee_calc
        self._gateway  = gateway

    def checkout(self, tx: Transaction) -> dict:
        """
        Computes the processing fee, charges the gateway, and
        returns a receipt dict with: amount, fee, net, status.
        """
        fee    = self._fee_calc.processing_fee(tx.amount, tx.currency)
        net    = self._fee_calc.net_amount(tx.amount, tx.currency)
        status = "success" if self._gateway.charge(tx) else "declined"
        return {
            "tx_id":  tx.tx_id,
            "amount": tx.amount,
            "fee":    fee,
            "net":    net,
            "status": status,
        }