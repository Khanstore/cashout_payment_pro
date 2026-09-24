# -*- coding: utf-8 -*-
"""Remove stale ir.model.fields.selection rows before registry cleanup.

Some earlier Cashout Pro versions changed payment.transaction.cashout_method
from Selection to Char. Odoo's upgrade cleanup can encounter the old
ir.model.fields.selection rows while the current field is already Char and
then try to access Selection-only metadata (ondelete), causing:
    AttributeError: 'Char' object has no attribute 'ondelete'

A selection metadata row is only valid when its current ir.model.fields row
has ttype='selection'. Therefore any mismatched row is stale metadata and can
be safely removed before the registry cleanup phase.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # Delete XML-ID rows first so no dangling external IDs remain.
    cr.execute("""
        SELECT s.id
          FROM ir_model_fields_selection s
          JOIN ir_model_fields f ON f.id = s.field_id
         WHERE f.ttype != 'selection'
    """)
    ids = [row[0] for row in cr.fetchall()]
    if not ids:
        return

    cr.execute("""
        DELETE FROM ir_model_data
         WHERE model = 'ir.model.fields.selection'
           AND res_id = ANY(%s)
    """, (ids,))

    cr.execute("""
        DELETE FROM ir_model_fields_selection
         WHERE id = ANY(%s)
    """, (ids,))

    _logger.info(
        'Cashout Pro 18.0.11.0.11: removed %s stale selection metadata row(s).',
        len(ids),
    )
