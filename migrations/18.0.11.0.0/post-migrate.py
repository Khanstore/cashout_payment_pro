# -*- coding: utf-8 -*-
"""
Post-migrate for cashout_payment_pro 18.0.11.0.0 — see pre-migrate.py for
the full explanation of the cashout_method Selection → Char change.

By this point the ORM has already rewritten ir_model_fields for
cashout_method as ttype='char'. This step just:
  1. Trims/normalizes existing values (defensive, no-op for well-formed data).
  2. Double-checks no leftover ir_model_fields_selection rows survived
     (belt-and-braces in case another module or a partial upgrade left some).
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'payment_transaction' AND column_name = 'cashout_method'
    """)
    if not cr.fetchone():
        return

    cr.execute("""
        UPDATE payment_transaction
        SET cashout_method = TRIM(cashout_method)
        WHERE cashout_method IS NOT NULL AND cashout_method != TRIM(cashout_method)
    """)

    cr.execute("""
        DELETE FROM ir_model_fields_selection
        WHERE field_id IN (
            SELECT id FROM ir_model_fields
            WHERE model = 'payment.transaction' AND name = 'cashout_method'
        )
    """)
    _logger.info('cashout_payment_pro migration 18.0.11.0.0: post-migrate cleanup complete.')
