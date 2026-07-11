# -*- coding: utf-8 -*-
"""
Cashout Payment Pro — Controllers
Full cycle:
  /cashout/pay      → 3-step wizard (GET)
  /cashout/submit   → receive proof, notify admin (POST)
  /cashout/verify   → SMS relay webhook (JSON POST)
  /cashout/stats    → backend dashboard stats (JSON)
"""
import base64
import logging

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request

_logger = logging.getLogger(__name__)


class CashoutController(http.Controller):

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 1 landing: render the 3-step wizard
    # Called after Odoo auto-submits the redirect form
    # ─────────────────────────────────────────────────────────────────────────
    @http.route('/cashout/pay', type='http', auth='public', website=True, csrf=False)
    def payment_page(self, ref=None, **kwargs):

        # ── Locate provider ───────────────────────────────────────────────────
        provider = request.env['payment.provider'].sudo().search(
            [('code', '=', 'cashout_pro'), ('state', '!=', 'disabled')],
            limit=1,
        )
        if not provider:
            return request.render('cashout_payment_pro.cashout_error_page', {
                'error': 'Cashout payment is not configured. Please contact the store.',
            })

        # ── Find transaction ───────────────────────────────────────────────────
        tx_sudo = None
        if ref:
            tx_sudo = request.env['payment.transaction'].sudo().search(
                [('reference', '=', ref)], limit=1,
            )

        return request.render('cashout_payment_pro.cashout_payment_page', {
            'tx':                   tx_sudo,
            'ref':                  ref or '',
            'provider':             provider,
            'methods':              self._build_methods_data(provider, tx_sudo),
            'footer_note':          provider.cashout_footer_note or '',
        })

    # ─────────────────────────────────────────────────────────────────────────
    # Helper: build the per-method context (QR, agent number, rendered steps)
    # shared by the initial payment page and the error-reload path.
    # ─────────────────────────────────────────────────────────────────────────
    def _build_methods_data(self, provider, tx_sudo):
        def _b64_to_data_uri(field_val):
            if not field_val:
                return ''
            raw = field_val if isinstance(field_val, str) else field_val.decode('utf-8')
            return 'data:image/png;base64,' + raw

        amount_str = ''
        if tx_sudo:
            amount_str = '{:,.2f} {}'.format(tx_sudo.amount, tx_sudo.currency_id.symbol or '')

        methods = request.env['cashout.payment.method'].sudo().search([
            ('provider_id', '=', provider.id), ('active', '=', True),
        ])
        return [{
            'code':         m.code,
            'name':         m.name,
            'color':        m.color or '#6B4EFF',
            'agent_number': m._effective_agent_number(),
            'instructions': m.instructions or '',
            'steps':        m._rendered_steps(amount_str),
            'qr_src':       _b64_to_data_uri(m.qr_code),
            'logo_src':     _b64_to_data_uri(m.logo),
        } for m in methods]

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 3 submit: receive proof from customer
    # ─────────────────────────────────────────────────────────────────────────
    @http.route(
        '/cashout/submit',
        type='http',
        auth='public',
        methods=['POST'],
        website=True,
        csrf=False,
    )
    def submit_payment(self, **post):
        ref    = (post.get('ref')    or '').strip()
        method = (post.get('method') or '').strip()
        txn_id   = (post.get('txn_id')   or '').strip()
        sender   = (post.get('sender')   or '').strip()
        note     = (post.get('note')     or '').strip()
        sms_text = (post.get('sms_text') or '').strip()

        # Validate the submitted method against the actually configured,
        # active cashout methods (bKash, Nagad, Rocket, Upay, or anything
        # else the admin has added) rather than a hardcoded pair.
        valid_codes = request.env['cashout.payment.method'].sudo().search([
            ('active', '=', True),
        ]).mapped('code')
        if method not in valid_codes:
            method = valid_codes[0] if valid_codes else method

        # ── Screenshot upload (read before validation so rules can check it) ────
        screenshot_b64  = False
        screenshot_name = False
        upload = request.httprequest.files.get('screenshot')
        if upload and upload.filename:
            data = upload.read()
            if data:
                screenshot_b64  = base64.b64encode(data)
                screenshot_name = upload.filename

        # ── Validate fields ────────────────────────────────────────────────────
        # Each proof field (Transaction ID, Sender, Screenshot, SMS Text) is
        # individually optional, but at least one of them must be provided.
        if not (txn_id or sender or screenshot_b64 or sms_text):
            return self._reload_pay_page(
                ref,
                'Please provide at least one proof of payment: Transaction ID, '
                'sending number, screenshot, or the confirmation SMS text.',
            )

        # ── Update transaction ─────────────────────────────────────────────────
        tx_sudo = None
        if ref:
            tx_sudo = request.env['payment.transaction'].sudo().search(
                [('reference', '=', ref)], limit=1,
            )

        if tx_sudo:
            vals = {
                'cashout_method':           method,
                'cashout_txn_id':           txn_id,
                'cashout_sender':           sender,
                'cashout_customer_note':    note,
                'cashout_screenshot':       screenshot_b64,
                'cashout_screenshot_name':  screenshot_name,
                'cashout_sms_text':         sms_text,
                'cashout_status':           'screenshot_uploaded',
            }
            try:
                tx_sudo.write(vals)
            except UserError as e:
                # Raised by the Transaction ID uniqueness constraint — surface
                # it to the customer instead of silently failing through to
                # the "submitted" success page.
                return self._reload_pay_page(ref, str(e))
            except Exception as e:
                _logger.error('Cashout: failed to write transaction %s: %s', ref, e)
            else:
                # Move Odoo state draft → pending so that admin's _set_done()
                # works correctly. _set_done() silently does nothing on 'draft'.
                if tx_sudo.state == 'draft':
                    try:
                        tx_sudo._set_pending()
                    except Exception as e:
                        _logger.warning('Cashout submit: _set_pending for %s: %s', ref, e)
                tx_sudo.message_post(
                    body=(
                        f'&#128228; Customer submitted payment proof.<br/>'
                        f'Method: <b>{method.upper()}</b> | '
                        f'Txn ID: <b>{txn_id or "—"}</b> | '
                        f'Sender: <b>{sender or "—"}</b>'
                        + (f'<br/>Screenshot: {screenshot_name}' if screenshot_name else '')
                        + (f'<br/>SMS Text: {sms_text}' if sms_text else '')
                    ),
                    message_type='notification',
                )

            # Notify admin
            try:
                tx_sudo._cashout_notify_admin()
            except Exception as e:
                _logger.warning('Cashout: admin notification failed: %s', e)
        else:
            _logger.warning('Cashout: no transaction found for ref=%s', ref)

        method_rec = request.env['cashout.payment.method'].sudo().search(
            [('code', '=', method)], limit=1,
        )
        return request.render('cashout_payment_pro.cashout_success_page', {
            'ref':          ref,
            'method':       method,
            'method_name':  method_rec.name if method_rec else (method or '—'),
            'method_color': method_rec.color if method_rec else '#6B4EFF',
            'txn_id':       txn_id,
        })

    # ─────────────────────────────────────────────────────────────────────────
    # Helper: reload payment page with error
    # ─────────────────────────────────────────────────────────────────────────
    def _reload_pay_page(self, ref, error_msg):
        provider = request.env['payment.provider'].sudo().search(
            [('code', '=', 'cashout_pro'), ('state', '!=', 'disabled')], limit=1,
        )
        tx_sudo = None
        if ref:
            tx_sudo = request.env['payment.transaction'].sudo().search(
                [('reference', '=', ref)], limit=1,
            )

        methods_data = self._build_methods_data(provider, tx_sudo) if provider else []

        return request.render('cashout_payment_pro.cashout_payment_page', {
            'tx':                   tx_sudo,
            'ref':                  ref,
            'provider':             provider,
            'methods':              methods_data,
            'footer_note':          provider.cashout_footer_note if provider else '',
            'error':                error_msg,
        })

    # ─────────────────────────────────────────────────────────────────────────
    # SMS relay webhook (optional Android app)
    # ─────────────────────────────────────────────────────────────────────────
    @http.route('/cashout/verify', type='json', auth='public', methods=['POST'], csrf=False)
    def verify_sms(self, **data):
        provider = request.env['payment.provider'].sudo().search(
            [('code', '=', 'cashout_pro')], limit=1,
        )
        expected = provider.cashout_secret_token if provider else 'CASHOUT_ASHRAF_SECRET_2024'
        if data.get('token') != expected:
            _logger.warning('Cashout SMS webhook: unauthorized')
            return {'error': 'unauthorized'}

        raw_sms = data.get('raw_sms', '')
        if not raw_sms:
            return {'error': 'empty_sms'}

        SmsLog = request.env['cashout.sms.log'].sudo()
        parsed  = SmsLog.parse_sms(raw_sms)
        log = SmsLog.create({
            'raw_sms':       raw_sms,
            'source_number': data.get('source', ''),
            'parsed_txn':    parsed['txn'],
            'parsed_amount': parsed['amount'],
            'parsed_sender': parsed['sender'],
            'parsed_method': parsed['method'],
            'state':         'new',
        })

        matched_tx = None
        if parsed['amount'] > 0:
            pending = request.env['payment.transaction'].sudo().search([
                ('state', '=', 'pending'),
                ('provider_code', '=', 'cashout_pro'),
                ('amount', '=', parsed['amount']),
            ], limit=10)

            for tx in pending:
                txn_ok    = parsed['txn']    and tx.cashout_txn_id == parsed['txn']
                sender_ok = parsed['sender'] and tx.cashout_sender and parsed['sender'][-4:] in tx.cashout_sender
                if txn_ok or sender_ok:
                    tx.cashout_verified = True
                    tx.cashout_status   = 'sms_matched'
                    tx.sms_log_id       = log.id
                    try:
                        tx._set_done()
                    except Exception as e:
                        _logger.warning('SMS match _set_done: %s', e)
                    log.write({'matched': True, 'state': 'matched', 'match_transaction_id': tx.id})
                    matched_tx = tx
                    break

        if matched_tx:
            return {'status': 'matched', 'transaction': matched_tx.reference, 'amount': parsed['amount']}
        log.state = 'unmatched'
        return {'status': 'not_matched', 'parsed': parsed}

    # ─────────────────────────────────────────────────────────────────────────
    # Backend dashboard stats
    # ─────────────────────────────────────────────────────────────────────────
    @http.route('/cashout/stats', type='json', auth='user')
    def dashboard_stats(self):
        SmsLog = request.env['cashout.sms.log'].sudo()
        Tx     = request.env['payment.transaction'].sudo()
        base   = [('provider_code', '=', 'cashout_pro')]
        return {
            'sms_total':     SmsLog.search_count([]),
            'sms_matched':   SmsLog.search_count([('matched', '=', True)]),
            'sms_unmatched': SmsLog.search_count([('state', '=', 'unmatched')]),
            'tx_pending':    Tx.search_count(base + [('cashout_status', '=', 'screenshot_uploaded')]),
            'tx_confirmed':  Tx.search_count(base + [('cashout_status', '=', 'confirmed')]),
            'tx_rejected':   Tx.search_count(base + [('cashout_status', '=', 'rejected')]),
            'tx_total':      Tx.search_count(base),
        }
