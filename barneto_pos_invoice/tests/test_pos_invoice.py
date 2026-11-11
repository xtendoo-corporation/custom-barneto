import odoo
from odoo.tests import Form
from odoo.tools import float_compare

from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@odoo.tests.tagged("post_install", "-at_install")
class TestBarnetoPosInvoice(TestPoSCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.basic_config
        cls.barneto_product = cls.create_product(
            "Barneto product", cls.categ_basic, 100, 100
        )

    def _create_order(self, payments, customer=None, is_invoiced=False):
        self.config.write(
            {"payment_method_ids": [(6, 0, (self.pay_later_pm | self.cash_pm1).ids)]}
        )
        self.open_new_session()
        return self._create_orders(
            [
                {
                    "pos_order_lines_ui_args": [(self.barneto_product, 1)],
                    "payments": payments,
                    "customer": customer,
                    "is_invoiced": is_invoiced,
                    "uuid": self.create_random_uid(),
                }
            ]
        ).popitem()[1]

    def _close_current_session(self):
        session = self.config.current_session_id
        cash_amount = sum(
            session.order_ids.payment_ids.filtered(
                lambda payment: payment.payment_method_id.is_cash_count
            ).mapped("amount")
        )
        session.post_closing_cash_details(cash_amount)
        session.close_session_from_ui()
        return session

    def test_pay_later_payment_marks_order_to_invoice(self):
        order = self._create_order(
            [(self.pay_later_pm, 100)],
            customer=self.customer,
            is_invoiced=False,
        )

        self.assertTrue(order.to_invoice)
        self.assertTrue(order.account_move)
        self.assertEqual(order.state, "invoiced")

    def test_closed_order_invoice_reverses_session_sale_once(self):
        order = self._create_order(
            [(self.cash_pm1, 100)],
            customer=self.customer,
            is_invoiced=False,
        )
        session = self._close_current_session()

        self.assertEqual(order.state, "done")
        self.assertFalse(order.account_move)

        order.with_context(generate_pdf=False).action_barneto_invoice_order()

        self.assertTrue(order.account_move)
        self.assertEqual(order.state, "invoiced")
        reversal_moves = self.env["account.move"].search(
            [("reversed_pos_order_id", "=", order.id)]
        )
        self.assertEqual(
            len(reversal_moves),
            1,
        )
        revenue_moves = session.move_id | reversal_moves | order.account_move
        revenue_balance = sum(
            revenue_moves.line_ids.filtered(
                lambda line: line.account_id == self.sales_account
            ).mapped("balance")
        )
        self.assertEqual(
            float_compare(
                revenue_balance,
                -100,
                precision_rounding=self.env.company.currency_id.rounding,
            ),
            0,
        )

    def test_pay_later_invoice_keeps_customer_balance_correct(self):
        order = self._create_order(
            [(self.cash_pm1, 40), (self.pay_later_pm, 60)],
            customer=self.customer,
            is_invoiced=False,
        )

        invoice = order.account_move
        self.assertEqual(invoice.state, "posted")
        self.assertEqual(
            float_compare(
                invoice.amount_residual,
                60,
                precision_rounding=invoice.currency_id.rounding,
            ),
            0,
        )

        receivable_lines = invoice.line_ids.filtered(
            lambda line: line.account_id == self.customer.property_account_receivable_id
        )
        self.assertTrue(receivable_lines)
        self.assertTrue(any(line.amount_residual > 0 for line in receivable_lines))

    def test_cash_order_without_customer_is_not_marked_for_invoice(self):
        order = self._create_order(
            [(self.cash_pm1, 100)],
            customer=False,
            is_invoiced=False,
        )

        self.assertFalse(order.to_invoice)
        self.assertFalse(order.account_move)

    def test_invoice_can_be_paid_in_two_posted_payments(self):
        order = self._create_order(
            [(self.cash_pm1, 40), (self.pay_later_pm, 60)],
            customer=self.customer,
            is_invoiced=False,
        )
        invoice = order.account_move

        with Form(
            self.env["account.payment.register"].with_context(
                active_model="account.move",
                active_ids=invoice.ids,
            )
        ) as payment_register:
            payment_register.amount = 30
        payment_register.save().action_create_payments()
        self.assertEqual(invoice.payment_state, "partial")
        self.assertEqual(
            float_compare(
                invoice.amount_residual,
                30,
                precision_rounding=invoice.currency_id.rounding,
            ),
            0,
        )

        with Form(
            self.env["account.payment.register"].with_context(
                active_model="account.move",
                active_ids=invoice.ids,
            )
        ) as payment_register:
            payment_register.amount = 30
        payment_register.save().action_create_payments()

        self.assertEqual(invoice.payment_state, "paid")
        self.assertTrue(invoice.currency_id.is_zero(invoice.amount_residual))

    def test_invoice_payment_from_open_pos_session_is_reconciled(self):
        order = self._create_order(
            [(self.pay_later_pm, 100)],
            customer=self.customer,
            is_invoiced=False,
        )
        invoice = order.account_move
        session = self.config.current_session_id

        result = order.action_barneto_pay_invoice(
            session.id,
            self.cash_pm1.id,
            40,
        )

        payment_order = self.env["pos.order"].browse(
            result["payment_order_id"]
        )
        payment = payment_order.payment_ids
        self.assertTrue(payment_order.barneto_invoice_payment_id)
        self.assertEqual(payment_order.session_id, session)
        self.assertEqual(payment.amount, 40)
        self.assertTrue(payment.account_move_id)
        self.assertEqual(invoice.amount_residual, 60)
        self.assertEqual(invoice.payment_state, "partial")

        closing_data = session.get_closing_control_data()
        self.assertEqual(
            closing_data["default_cash_details"]["payment_amount"],
            40,
        )

        self._close_current_session()

        self.assertTrue(session.move_id)
        self.assertTrue(payment.account_move_id.line_ids.filtered(
            lambda line: line.account_id
            == self.env.company.account_default_pos_receivable_account_id
            and line.reconciled
        ))
        self.assertEqual(invoice.amount_residual, 60)
