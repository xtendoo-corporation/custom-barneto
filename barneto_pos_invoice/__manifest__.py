{
    "name": "Barneto POS Invoice",
    "version": "18.0.1.0.0",
    "category": "Point of Sale",
    "summary": "Invoice Barneto POS orders paid on customer account",
    "description": """
Barneto Modas POS invoicing.

Orders paid with a customer-account payment method are always marked for
invoicing. Closed POS orders can also be invoiced from the backend without
duplicating the session sale.
""",
    "author": "Xtendoo Software SLU",
    "website": "https://www.xtendoo.es",
    "license": "LGPL-3",
    "depends": ["point_of_sale"],
    "data": [
        "views/pos_order_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "barneto_pos_invoice/static/src/app/payment_screen.js",
            "barneto_pos_invoice/static/src/app/payment_screen.xml",
            "barneto_pos_invoice/static/src/app/ticket_screen.js",
            "barneto_pos_invoice/static/src/app/ticket_screen.xml",
        ],
    },
    "installable": True,
    "auto_install": False,
}
