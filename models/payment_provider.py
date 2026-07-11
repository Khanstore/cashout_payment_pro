# -*- coding: utf-8 -*-
from odoo import api, fields, models


class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    code = fields.Selection(
        selection_add=[('cashout_pro', 'Cashout Pro (Bkash/Nagad)')],
        ondelete={'cashout_pro': 'set default'},
    )

    # ── Agent / Config ────────────────────────────────────────────────────────
    cashout_agent_number = fields.Char(
        string='Agent Number',
        default='01970569256',
    )
    cashout_secret_token = fields.Char(
        string='SMS Webhook Secret',
        default='CASHOUT_ASHRAF_SECRET_2024',
    )
    cashout_footer_note = fields.Char(
        string='Footer Note',
        default='Upload your payment screenshot. Order confirmed within minutes.',
    )

    # ── Payment Methods (bKash, Nagad, Rocket, Upay, ...) ──────────────────────
    cashout_method_ids = fields.One2many(
        'cashout.payment.method', 'provider_id', string='Payment Methods',
    )

    # ── Capabilities ──────────────────────────────────────────────────────────
    @api.depends('code')
    def _compute_feature_support_fields(self):
        super()._compute_feature_support_fields()
        for rec in self.filtered(lambda p: p.code == 'cashout_pro'):
            rec.support_tokenization = False
            rec.support_manual_capture = False

    def _is_tokenization_required(self, **kwargs):
        if self.code == 'cashout_pro':
            return False
        return super()._is_tokenization_required(**kwargs)

    def _should_build_inline_form(self, is_validation=False):
        """
        Return False → Odoo will use redirect_form_view_id to get the form HTML,
        render it server-side, send it to JS, and JS will call form.submit().
        """
        if self.code == 'cashout_pro':
            return False
        return super()._should_build_inline_form(is_validation)

    # ── Redirect Flow ─────────────────────────────────────────────────────────
    def _get_specific_rendering_values(self, processing_values):
        """
        Called by Odoo after transaction creation.
        Returns values rendered into the redirect form template.

        We provide BOTH:
          - api_url / reference  → used by our QWeb template t-att-action="api_url"
          - redirect_url         → Odoo 18 JS fallback: if present it does window.location
        """
        res = super()._get_specific_rendering_values(processing_values)
        if self.code != 'cashout_pro':
            return res

        ref = processing_values.get('reference', '')
        cashout_url = f'/cashout/pay?ref={ref}'

        return {
            **res,
            'api_url':      cashout_url,   # used by the QWeb form template
            'reference':    ref,            # used by the hidden input
            'redirect_url': cashout_url,   # Odoo 18 JS direct-redirect fallback
        }

    def _get_redirect_form_view(self, is_validation=False):
        """
        Fallback in case redirect_form_view_id is not set on the DB record.
        redirect_form_view_id (set in XML data) is the primary mechanism;
        this method is the safety net.
        """
        if self.code == 'cashout_pro':
            # If redirect_form_view_id is already set on the record (from XML data), use it
            if self.redirect_form_view_id:
                return self.redirect_form_view_id
            # Otherwise look up by external id
            view = self.env.ref(
                'cashout_payment_pro.cashout_pro_redirect_form',
                raise_if_not_found=False,
            )
            if view:
                return view
        return super()._get_redirect_form_view(is_validation)
