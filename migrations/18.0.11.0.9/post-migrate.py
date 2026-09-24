from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    methods = env['cashout.payment.method'].search([
        ('provider_id.code', '=', 'cashout_pro'),
    ])
    if methods:
        methods._sync_odoo_brands()
