# -*- coding: utf-8 -*-
"""
Migration 18.0.10.0.0
Runs on every upgrade — fixes two issues on existing installations:
  1. Links payment.method ↔ payment.provider (fixes "no supported provider")
  2. Sets redirect_form_view_id on provider (fixes "Pay now does nothing")
"""
import logging
_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})

    method   = env['payment.method'].search([('code', '=', 'cashout_pro')], limit=1)
    provider = env['payment.provider'].search([('code', '=', 'cashout_pro')], limit=1)

    if not provider:
        _logger.warning('Cashout migrate: payment.provider not found — skipping')
        return

    # 1. Link method ↔ provider
    if method and method not in provider.payment_method_ids:
        provider.payment_method_ids = [(4, method.id)]
        _logger.info('Cashout migrate: linked method id=%s → provider id=%s', method.id, provider.id)

    # 2. Set redirect_form_view_id so Odoo knows to render & auto-submit our form
    form_view = env.ref(
        'cashout_payment_pro.cashout_pro_redirect_form',
        raise_if_not_found=False,
    )
    if form_view and not provider.redirect_form_view_id:
        provider.redirect_form_view_id = form_view.id
        _logger.info('Cashout migrate: set redirect_form_view_id=%s on provider id=%s',
                     form_view.id, provider.id)

    _logger.info('Cashout migration 18.0.10.0.0 complete')
