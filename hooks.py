# -*- coding: utf-8 -*-
"""
Post-install / uninstall hooks for Cashout Payment Pro.
Ensures payment.method is created and linked to the provider
even when upgrading an existing installation.
"""
import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    _ensure_payment_method(env)


def uninstall_hook(env):
    method = env['payment.method'].search([('code', '=', 'cashout_pro')], limit=1)
    if method:
        # Unlink from providers first
        providers = env['payment.provider'].search([('code', '=', 'cashout_pro')])
        providers.write({'payment_method_ids': [(3, method.id)]})
        method.unlink()
        _logger.info('Cashout Pro: removed payment.method on uninstall')


def _ensure_payment_method(env):
    """Create and link payment.method if missing (safe to call on upgrade)."""
    PaymentMethod = env['payment.method']
    PaymentProvider = env['payment.provider']

    method = PaymentMethod.search([('code', '=', 'cashout_pro')], limit=1)
    if not method:
        vals = {
            'name': 'Cashout (Bkash / Nagad)',
            'code': 'cashout_pro',
            'sequence': 10,
            'active': True,
        }
        method = PaymentMethod.create(vals)
        _logger.info('Cashout Pro: created payment.method id=%s', method.id)

    # Link to all cashout_pro providers that don't already have it
    providers = PaymentProvider.search([('code', '=', 'cashout_pro')])
    for provider in providers:
        if method not in provider.payment_method_ids:
            provider.payment_method_ids = [(4, method.id)]
            _logger.info(
                'Cashout Pro: linked payment.method to provider %s (id=%s)',
                provider.name, provider.id,
            )
