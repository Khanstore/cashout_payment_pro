# -*- coding: utf-8 -*-
"""
Migration for cashout_payment_pro 18.0.11.0.0

`payment.transaction.cashout_method` changed from:
    fields.Selection([('bkash', 'bKash'), ('nagad', 'Nagad')])
to:
    fields.Char()

PostgreSQL stores both Selection and Char as `varchar` under the hood, so no
column type conversion or data rewrite is actually needed — existing values
like 'bkash' / 'nagad' remain perfectly valid as plain text.

The upgrade error comes from Odoo's registry loader: it still has metadata
rows in ir_model_fields_selection for the old ('bkash', 'bKash') /
('nagad', 'Nagad') choices tied to this field. When the ORM sees the field
is no longer a Selection, it can fail while trying to reconcile/clean up
those orphaned rows. This pre-migrate step removes them proactively, before
the registry starts loading the new field definition.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # Nothing to do on a fresh install — the column won't exist yet.
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'payment_transaction' AND column_name = 'cashout_method'
    """)
    if not cr.fetchone():
        return

    # Remove stale Selection-choice metadata for cashout_method so the ORM
    # doesn't try to reconcile it against the new Char field definition.
    cr.execute("""
        DELETE FROM ir_model_fields_selection
        WHERE field_id IN (
            SELECT id FROM ir_model_fields
            WHERE model = 'payment.transaction' AND name = 'cashout_method'
        )
    """)
    _logger.info(
        'cashout_payment_pro migration 18.0.11.0.0: removed %s stale '
        'ir_model_fields_selection row(s) for cashout_method.',
        cr.rowcount,
    )
