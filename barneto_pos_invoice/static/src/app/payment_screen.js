import { patch } from "@web/core/utils/patch";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";

patch(PaymentScreen.prototype, {
    _hasBarnetoPayLaterPayment() {
        return this.currentOrder.payment_ids.some(
            (payment) => payment.payment_method_id.type === "pay_later"
        );
    },

    async addNewPaymentLine(paymentMethod) {
        const result = await super.addNewPaymentLine(...arguments);
        if (result && paymentMethod.type === "pay_later") {
            this.currentOrder.set_to_invoice(true);
        }
        return result;
    },

    async validateOrder(...args) {
        if (this._hasBarnetoPayLaterPayment()) {
            this.currentOrder.set_to_invoice(true);
        }
        return super.validateOrder(...args);
    },

    toggleIsToInvoice() {
        if (this._hasBarnetoPayLaterPayment()) {
            this.currentOrder.set_to_invoice(true);
            return;
        }
        return super.toggleIsToInvoice(...arguments);
    },

    disableBarnetoInvoiceButton() {
        return this._hasBarnetoPayLaterPayment();
    },
});
