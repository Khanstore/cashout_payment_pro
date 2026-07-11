# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _name = 'payment.transaction'
    _inherit = ['payment.transaction', 'mail.thread', 'mail.activity.mixin']

    # ── Cashout Fields ─────────────────────────────────────────────────────────
    cashout_method = fields.Char(
        string='Cashout Method',
        help='Technical code of the payment method used (bkash, nagad, rocket, upay, ...).',
    )

    def _cashout_method_label(self):
        """Resolve the human-readable name for this transaction's cashout method,
        looking it up in the configurable cashout.payment.method records so any
        admin-added method (Rocket, Upay, ...) displays correctly."""
        self.ensure_one()
        if not self.cashout_method:
            return '—'
        method_rec = self.env['cashout.payment.method'].sudo().search(
            [('code', '=', self.cashout_method)], limit=1,
        )
        return method_rec.name if method_rec else self.cashout_method
    cashout_txn_id = fields.Char(
        string='Transaction ID', index=True,
        help='Transaction ID from the Bkash/Nagad confirmation SMS. Must be unique — '
             'the same Transaction ID cannot be used on more than one active order.',
    )

    @api.constrains('cashout_txn_id')
    def _check_cashout_txn_id_unique(self):
        for rec in self:
            txn_id = (rec.cashout_txn_id or '').strip()
            if not txn_id:
                continue
            duplicate = self.search([
                ('id', '!=', rec.id),
                ('cashout_txn_id', '=', txn_id),
                ('cashout_status', '!=', 'rejected'),
            ], limit=1)
            if duplicate:
                raise UserError(
                    f'Transaction ID "{txn_id}" has already been submitted on order '
                    f'{duplicate.reference}. Each Transaction ID can only be used once — '
                    'please double-check the ID from your SMS.'
                )
    cashout_sender = fields.Char(string='Sending Mobile Number')
    cashout_verified = fields.Boolean(string='Verified', default=False, copy=False)
    cashout_verified_by = fields.Char(
        string='Verified By', compute='_compute_verified_by', store=True,
    )
    cashout_confirmed_date = fields.Datetime(
        string='Confirmed On', readonly=True, copy=False,
    )
    cashout_screenshot = fields.Binary(
        string='Payment Screenshot', attachment=True, copy=False,
    )
    cashout_screenshot_name = fields.Char(string='Screenshot Filename')
    cashout_screenshot_url = fields.Char(
        string='Screenshot URL', compute='_compute_screenshot_url',
    )
    cashout_sms_text = fields.Text(
        string='Confirmation SMS',
        help='Raw bKash/Nagad confirmation SMS text pasted in by the customer, '
             'as an alternative or supplement to the screenshot proof.',
    )
    sms_log_id = fields.Many2one('cashout.sms.log', string='Matched SMS Log', copy=False)
    cashout_customer_note = fields.Text(string='Customer Note')
    cashout_status = fields.Selection(
        [
            ('waiting',             'Waiting for Payment'),
            ('screenshot_uploaded', 'Proof Uploaded — Pending Review'),
            ('sms_matched',         'SMS Auto-Matched'),
            ('confirmed',           'Confirmed'),
            ('rejected',            'Rejected'),
        ],
        string='Cashout Status', default='waiting', copy=False, index=True,
    )

    # ── Computed ───────────────────────────────────────────────────────────────
    @api.depends('cashout_verified', 'sms_log_id')
    def _compute_verified_by(self):
        for rec in self:
            if rec.sms_log_id:
                rec.cashout_verified_by = 'SMS Auto-Match'
            elif rec.cashout_verified:
                rec.cashout_verified_by = 'Admin Manual'
            else:
                rec.cashout_verified_by = False

    @api.depends('cashout_screenshot')
    def _compute_screenshot_url(self):
        for rec in self:
            if rec.cashout_screenshot and rec.id:
                rec.cashout_screenshot_url = (
                    f'/web/image/payment.transaction/{rec.id}/cashout_screenshot'
                )
            else:
                rec.cashout_screenshot_url = False

    # ── Odoo 18 mail.thread compatibility ─────────────────────────────────────
    @api.model
    def _get_thread_with_access(self, thread_id, mode='read', **kwargs):
        """
        Required by Odoo 18's mail/controllers/thread.py.

        Delegates to mail.thread when available (newer builds), otherwise
        provides a self-contained fallback so the chatter panel loads without
        crashing on builds that predate this method.
        """
        try:
            return super()._get_thread_with_access(thread_id, mode=mode, **kwargs)
        except AttributeError:
            pass
        # Fallback: browse + ACL check, mirrors mail.thread implementation
        thread = self.browse(thread_id)
        try:
            thread.check_access_rights(mode)
            thread.check_access_rule(mode)
        except Exception:
            return self.browse()
        return thread

    def _thread_to_store(self, store, request_list=None, **kwargs):
        """
        Required by Odoo 18's mail/tools/discuss.py Store system.

        Delegates to mail.thread when available. On older builds that predate
        the Store API, returns gracefully — the chatter widget loads messages,
        followers, and attachments through its own separate RPCs, so an empty
        response here is safe.
        """
        try:
            return super()._thread_to_store(store, request_list=request_list, **kwargs)
        except AttributeError:
            # mail.thread does not have this method in this Odoo 18 build.
            # Return without raising — chatter will still work via other RPCs.
            return

    # ── Provider-required override (Odoo 18) ──────────────────────────────────
    def _get_specific_processing_values(self, processing_values):
        res = super()._get_specific_processing_values(processing_values)
        if self.provider_code != 'cashout_pro':
            return res
        return res

    def _get_specific_rendering_values(self, processing_values):
        """
        Odoo 18 JS checks for redirect_url first and does window.location.href
        directly, bypassing the form-submit path entirely. Providing it here on
        the transaction level guarantees the redirect fires even if the
        provider-level override is missed after a hot upgrade.
        """
        res = super()._get_specific_rendering_values(processing_values)
        if self.provider_code != 'cashout_pro':
            return res
        ref = processing_values.get('reference') or self.reference or ''
        cashout_url = f'/cashout/pay?ref={ref}'
        return {
            **res,
            'api_url':      cashout_url,
            'reference':    ref,
            'redirect_url': cashout_url,
        }

    def _process_notification_data(self, notification_data):
        super()._process_notification_data(notification_data)
        if self.provider_code != 'cashout_pro':
            return
        if notification_data.get('status') == 'done':
            self._set_done()

    # ── Admin Actions ──────────────────────────────────────────────────────────
    def action_cashout_confirm(self):
        """
        Manually confirm the cashout payment from the backend.

        Full state machine:
          draft  ──► _set_pending()  ──► pending
          pending ──► _set_done()    ──► done   (triggers SO confirm + invoice)
        """
        for rec in self:
            if rec.provider_code != 'cashout_pro':
                raise UserError('This action is only for Cashout Pro transactions.')
            if rec.cashout_status == 'confirmed':
                raise UserError(f'Transaction {rec.reference} is already confirmed.')
            if rec.cashout_status == 'rejected':
                raise UserError(f'Transaction {rec.reference} was rejected and cannot be confirmed.')
            if not (rec.cashout_txn_id or '').strip():
                raise UserError(
                    f'Cannot confirm {rec.reference}: the Transaction ID field is empty. '
                    'Please verify the payment and fill in the Transaction ID from the '
                    "customer's confirmation SMS before confirming."
                )

            rec.write({
                'cashout_verified':       True,
                'cashout_status':         'confirmed',
                'cashout_confirmed_date': fields.Datetime.now(),
            })

            # Ensure Odoo state is at least 'pending' before calling _set_done().
            # _set_done() requires state in ('pending', 'authorized'); calling it
            # on a 'draft' transaction silently does nothing in Odoo 18.
            if rec.state == 'draft':
                try:
                    rec._set_pending()
                except Exception as e:
                    _logger.warning('Cashout: _set_pending for %s: %s', rec.reference, e)

            # ── 1. Transition Odoo payment state to done ─────────────────
            # _set_done() calls _execute_callback(), but in Odoo 18 that
            # callback is silently skipped when is_post_processed=True (set
            # during the original checkout redirect). We therefore ALWAYS
            # confirm the sale order explicitly below — never rely on the
            # callback alone.
            try:
                rec._set_done()
            except Exception as e:
                _logger.warning('Cashout: _set_done raised for %s: %s', rec.reference, e)

            # ── 2. Mark as post-processed to block the cron ──────────────
            # _set_done() leaves is_post_processed=False, which causes
            # _cron_post_process to call _create_payment() — and that fails
            # with "Please define a payment method line" because the provider
            # journal may not have one configured.  We handle the full
            # accounting flow ourselves below, so we block the cron here.
            try:
                rec.sudo().write({'is_post_processed': True})
            except Exception:
                pass  # field may not exist in all builds — safe to ignore

            # ── 3. Full accounting flow (SO confirm → invoice → payment) ─────
            # Do NOT wrap in try/except — UserError must reach the UI so the
            # admin sees exactly what failed instead of a silent no-op.
            rec._cashout_confirm_sale_order()

            method_label = rec._cashout_method_label()

            if hasattr(rec, 'message_post'):
                rec.message_post(
                    body=(
                        f'<p>&#9989; <b>Cashout confirmed</b> by {self.env.user.name}.</p>'
                        f'<ul>'
                        f'<li>Method: <b>{method_label}</b></li>'
                        f'<li>Txn ID: <b>{rec.cashout_txn_id or "—"}</b></li>'
                        f'<li>Sender: <b>{rec.cashout_sender or "—"}</b></li>'
                        f'<li>Confirmed on: <b>{rec.cashout_confirmed_date}</b></li>'
                        f'</ul>'
                    ),
                    message_type='notification',
                )
            else:
                _logger.info('Cashout: confirmed %s by %s (chatter unavailable)',
                             rec.reference, self.env.user.name)
            rec._cashout_send_confirmation_email()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': '✅ Payment Confirmed',
                'message': (
                    f'{rec.reference} — '
                    'Quotation confirmed · Invoice created & validated · Invoice marked paid.'
                ),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_cashout_reject(self):
        """Reject and cancel the cashout transaction."""
        for rec in self:
            if rec.cashout_status == 'confirmed':
                raise UserError('Cannot reject an already confirmed transaction.')
            rec.write({'cashout_status': 'rejected'})
            # _set_canceled() requires state != 'done'. Guard here so a
            # mis-click on a done record doesn't crash.
            if rec.state not in ('done', 'cancel'):
                try:
                    rec._set_canceled(state_message='Rejected by admin.')
                except Exception as e:
                    _logger.warning('Cashout: _set_canceled for %s: %s', rec.reference, e)
            if hasattr(rec, 'message_post'):
                rec.message_post(
                    body=f'<p>&#10060; <b>Rejected</b> by {self.env.user.name}.</p>',
                    message_type='notification',
                )
            else:
                _logger.info('Cashout: rejected %s by %s (chatter unavailable)',
                             rec.reference, self.env.user.name)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': '❌ Rejected',
                'message': f'{rec.reference} rejected.',
                'type': 'warning',
                'sticky': False,
            },
        }

    def action_view_screenshot(self):
        self.ensure_one()
        if not self.cashout_screenshot_url:
            raise UserError('No screenshot uploaded yet.')
        return {'type': 'ir.actions.act_url', 'url': self.cashout_screenshot_url, 'target': 'new'}

    # ── Sale Order Confirmation (fallback) ────────────────────────────────────
    def _cashout_confirm_sale_order(self):
        """
        Confirm quotation → create & validate invoice → register payment.
        Raises UserError with a clear message so the admin sees any failure
        instead of it being swallowed silently.
        """
        from odoo.exceptions import UserError

        self.ensure_one()
        # env.get() returns an empty recordset when the model exists —
        # empty recordsets are falsy in Odoo, so we MUST check `is None`.
        SaleOrder = self.env.get('sale.order')
        if SaleOrder is None:
            raise UserError('Sales module is not installed. Cannot confirm order.')

        # ── Find the linked sale order (three attempts) ────────────────────────
        # Attempt A: direct Many2many field added by sale module
        orders = SaleOrder
        if hasattr(self, 'sale_order_ids') and self.sale_order_ids:
            orders = self.sale_order_ids.sudo()

        # Attempt B: reverse Many2many search
        if not orders:
            orders = SaleOrder.sudo().search([
                ('transaction_ids', 'in', [self.id])
            ])

        # Attempt C: parse transaction reference (e.g. "S04055-1" → "S04055")
        if not orders and self.reference:
            so_name = self.reference.rsplit('-', 1)[0]
            orders = SaleOrder.sudo().search([('name', '=', so_name)])
            if not orders:
                # try the full reference as the order name
                orders = SaleOrder.sudo().search([('name', '=', self.reference)])

        if not orders:
            raise UserError(
                f'No sale order found for transaction {self.reference}.\n'
                f'Checked: sale_order_ids field, transaction_ids search, and order name match.'
            )

        for order in orders:
            _logger.info('Cashout: processing SO %s (state=%s)', order.name, order.state)

            # ── 1. Confirm quotation ───────────────────────────────────────────
            if order.state in ('draft', 'sent'):
                order.sudo().action_confirm()
                _logger.info('Cashout: SO %s confirmed', order.name)
            elif order.state not in ('sale', 'done'):
                raise UserError(
                    f'Sale order {order.name} is in state "{order.state}" '
                    f'and cannot be confirmed.'
                )

            # ── 2. Create invoice ──────────────────────────────────────────────
            if order.invoice_status == 'invoiced':
                _logger.info('Cashout: SO %s already fully invoiced', order.name)
                invoices = order.invoice_ids.sudo().filtered(
                    lambda inv: inv.move_type == 'out_invoice'
                    and inv.state == 'posted'
                    and inv.payment_state in ('not_paid', 'partial')
                )
            else:
                invoices = order.sudo()._create_invoices()
                if not invoices:
                    raise UserError(
                        f'Invoice creation returned nothing for order {order.name}.\n'
                        f'Check that the order lines have an invoiceable policy (Ordered/Delivered Qty).'
                    )
                _logger.info('Cashout: created %s invoice(s) for SO %s', len(invoices), order.name)

            for invoice in invoices.sudo():
                # ── 3. Validate invoice ────────────────────────────────────────
                if invoice.state == 'draft':
                    invoice.action_post()
                    _logger.info('Cashout: posted invoice %s', invoice.name)

                if invoice.payment_state in ('paid', 'in_payment'):
                    _logger.info('Cashout: invoice %s already paid', invoice.name)
                    continue

                # ── 4. Find journal ────────────────────────────────────────────
                journal = None
                if hasattr(self.provider_id, 'journal_id') and self.provider_id.journal_id:
                    journal = self.provider_id.journal_id
                if not journal:
                    journal = self.env['account.journal'].sudo().search([
                        ('type', 'in', ['bank', 'cash']),
                        ('company_id', '=', invoice.company_id.id),
                    ], limit=1)
                if not journal:
                    raise UserError(
                        f'No bank or cash journal found for company "{invoice.company_id.name}".\n'
                        f'Go to Accounting → Configuration → Journals and create one,\n'
                        f'then set it on the Cashout Pro provider under Configuration.'
                    )

                pay_method_line = journal.inbound_payment_method_line_ids[:1]
                if not pay_method_line:
                    raise UserError(
                        f'Journal "{journal.name}" has no inbound payment methods.\n'
                        f'Go to Accounting → Configuration → Journals → {journal.name}\n'
                        f'→ Configuration tab → add "Manual" under Inbound Payment Methods.'
                    )

                # ── 5. Register payment (same as UI "Register Payment" button) ─
                method_label = self._cashout_method_label()

                wizard = self.env['account.payment.register'].sudo().with_context(
                    active_model='account.move',
                    active_ids=invoice.ids,
                ).create({
                    'payment_date':           fields.Date.today(),
                    'journal_id':             journal.id,
                    'payment_method_line_id': pay_method_line.id,
                    'amount':                 invoice.amount_residual,
                    'currency_id':            invoice.currency_id.id,
                    'communication':          (
                        f'Cashout Pro | {method_label} | '
                        f'Txn: {self.cashout_txn_id or "—"} | {self.reference}'
                    ),
                })
                wizard.action_create_payments()
                _logger.info('Cashout: payment registered for invoice %s', invoice.name)

    def _cashout_chatter(self, body):
        """Post a chatter message if mail.thread is available."""
        try:
            if hasattr(self, 'message_post'):
                self.message_post(body=body, message_type='notification')
            else:
                _logger.info('Cashout chatter: %s', body)
        except Exception:
            _logger.info('Cashout chatter (fallback): %s', body)

    # ── Email Notifications ────────────────────────────────────────────────────
    def _cashout_notify_admin(self):
        """Email admin/payment managers when customer submits proof."""
        self.ensure_one()
        admin_users = self.env['res.users'].sudo().search([
            ('groups_id', 'in', [self.env.ref('payment.group_payment_manager').id]),
            ('active', '=', True),
            ('email', '!=', False),
        ], limit=5)
        if not admin_users:
            admin_users = self.env['res.users'].sudo().browse([1])

        method_label = self._cashout_method_label()
        for user in admin_users:
            if not user.email:
                continue
            self._cashout_send_plain_email(
                to=user.email,
                subject=f'⏳ Payment Proof Awaiting Review — {self.reference}',
                body=f"""
<div style="font-family:Arial,sans-serif;max-width:560px;">
  <div style="background:#f5a623;padding:16px 24px;border-radius:8px 8px 0 0;">
    <h2 style="color:#fff;margin:0;">&#9203; New Payment Proof Submitted</h2>
  </div>
  <div style="background:#f7f8fc;padding:24px;border:1px solid #e3e6f0;border-radius:0 0 8px 8px;">
    <p>A customer has submitted payment proof and needs your review.</p>
    <table style="width:100%;border-collapse:collapse;border:1px solid #e3e6f0;border-radius:6px;overflow:hidden;margin:1rem 0;">
      <tr style="background:#f0f4ff;"><td style="padding:8px 12px;color:#666;font-size:.85rem;">Order Ref</td><td style="padding:8px 12px;font-weight:700;">{self.reference}</td></tr>
      <tr><td style="padding:8px 12px;color:#666;font-size:.85rem;">Customer</td><td style="padding:8px 12px;">{self.partner_id.name or '—'}</td></tr>
      <tr style="background:#f0f4ff;"><td style="padding:8px 12px;color:#666;font-size:.85rem;">Amount</td><td style="padding:8px 12px;font-weight:700;">{self.amount:,.2f} {self.currency_id.symbol}</td></tr>
      <tr><td style="padding:8px 12px;color:#666;font-size:.85rem;">Method</td><td style="padding:8px 12px;">{method_label}</td></tr>
      <tr style="background:#f0f4ff;"><td style="padding:8px 12px;color:#666;font-size:.85rem;">Txn ID</td><td style="padding:8px 12px;">{self.cashout_txn_id or '—'}</td></tr>
      <tr><td style="padding:8px 12px;color:#666;font-size:.85rem;">Sender</td><td style="padding:8px 12px;">{self.cashout_sender or '—'}</td></tr>
    </table>
    <p><a href="/odoo/action-cashout_payment_pro.action_cashout_transactions"
          style="background:#1a1a2e;color:#fff;padding:.6rem 1.4rem;border-radius:6px;text-decoration:none;font-weight:600;">
      &#128279; Review in Backend
    </a></p>
  </div>
</div>""",
            )

    def _cashout_send_confirmation_email(self):
        """Send order-confirmed email to the customer."""
        self.ensure_one()
        if not self.partner_id or not self.partner_id.email:
            return
        template = self.env.ref(
            'cashout_payment_pro.email_template_cashout_confirmed',
            raise_if_not_found=False,
        )
        if template:
            try:
                template.send_mail(self.id, force_send=True)
                return
            except Exception as e:
                _logger.warning('Cashout: template email failed: %s', e)

        method_label = self._cashout_method_label()
        self._cashout_send_plain_email(
            subject=f'✅ Payment Confirmed — Order {self.reference}',
            body=f"""
<div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto;">
  <div style="background:linear-gradient(135deg,#1a1a2e,#0f3460);padding:28px 32px;border-radius:12px 12px 0 0;text-align:center;">
    <h1 style="color:#fff;font-size:1.4rem;margin:0;">&#9989; Payment Confirmed!</h1>
  </div>
  <div style="background:#f7f8fc;padding:32px;border:1px solid #e3e6f0;border-radius:0 0 12px 12px;">
    <p>Dear <strong>{self.partner_id.name or 'Customer'}</strong>,</p>
    <p>Your cashout payment has been verified and your order is now confirmed.</p>
    <table style="width:100%;border-collapse:collapse;background:#fff;border-radius:8px;border:1px solid #e3e6f0;margin:1rem 0;">
      <tr style="background:#f0f4ff;"><td style="padding:10px 16px;color:#666;font-size:.85rem;border-bottom:1px solid #e3e6f0;">Order Reference</td><td style="padding:10px 16px;font-weight:700;border-bottom:1px solid #e3e6f0;">{self.reference}</td></tr>
      <tr><td style="padding:10px 16px;color:#666;font-size:.85rem;border-bottom:1px solid #e3e6f0;">Amount Paid</td><td style="padding:10px 16px;font-weight:700;border-bottom:1px solid #e3e6f0;">{self.amount:,.2f} {self.currency_id.symbol}</td></tr>
      <tr style="background:#f0f4ff;"><td style="padding:10px 16px;color:#666;font-size:.85rem;border-bottom:1px solid #e3e6f0;">Payment Method</td><td style="padding:10px 16px;font-weight:700;border-bottom:1px solid #e3e6f0;">{method_label}</td></tr>
      <tr><td style="padding:10px 16px;color:#666;font-size:.85rem;">Transaction ID</td><td style="padding:10px 16px;font-weight:700;">{self.cashout_txn_id or '—'}</td></tr>
    </table>
    <p style="color:#666;font-size:.875rem;margin-bottom:0;">Thank you for your purchase!</p>
  </div>
</div>""",
        )

    def _cashout_send_plain_email(self, subject, body, to=None):
        if not to:
            to = self.partner_id.email if self.partner_id else None
        if not to:
            return
        try:
            self.env['mail.mail'].sudo().create({
                'subject':    subject,
                'email_to':   to,
                'body_html':  body,
                'auto_delete': True,
            }).send()
        except Exception as e:
            _logger.warning('Cashout: mail.mail send failed: %s', e)
