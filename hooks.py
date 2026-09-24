# -*- coding: utf-8 -*-
"""
Post-install / uninstall hooks for Cashout Payment Pro.
Ensures payment.method is created and linked to the provider
even when upgrading an existing installation.
"""
import logging
import base64
import os

from odoo.modules.module import get_module_resource

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    _ensure_payment_method(env)
    _sync_cashout_brands(env)


def uninstall_hook(env):
    cashout_methods = env['cashout.payment.method'].search([])
    brands = cashout_methods.mapped('odoo_brand_id').exists()
    if brands:
        brands.unlink()
        _logger.info('Cashout Pro: removed %s configurable payment-method brands', len(brands))

    method = env['payment.method'].search([('code', '=', 'cashout_pro')], limit=1)
    if method:
        providers = env['payment.provider'].search([('code', '=', 'cashout_pro')])
        providers.write({'payment_method_ids': [(3, method.id)]})
        method.unlink()
        _logger.info('Cashout Pro: removed primary payment.method on uninstall')


def _ensure_payment_method(env):
    """Create and link payment.method if missing (safe to call on upgrade)."""
    PaymentMethod = env['payment.method']
    PaymentProvider = env['payment.provider']

    method = PaymentMethod.search([('code', '=', 'cashout_pro')], limit=1)
    if not method:
        image_path = get_module_resource(
            'cashout_payment_pro', 'static', 'description', 'iconBK.png'
        )
        image_b64 = False
        if image_path and os.path.isfile(image_path):
            with open(image_path, 'rb') as image_file:
                image_b64 = base64.b64encode(image_file.read())
        vals = {
            'name': 'Cashout',
            'code': 'cashout_pro',
            'sequence': 10,
            'active': True,
            'image': image_b64,
        }
        method = PaymentMethod.create(vals)
        _logger.info('Cashout Pro: created payment.method id=%s', method.id)

    # Repair the checkout logo on older installations where the module used
    # the provider's image_128 field instead of Odoo 18's payment.method.image.
    if not method.image:
        image_path = get_module_resource(
            'cashout_payment_pro', 'static', 'description', 'iconBK.png'
        )
        if image_path and os.path.isfile(image_path):
            with open(image_path, 'rb') as image_file:
                method.image = base64.b64encode(image_file.read())
            _logger.info('Cashout Pro: repaired payment method checkout image id=%s', method.id)

    # Link to all cashout_pro providers that don't already have it
    providers = PaymentProvider.search([('code', '=', 'cashout_pro')])
    for provider in providers:
        if method not in provider.payment_method_ids:
            provider.payment_method_ids = [(4, method.id)]
            _logger.info(
                'Cashout Pro: linked payment.method to provider %s (id=%s)',
                provider.name, provider.id,
            )


def _sync_cashout_brands(env):
    """Backfill/synchronize native Odoo brands for all configurable Cashout
    methods. This is also safe on upgrades from versions that hard-coded
    bKash/Nagad payment.method brand records.
    """
    methods = env['cashout.payment.method'].search([
        ('provider_id.code', '=', 'cashout_pro'),
    ])
    if methods:
        methods._sync_odoo_brands()
        _logger.info('Cashout Pro: synchronized %s configurable payment brands', len(methods))
