import unittest
from unittest.mock import MagicMock

# Assuming these are imported from your actual implementation:
from banklite import PaymentProcessor, FraudAwareProcessor, FraudCheckResult

class TestPaymentProcessor(unittest.TestCase):
    def setUp(self):
        self.gateway = MagicMock()
        self.audit = MagicMock()
        self.proc = PaymentProcessor(self.gateway, self.audit)

        self.tx = MagicMock()
        self.tx.tx_id = "tx_12345"
        self.tx.amount = 100.00
        

    def test_process_returns_success_when_gateway_charges(self):
        self.gateway.charge.return_value = True
        
        result = self.proc.process(self.tx)
        
        self.assertEqual(result, "success")

    def test_process_returns_declined_when_gateway_rejects(self):
        self.gateway.charge.return_value = False
        
        result = self.proc.process(self.tx)
        
        self.assertEqual(result, "declined")

    def test_process_raises_on_zero_amount(self):
        self.tx.amount = 0.00
        
        with self.assertRaises(ValueError):
            self.proc.process(self.tx)
            
        self.gateway.charge.assert_not_called()

    def test_process_raises_on_negative_amount(self):
        self.tx.amount = -0.01
        
        with self.assertRaises(ValueError):
            self.proc.process(self.tx)
            
        self.gateway.charge.assert_not_called()

    def test_process_raises_when_amount_exceeds_limit(self):
        self.tx.amount = 10000.01
        
        with self.assertRaises(ValueError):
            self.proc.process(self.tx)
            
        self.gateway.charge.assert_not_called()

    def test_process_accepts_amount_at_max_limit(self):
        self.tx.amount = 10000.00
        self.gateway.charge.return_value = True
        
        result = self.proc.process(self.tx)
        
        self.assertEqual(result, "success")
        self.gateway.charge.assert_called_once()

    def test_audit_records_charged_event_on_success(self):
        self.gateway.charge.return_value = True
        
        self.proc.process(self.tx)
        
        self.audit.record.assert_called_once_with(
            "CHARGED", self.tx.tx_id, {"amount": self.tx.amount}
        )

    def test_audit_records_declined_event_on_failure(self):
        self.gateway.charge.return_value = False
        
        self.proc.process(self.tx)
        
        self.audit.record.assert_called_once_with(
            "DECLINED", self.tx.tx_id, {"amount": self.tx.amount}
        )


class TestFraudAwareProcessor(unittest.TestCase):
    def setUp(self):
        self.gateway =  MagicMock()
        self.mailer =   MagicMock()
        self.detector = MagicMock()
        self.audit   =  MagicMock()
        self.proc    = FraudAwareProcessor(self.gateway, self.detector, self.mailer, self.audit)

        # making own data here to use for magicmock
        self.tx = MagicMock()
        self.tx.tx_id = "tx_98765"
        self.tx.user_id = 42
        self.tx.amount = 150.00

    def _safe_result(self, risk_score=0.1):
        return FraudCheckResult(approved=True, risk_score=risk_score)

    def _fraud_result(self, risk_score=0.9):
        return FraudCheckResult(approved=False, risk_score=risk_score)

    
    def test_high_risk_returns_blocked(self):
        self.detector.check.return_value = self._fraud_result(0.8)
        result = self.proc.process(self.tx)
        self.assertEqual(result, "blocked")
        self.gateway.charge.assert_not_called()

    def test_exactly_at_threshold_is_treated_as_fraud(self):
        self.detector.check.return_value = self._fraud_result(0.75)
        result = self.proc.process(self.tx)
        self.assertEqual(result, "blocked")
        self.gateway.charge.assert_not_called()

    def test_low_risk_successful_charge_logic(self):
        self.detector.check.return_value = self._safe_result(0.1)
        self.gateway.charge.return_value = True
        
        result = self.proc.process(self.tx)
        
        self.assertEqual(result, "success")
        self.mailer.send_receipt.assert_called_once_with(self.tx.user_id, self.tx.tx_id, self.tx.amount)
        self.audit.record.assert_called_once_with("CHARGED", self.tx.tx_id, {"amount": self.tx.amount})

    def test_low_risk_declined_charge_logic(self):
        self.detector.check.return_value = self._safe_result(0.1)
        self.gateway.charge.return_value = False
        
        result = self.proc.process(self.tx)
        
        self.assertEqual(result, "declined")
        self.mailer.send_receipt.assert_not_called()
        self.audit.record.assert_called_once_with("DECLINED", self.tx.tx_id, {"amount": self.tx.amount})

    def test_fraud_detector_connection_error_propagates(self):
        self.detector.check.side_effect = ConnectionError("API down")
        with self.assertRaises(ConnectionError):
            self.proc.process(self.tx)
        self.gateway.charge.assert_not_called()

    def test_fraud_alert_email_args(self):
        self.detector.check.return_value = self._fraud_result(0.9)
        self.proc.process(self.tx)
        self.mailer.send_fraud_alert.assert_called_once_with(self.tx.user_id, self.tx.tx_id)

    def test_receipt_email_args(self):
        self.detector.check.return_value = self._safe_result(0.1)
        self.gateway.charge.return_value = True
        self.proc.process(self.tx)
        self.mailer.send_receipt.assert_called_once_with(self.tx.user_id, self.tx.tx_id, self.tx.amount)

class TestStatementBuilder(unittest.TestCase):
    def setUp(self):
        self.repo = MagicMock()
        self.builder = StatementBuilder(self.repo)

    def test_user_with_no_transactions(self):
        self.repo.find_by_user.return_value = []
        
        result = self.builder.build(user_id=1)
        
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["total_charged"], 0.0)
        self.assertEqual(result["transactions"], [])

    def test_user_with_only_success_transactions(self):
        txs = [
            Transaction("TX1", 99, 100.00, status="success"),
            Transaction("TX2", 99, 50.50,  status="success"),
        ]
        self.repo.find_by_user.return_value = txs
        
        result = self.builder.build(user_id=99)
        
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["total_charged"], 150.50)

    def test_user_with_mixed_statuses(self):
        txs = [
            Transaction("TX1", 99, 100.00, status="success"),
            Transaction("TX2", 99, 50.00,  status="declined"),
            Transaction("TX3", 99, 20.00,  status="pending"),
            Transaction("TX4", 99, 5.00,   status="success"),
        ]
        self.repo.find_by_user.return_value = txs
        
        result = self.builder.build(user_id=99)
        
        self.assertEqual(result["total_charged"], 105.00)
        self.assertEqual(result["count"], 4) 

    def test_rounding_to_two_decimal_places(self):
        txs = [
            Transaction("TX1", 3, 10.555, status="success"),
            Transaction("TX2", 3, 0.005,  status="success"),
        ]
        self.repo.find_by_user.return_value = txs
        
        result = self.builder.build(user_id=3)
        
        self.assertEqual(result["total_charged"], 10.56)

    def test_transactions_list_is_returned_as_is(self):
        txs = [Transaction("TX1", 4, 100.00, status="success")]
        self.repo.find_by_user.return_value = txs
        
        result = self.builder.build(user_id=4)
        
        self.assertIs(result["transactions"], txs)

if __name__ == "__main__":
    unittest.main()

