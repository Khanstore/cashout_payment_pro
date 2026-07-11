# -*- coding: utf-8 -*-
import base64
import logging
import re
from io import BytesIO

from odoo import api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class CashoutPaymentMethod(models.Model):
    """A mobile-banking cashout method (bKash, Nagad, Rocket, Upay, ...).

    Admins can add/edit/deactivate these freely from
    Cashout Pro → Configuration → Payment Methods — no code changes needed.
    """
    _name = 'cashout.payment.method'
    _description = 'Cashout Payment Method'
    _order = 'sequence, id'

    name = fields.Char(string='Display Name', required=True, help='e.g. Rocket, Upay')
    code = fields.Char(
        string='Technical Code', required=True,
        help='Short lowercase code used internally and stored on transactions, e.g. "rocket". '
             'Cannot be changed once transactions exist.',
    )
    provider_id = fields.Many2one(
        'payment.provider', string='Provider', required=True,
        default=lambda self: self.env.ref(
            'cashout_payment_pro.payment_provider_cashout_pro', raise_if_not_found=False,
        ),
        ondelete='cascade',
    )
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(string='Active', default=True)
    agent_number = fields.Char(
        string='Agent / Merchant Number',
        help='Leave blank to reuse the provider\'s default agent number.',
    )
    color = fields.Char(
        string='Brand Color', default='#6B4EFF',
        help='Hex color used for this method\'s badge/card, e.g. #8C3AF5',
    )
    logo = fields.Binary(string='Logo (optional)', attachment=True)
    payment_steps = fields.Text(
        string='Payment Steps',
        help='One step per line — shown as the numbered "How to Pay" list. '
             'Use {agent} for the agent number and {amount} for the order '
             'amount due; both get substituted automatically. '
             'Leave blank to use the default generic steps.',
    )
    instructions = fields.Text(
        string='Extra Note',
        help='An additional highlighted note shown below the steps, e.g. '
             '"Only cashout from a personal account, not merchant."',
    )
    qr_code = fields.Binary(
        string='QR Code', compute='_compute_qr_code', inverse='_inverse_qr_code',
        store=True, readonly=False,
        help='Auto-generated from the agent number. You can also upload your own '
             'QR image (e.g. exported from the bKash/Nagad/Rocket merchant app) to '
             'override it — it will only be regenerated if you clear it or change '
             'the agent number.',
    )

    _DEFAULT_STEPS = [
        'Open your {name} app',
        'Tap Cashout',
        'Scan the QR code or enter agent: {agent}',
        'Enter the exact amount: {amount}',
        'Enter your PIN to confirm',
        'Save the Transaction ID from your SMS',
    ]

    _sql_constraints = [
        ('code_provider_uniq', 'unique(code, provider_id)',
         'This technical code is already used by another payment method on this provider.'),
    ]

    @api.constrains('code')
    def _check_code_format(self):
        for rec in self:
            if not rec.code or not re.match(r'^[a-z0-9_]+$', rec.code):
                raise ValidationError(
                    'Technical Code must contain only lowercase letters, numbers, '
                    'and underscores (e.g. "rocket", "upay").'
                )

    @api.depends('agent_number', 'provider_id.cashout_agent_number', 'code')
    def _compute_qr_code(self):
        for rec in self:
            agent = rec.agent_number or rec.provider_id.cashout_agent_number
            if not agent or not rec.code:
                rec.qr_code = False
                continue
            rec.qr_code = self._generate_qr(f'{rec.code}://cashout?to={agent}')

    def _inverse_qr_code(self):
        # No-op: allows the admin to manually upload/replace the QR image in
        # the UI. Odoo persists the assigned value directly since the field
        # is store=True; this inverse only exists so the field isn't locked
        # to the auto-computed value.
        pass

    def action_regenerate_qr(self):
        """Force-regenerate the QR code from the current agent number,
        discarding any manually-uploaded image."""
        for rec in self:
            agent = rec.agent_number or rec.provider_id.cashout_agent_number
            rec.qr_code = self._generate_qr(f'{rec.code}://cashout?to={agent}') if (agent and rec.code) else False

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

    def _effective_agent_number(self):
        self.ensure_one()
        return self.agent_number or self.provider_id.cashout_agent_number or ''

    def _rendered_steps(self, amount_str):
        """Return the list of step strings for this method, with {agent}/
        {amount}/{name} placeholders substituted. Falls back to a generic
        default list if the admin hasn't customized payment_steps."""
        self.ensure_one()
        raw_lines = [
            l.strip() for l in (self.payment_steps or '').split('\n') if l.strip()
        ]
        lines = raw_lines or self._DEFAULT_STEPS
        agent = self._effective_agent_number() or '—'
        subs = {'agent': agent, 'amount': amount_str or 'the amount shown above', 'name': self.name}
        rendered = []
        for line in lines:
            try:
                rendered.append(line.format(**subs))
            except (KeyError, IndexError, ValueError):
                # Admin used an unknown or malformed placeholder (e.g. a
                # stray "{") — show the line as-is rather than erroring out
                # the whole checkout page.
                rendered.append(line)
        return rendered
