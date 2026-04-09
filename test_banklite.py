import unittest
from unittest.mock import MagicMock, patch

# Assuming these are imported from your actual implementation:
from banklite import (
    Transaction,         
    FraudCheckResult,    
    PaymentGateway,    
    FraudDetector,      
    EmailClient,         
    AuditLog,           
    TransactionRepository, 
    PaymentProcessor,    
    FraudAwareProcessor, 
    StatementBuilder,    
    FeeCalculator,
    CheckoutService,
)
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


class TestCheckoutServiceWithSpy(unittest.TestCase):
    def setUp(self):
        self.real_calc = FeeCalculator()
        self.spy_calc = MagicMock(wraps=self.real_calc)
        
        self.gateway = MagicMock()
        self.gateway.charge.return_value = True
        
        self.svc = CheckoutService(self.spy_calc, self.gateway)

        self.tx = MagicMock()
        self.tx.tx_id = "tx_spy_123"
        self.tx.amount = 100.00
        self.tx.currency = "USD"

    def test_usd_processing_fee_is_correct(self):
        receipt = self.svc.checkout(self.tx)
        
        self.assertEqual(receipt["fee"], 3.20)

    def test_international_fee_includes_surcharge(self):
        self.tx.amount = 200.00
        self.tx.currency = "EUR"
        
        receipt = self.svc.checkout(self.tx)
        
        self.assertEqual(receipt["fee"], 9.10)

    def test_net_amount_is_amount_minus_fee(self):
        receipt = self.svc.checkout(self.tx)
        
        self.assertEqual(receipt["net"], 96.80)

    def test_processing_fee_called_with_correct_amount_and_currency(self):
        self.svc.checkout(self.tx)
        
        self.spy_calc.processing_fee.assert_called_with(100.00, "USD")

    def test_net_amount_called_with_correct_amount_and_currency(self):
        self.svc.checkout(self.tx)
        
        self.spy_calc.net_amount.assert_called_with(100.00, "USD")

    def test_each_fee_method_called_exactly_once_per_checkout(self):
        self.svc.checkout(self.tx)
        
        self.assertEqual(self.spy_calc.processing_fee.call_count, 1)
        self.assertEqual(self.spy_calc.net_amount.call_count, 1)

    def test_spy_return_matches_fee_in_receipt(self):
        receipt = self.svc.checkout(self.tx)
        
        self.assertEqual(receipt["fee"], 3.20)

    def test_partial_spy_on_net_amount_only(self):
        real_calc = FeeCalculator()
        
        # Use the gateway from setUp
        svc = CheckoutService(real_calc, self.gateway)
        
        # Override the default tx amount for this specific test
        self.tx.amount = 500.00

        with patch.object(real_calc, "net_amount",
                        wraps=real_calc.net_amount) as spy_net:
            receipt = svc.checkout(self.tx)

        spy_net.assert_called_once_with(500.00, "USD")

        self.assertEqual(receipt["net"], 485.20)

    def test_contrast_mock_only_tests_wiring_not_formula(self):
        mock_calc = MagicMock()
        mock_calc.processing_fee.return_value = 5.00  
        mock_calc.net_amount.return_value = 95.00     

        gateway = MagicMock()
        gateway.charge.return_value = True

        svc = CheckoutService(mock_calc, gateway)
        receipt = svc.checkout(self.tx)

        self.assertEqual(receipt["fee"], 5.00)
        self.assertEqual(receipt["net"], 95.00)
if __name__ == "__main__":
    unittest.main()

