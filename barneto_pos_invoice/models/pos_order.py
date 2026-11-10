from odoo import _, models
from odoo.exceptions import UserError


class PosOrder(models.Model):
    _inherit = "pos.order"

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
