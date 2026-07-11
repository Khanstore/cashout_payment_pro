{
    'name': 'Cashout Payment Pro',
    'version': '18.0.11.0.0',
    'summary': 'Cashout/Pament from any MFS/Banking app,checkout selection, 3-step wizard, QR, screenshot, admin confirm manually',
    'description': '''
Cashout Payment Pro v7 — Full-featured mobile banking payment for Odoo 18.

FIXED in v7:
  • hooks.py now exported from __init__.py (hooks actually run)
  • is_primary removed from payment.method record (field does not exist in Odoo 18)
  • cashout_menu.xml moved AFTER action definitions (load-order fix)
  • All invisible= attributes use Odoo 18 domain syntax
  • _set_done() / _set_canceled() wrapped in try/except
  • Admin email notification when customer submits proof
  • cashout_status field now indexed for fast queries
  • QR base64 decode robustness fix

Customer Flow (3-Step Wizard):
  Step 1 — Select Bkash or Nagad
  Step 2 — Scan QR / copy agent number, complete payment in mobile app
  Step 3 — Enter Transaction ID, sending number, upload screenshot

Backend Workflow:
  Transactions list defaults to "Pending Review" filter
  Confirm / Reject in list row or form header
  Confirmation sends customer email + logs in chatter
  SMS Auto-Match via webhook (optional Android app)
    ''',
    'category': 'Payment',
    'author': 'Cashout Pro',
    'depends': ['payment', 'website', 'web', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        # payment_templates.xml must come first — it defines cashout_pro_redirect_form
        # which is referenced by ref= in payment_provider_data.xml. Loading data
        # before the template exists causes: External ID not found.
        'views/payment_templates.xml',
        'data/payment_provider_data.xml',
        'data/payment_method_data.xml',
        'data/email_template_cashout.xml',
        # Views with actions MUST load before menus that reference them
        'views/payment_provider_views.xml',
        'views/payment_method_views.xml',
        'views/payment_transaction_views.xml',
        'views/dashboard.xml',
        # Menu last — references actions defined in views above
        'views/cashout_menu.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'cashout_payment_pro/static/src/css/cashout_frontend.css',
        ],
        'web.assets_backend': [
            'cashout_payment_pro/static/src/css/cashout_backend.css',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
