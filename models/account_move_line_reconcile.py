# -*- coding: utf-8 -*-
#############################################################################
#
#    DoniaLink Accounting - based on the Odoo 18 Full Accounting Kit by
#    Cybrosys Technologies (LGPL v3).
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#############################################################################
"""Manual reconciliation of selected journal items (Odoo Community has no wizard for it).

Used from the partner ledger: the Reconcile button lists the partner's open items, the
user selects the invoices and payments that belong together and reconciles them. An
unequal selection is reconciled partially, as Odoo does; nothing is written off."""
from odoo import _, models
from odoo.exceptions import UserError


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    def _dl_reload(self, message):
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'message': message, 'type': 'success', 'sticky': False,
                           'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'}}}

    def action_dl_reconcile(self):
        lines = self.filtered(lambda l: l.parent_state == 'posted' and l.account_id.reconcile and not l.reconciled)
        if not lines:
            raise UserError(_('Select open posted items on a reconcilable account.'))
        if len(lines.company_id) > 1:
            raise UserError(_('Select items of one company only.'))
        groups = lines.grouped('account_id')
        for account, group in groups.items():
            if not group.filtered(lambda l: l.amount_residual > 0) or \
                    not group.filtered(lambda l: l.amount_residual < 0):
                raise UserError(_('%s: select at least one debit and one credit item to reconcile.',
                                  account.display_name))
        for group in groups.values():
            group.reconcile()
        return self._dl_reload(_('%s items reconciled.', len(lines)))

    def action_dl_unreconcile(self):
        lines = self.filtered(lambda l: l.matched_debit_ids or l.matched_credit_ids)
        if not lines:
            raise UserError(_('The selected items are not reconciled.'))
        lines.remove_move_reconcile()
        return self._dl_reload(_('%s items unreconciled.', len(lines)))
