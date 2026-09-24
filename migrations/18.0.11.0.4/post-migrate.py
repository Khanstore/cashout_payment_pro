# -*- coding: utf-8 -*-
"""Force-refresh Cashout Pro payment method/provider images on upgrade.

Odoo 18 payment.method uses `image` (64x64) and exposes the resized
`image_payment_form` field on checkout. `image_128` is not the payment.method
image field. The provider itself uses `image_128`.
"""
from odoo import SUPERUSER_ID
from odoo.modules.module import get_module_resource


def migrate(cr, version):
    if not version:
        return

    env = __import__('odoo').api.Environment(cr, SUPERUSER_ID, {})
    image_path = get_module_resource(
        'cashout_payment_pro', 'static', 'description', 'iconBK.png'
    )
    if not image_path:
        return

    with open(image_path, 'rb') as f:
        image = f.read()

    method = env.ref('cashout_payment_pro.payment_method_cashout_pro', raise_if_not_found=False)
    provider = env.ref('cashout_payment_pro.payment_provider_cashout_pro', raise_if_not_found=False)

    if method:
        method.write({'image': image})
    if provider:
        vals = {'image_128': image}
        if method and method not in provider.payment_method_ids:
            vals['payment_method_ids'] = [(4, method.id)]
        provider.write(vals)
