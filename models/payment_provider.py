# -*- coding: utf-8 -*-
import base64
import logging
from io import BytesIO

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


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
    cashout_bkash_instructions = fields.Text(
        string='Bkash Instructions',
        default='Open bKash → Cashout → Scan QR or enter agent number → Enter amount → PIN → save Txn ID.',
    )
    cashout_nagad_instructions = fields.Text(
        string='Nagad Instructions',
        default='Open Nagad → Cash Out → Scan QR or enter agent number → Enter amount → PIN → save Txn ID.',
    )
    cashout_footer_note = fields.Char(
        string='Footer Note',
        default='Upload your payment screenshot. Order confirmed within minutes.',
    )

    # ── QR Codes ──────────────────────────────────────────────────────────────
    cashout_bkash_qr = fields.Binary(string='Bkash QR Code', compute='_compute_qr_codes', store=True)
    cashout_nagad_qr = fields.Binary(string='Nagad QR Code', compute='_compute_qr_codes', store=True)

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

    # ── QR Generation ─────────────────────────────────────────────────────────
    @api.depends('cashout_agent_number')
    def _compute_qr_codes(self):
        for rec in self:
            if rec.code != 'cashout_pro' or not rec.cashout_agent_number:
                rec.cashout_bkash_qr = False
                rec.cashout_nagad_qr = False
                continue
            agent = rec.cashout_agent_number
            rec.cashout_bkash_qr = self._generate_qr(f'bkash://cashout?to={agent}')
            rec.cashout_nagad_qr = self._generate_qr(f'nagad://cashout?to={agent}')

    @api.model
    def _generate_qr(self, content):
        try:
            import qrcode
            qr = qrcode.QRCode(version=1,
                               error_correction=qrcode.constants.ERROR_CORRECT_H,
                               box_size=8, border=3)
            qr.add_data(content)
            qr.make(fit=True)
            img = qr.make_image(fill_color='#1a1a1a', back_color='white')
            buf = BytesIO()
            img.save(buf, format='PNG')
            return base64.b64encode(buf.getvalue())
        except Exception as exc:
            _logger.warning('Cashout QR generation failed: %s', exc)
            return False

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
