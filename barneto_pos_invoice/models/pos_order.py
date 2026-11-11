from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero


class PosOrder(models.Model):
    _inherit = "pos.order"

    barneto_invoice_payment_id = fields.Many2one(
        "account.move",
        string="Invoice paid in POS",
        readonly=True,
        copy=False,
    )

    @api.depends("account_move", "barneto_invoice_payment_id")
    def _compute_is_invoiced(self):
        super()._compute_is_invoiced()
        for order in self:
            if order.barneto_invoice_payment_id:
                order.is_invoiced = True

    def _has_pay_later_payment(self):
        self.ensure_one()
        return any(
            payment.payment_method_id.type == "pay_later"
            for payment in self.payment_ids
        )

    def _process_payment_lines(self, pos_order, order, pos_session, draft):
        result = super()._process_payment_lines(
            pos_order, order, pos_session, draft
        )
        if order._has_pay_later_payment():
            order.to_invoice = True
        return result

    def _barneto_invoice_skip_reason(self):
        self.ensure_one()
        if self.state != "done":
            return _("the order is not in Posted state")
        if not self.partner_id:
            return _("the order has no customer")
        if self.account_move:
            return _("the order is already invoiced")
        return False

    def action_barneto_invoice_order(self):
        self.ensure_one()
        reason = self._barneto_invoice_skip_reason()
        if reason:
            raise UserError(
                _("The order cannot be invoiced because %(reason)s.", reason=reason)
            )
        return self.action_pos_order_invoice()

    def action_barneto_invoice_selected(self):
        valid_orders = self.env["pos.order"]
        skipped = []
        for order in self:
            reason = order._barneto_invoice_skip_reason()
            if reason:
                skipped.append(
                    _("%(order)s: %(reason)s", order=order.name, reason=reason)
                )
            else:
                valid_orders |= order

        for order in valid_orders:
            order.with_context(generate_pdf=False).action_pos_order_invoice()

        if skipped:
            message = _(
                "Invoiced %(count)s order(s). Omitted order(s):\n%(orders)s",
                count=len(valid_orders),
                orders="\n".join(skipped),
            )
            notification_type = "warning"
        else:
            message = _("Invoiced %(count)s order(s).", count=len(valid_orders))
            notification_type = "success"

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Barneto POS invoicing"),
                "message": message,
                "type": notification_type,
                "sticky": bool(skipped),
            },
        }

    def action_barneto_pay_invoice(
        self, session_id, payment_method_id, amount
    ):
        self.ensure_one()
        if not self.account_move:
            raise UserError(_("The order has no invoice to pay."))

        invoice = self.account_move
        if invoice.state != "posted":
            raise UserError(_("The invoice must be posted before it can be paid."))

        if not invoice.partner_id:
            raise UserError(_("The invoice has no customer."))

        session = self.env["pos.session"].browse(session_id).exists()
        if (
            not session
            or session.state != "opened"
            or session.config_id != self.config_id
        ):
            raise UserError(
                _(
                    "Select an open session from the same point of sale "
                    "configuration as the ticket."
                )
            )

        payment_method = self.env["pos.payment.method"].browse(
            payment_method_id
        ).exists()
        if (
            not payment_method
            or payment_method not in session.config_id.payment_method_ids
            or payment_method.type not in ("cash", "bank")
        ):
            raise UserError(_("Select a cash or bank payment method."))

        amount = self.currency_id.round(float(amount))
        if float_is_zero(amount, precision_rounding=self.currency_id.rounding):
            raise UserError(_("The payment amount must be greater than zero."))
        if float_compare(
            amount,
            invoice.amount_residual,
            precision_rounding=invoice.currency_id.rounding,
        ) > 0:
            raise UserError(_("The payment exceeds the invoice residual."))

        payment_order = self.env["pos.order"].create(
            {
                "name": _("Payment of %s", invoice.name),
                "pos_reference": _("Payment of %s", invoice.name),
                "date_order": fields.Datetime.now(),
                "user_id": self.env.uid,
                "amount_tax": 0.0,
                "amount_total": 0.0,
                "amount_paid": 0.0,
                "amount_return": 0.0,
                "company_id": session.company_id.id,
                "pricelist_id": session.config_id.pricelist_id.id,
                "session_id": session.id,
                "partner_id": invoice.partner_id.id,
                "state": "draft",
                "barneto_invoice_payment_id": invoice.id,
            }
        )
        payment = self.env["pos.payment"].create(
            {
                "pos_order_id": payment_order.id,
                "amount": amount,
                "payment_method_id": payment_method.id,
                "payment_date": fields.Datetime.now(),
            }
        )
        payment_move = self._create_barneto_invoice_payment_move(
            payment, invoice
        )
        payment.write({"account_move_id": payment_move.id})
        payment_order.write({"amount_paid": amount, "state": "done"})
        self._reconcile_barneto_invoice_payment(invoice, payment_move)

        return {
            "invoice_id": invoice.id,
            "payment_order_id": payment_order.id,
            "amount_residual": invoice.amount_residual,
        }

    def _create_barneto_invoice_payment_move(self, payment, invoice):
        session = payment.pos_order_id.session_id
        accounting_partner = self.env["res.partner"]._find_accounting_partner(
            invoice.partner_id
        )
        amounts = session._update_amounts(
            {"amount": 0.0, "amount_converted": 0.0},
            {"amount": payment.amount},
            payment.payment_date,
        )
        payment_move = self.env["account.move"].with_context(
            default_journal_id=session.config_id.journal_id.id
        ).create(
            {
                "journal_id": session.config_id.journal_id.id,
                "date": fields.Date.context_today(payment.pos_order_id),
                "ref": _(
                    "Invoice payment for %(invoice)s using %(method)s",
                    invoice=invoice.name,
                    method=payment.payment_method_id.name,
                ),
            }
        )
        credit_line = session._credit_amounts(
            {
                "account_id": accounting_partner.with_company(
                    invoice.company_id
                ).property_account_receivable_id.id,
                "partner_id": accounting_partner.id,
                "move_id": payment_move.id,
            },
            amounts["amount"],
            amounts["amount_converted"],
        )
        debit_line = session._debit_amounts(
            {
                "account_id": (
                    invoice.company_id.account_default_pos_receivable_account_id.id
                ),
                "move_id": payment_move.id,
            },
            amounts["amount"],
            amounts["amount_converted"],
        )
        self.env["account.move.line"].create([credit_line, debit_line])
        payment_move.action_post()
        return payment_move

    def _reconcile_barneto_invoice_payment(self, invoice, payment_move):
        receivable_account = self.env["res.partner"]._find_accounting_partner(
            invoice.partner_id
        ).with_company(invoice.company_id).property_account_receivable_id
        invoice_lines = invoice.line_ids.filtered(
            lambda line: line.account_id == receivable_account
            and not line.reconciled
        )
        payment_lines = payment_move.line_ids.filtered(
            lambda line: line.account_id == receivable_account
            and not line.reconciled
        )
        if invoice_lines and payment_lines:
            (invoice_lines | payment_lines).reconcile()
