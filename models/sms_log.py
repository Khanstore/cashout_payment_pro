# -*- coding: utf-8 -*-
import logging
import re

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class CashoutSmsLog(models.Model):
    _name = 'cashout.sms.log'
    _description = 'Cashout SMS Log'
    _order = 'create_date desc'
    _rec_name = 'parsed_txn'

    # ── Raw Data ───────────────────────────────────────────────────────────────
    raw_sms = fields.Text(
        string='Raw SMS Text',
        required=True,
    )
    source_number = fields.Char(
        string='SMS From',
        help='Phone number that sent the SMS relay.',
    )

    # ── Parsed Fields ──────────────────────────────────────────────────────────
    parsed_txn = fields.Char(string='Transaction ID')
    parsed_amount = fields.Float(string='Amount (BDT)', digits=(12, 2))
    parsed_sender = fields.Char(string='Sender Number')
    parsed_method = fields.Selection(
        selection=[('bkash', 'Bkash'), ('nagad', 'Nagad'), ('unknown', 'Unknown')],
        string='Method',
        default='unknown',
    )

    # ── Match Status ───────────────────────────────────────────────────────────
    matched = fields.Boolean(string='Matched', default=False)
    match_transaction_id = fields.Many2one(
        'payment.transaction',
        string='Matched Transaction',
        ondelete='set null',
    )

    # ── State ──────────────────────────────────────────────────────────────────
    state = fields.Selection(
        selection=[
            ('new', 'New'),
            ('matched', 'Matched'),
            ('unmatched', 'Unmatched'),
            ('ignored', 'Ignored'),
        ],
        string='State',
        default='new',
        index=True,
    )

    # ── Computed ───────────────────────────────────────────────────────────────
    method_badge_color = fields.Char(
        string='Badge Color',
        compute='_compute_badge_color',
    )

    @api.depends('parsed_method')
    def _compute_badge_color(self):
        colors = {'bkash': '#E2136E', 'nagad': '#F5A623', 'unknown': '#6c757d'}
        for rec in self:
            rec.method_badge_color = colors.get(rec.parsed_method, '#6c757d')

    # ── Parsing ────────────────────────────────────────────────────────────────
    @api.model
    def parse_sms(self, raw_sms):
        """
        Parse a Bkash/Nagad cashout SMS into structured fields.
        Returns a dict with keys: txn, amount, sender, method.
        """
        text = raw_sms or ''
        upper = text.upper()

        # Detect method
        if 'BKASH' in upper:
            method = 'bkash'
        elif 'NAGAD' in upper:
            method = 'nagad'
        else:
            method = 'unknown'

        # Extract transaction ID (6-16 uppercase alphanumeric chars)
        txn_match = re.search(r'\b([A-Z0-9]{6,16})\b', text)
        txn = txn_match.group(1) if txn_match else ''

        # Extract amount (digits optionally followed by decimal)
        amount_match = re.search(r'(?:Tk\.?|BDT|Amount:?)\s*([\d,]+(?:\.\d{1,2})?)', text, re.IGNORECASE)
        if not amount_match:
            amount_match = re.search(r'([\d,]+(?:\.\d{1,2})?)\s*(?:Tk|BDT|taka)', text, re.IGNORECASE)
        if not amount_match:
            # fallback: first bare number >= 10
            amount_match = re.search(r'\b(\d{2,}(?:\.\d{1,2})?)\b', text)
        amount_str = amount_match.group(1).replace(',', '') if amount_match else '0'
        try:
            amount = float(amount_str)
        except ValueError:
            amount = 0.0

        # Extract BD mobile number (01x xxxxxxxx)
        sender_match = re.search(r'(01[3-9]\d{8})', text)
        sender = sender_match.group(1) if sender_match else ''

        return {
            'txn': txn,
            'amount': amount,
            'sender': sender,
            'method': method,
        }

    # ── Actions ────────────────────────────────────────────────────────────────
    def action_ignore(self):
        self.write({'state': 'ignored'})

    def action_retry_match(self):
        """Try to match this log against pending transactions again."""
        for rec in self:
            if rec.matched:
                continue
            tx = self.env['payment.transaction'].sudo().search([
                ('state', '=', 'pending'),
                ('provider_code', '=', 'cashout_pro'),
                ('amount', '=', rec.parsed_amount),
            ], limit=10)
            for t in tx:
                if (
                    (rec.parsed_txn and t.cashout_txn_id == rec.parsed_txn)
                    or (rec.parsed_sender and t.cashout_sender
                        and rec.parsed_sender[-4:] in t.cashout_sender)
                ):
                    t.cashout_verified = True
                    t.cashout_status = 'sms_matched'
                    t.sms_log_id = rec.id
                    t._set_done()
                    rec.write({
                        'matched': True,
                        'state': 'matched',
                        'match_transaction_id': t.id,
                    })
                    break
            else:
                rec.state = 'unmatched'
