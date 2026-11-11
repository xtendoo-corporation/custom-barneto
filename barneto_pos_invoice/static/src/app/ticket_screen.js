import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";
import { NumberPopup } from "@point_of_sale/app/utils/input_popups/number_popup";
import { SelectionPopup } from "@point_of_sale/app/utils/input_popups/selection_popup";
import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";

patch(TicketScreen.prototype, {
    setup() {
        super.setup(...arguments);
        this.barnetoPaymentLock = false;
        this.notification = this.env.services.notification;
    },

    isBarnetoInvoicePayable(order) {
        return Boolean(order?.raw.account_move && !order.raw.barneto_invoice_payment_id);
    },

    async payBarnetoInvoice(order) {
        if (!order || this.barnetoPaymentLock) {
            return;
        }

        this.barnetoPaymentLock = true;
        try {
            const invoiceId = order.raw.account_move;
            const invoiceData = await this.pos.data.read(
                "account.move",
                [invoiceId],
                ["amount_residual"],
                { load: false }
            );
            const residual = invoiceData[0]?.amount_residual || 0;
            if (!residual) {
                this.notification.add(_t("This invoice is already paid."), {
                    type: "warning",
                });
                return;
            }

            const paymentMethods = this.pos.config.payment_method_ids.filter(
                (paymentMethod) =>
                    ["cash", "bank"].includes(paymentMethod.type)
            );
            const paymentMethod = await makeAwaitable(
                this.dialog,
                SelectionPopup,
                {
                    title: _t("Select payment method"),
                    list: paymentMethods.map((method) => ({
                        id: method.id,
                        label: method.name,
                        item: method,
                    })),
                }
            );
            if (!paymentMethod) {
                return;
            }

            const amount = await makeAwaitable(this.dialog, NumberPopup, {
                title: _t("Payment amount"),
                startingValue: residual,
                isValid: (value) => {
                    const parsedAmount = Number(value);
                    return parsedAmount > 0 && parsedAmount <= residual;
                },
            });
            if (!amount) {
                return;
            }

            await this.pos.data.call("pos.order", "action_barneto_pay_invoice", [
                order.id,
                this.pos.session.id,
                paymentMethod.id,
                Number(amount),
            ]);
            this.notification.add(_t("Invoice payment registered."), {
                type: "success",
            });
        } catch (error) {
            this.notification.add(
                error?.message || _t("Unable to register the invoice payment."),
                { type: "danger" }
            );
        } finally {
            this.barnetoPaymentLock = false;
        }
    },
});
