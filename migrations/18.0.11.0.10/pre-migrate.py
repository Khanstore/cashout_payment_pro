# -*- coding: utf-8 -*-
"""Clean stale selection metadata left by a Selection -> Char field change.

Odoo keeps ir.model.fields.selection records (and their ir.model.data XML IDs)
for selection fields. Older Cashout Pro versions used payment.transaction's
cashout_method as a Selection; current versions intentionally use Char so new
Cashout methods can be created dynamically. On some databases the old
selection metadata survives the field-type change and Odoo's registry cleanup
then tries to read ``ondelete`` from the current Char field, causing:
    AttributeError: 'Char' object has no attribute 'ondelete'

Remove only selection metadata whose current field is no longer a Selection.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        SELECT s.id
          FROM ir_model_fields_selection s
          JOIN ir_model_fields f ON f.id = s.field_id
         WHERE f.ttype != 'selection'
           AND (
                (f.model = 'payment.transaction' AND f.name = 'cashout_method')
                OR f.model LIKE 'cashout.%'
           )
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
        'Cashout Pro 18.0.11.0.10: removed %s stale selection metadata record(s).',
        len(ids),
    )
