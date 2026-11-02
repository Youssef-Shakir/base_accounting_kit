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
"""Statement of account of a contact: opening balance, every receivable / payable item of
the period with a running balance, closing balance and, for one side, its ageing.

It is the partner ledger of one partner, so both always show the same figures."""
from odoo import _, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def action_open_statement_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Statement of Account'),
            'res_model': 'partner.statement.wizard', 'view_mode': 'form', 'target': 'new',
            'context': {'default_partner_id': self.commercial_partner_id.id},
        }

    def _dl_statement(self, date_from, date_to, account_type='receivable', target_move='posted'):
        """Statement values of the commercial partner; balances are debit - credit, shown
        as amounts owed to the partner (credit - debit) on a payable-only statement."""
        self.ensure_one()
        partner = self.commercial_partner_id
        Report = self.env['account.dynamic.report']
        options = Report.get_options('partner_ledger', {
            'date_filter': 'custom', 'date_from': date_from, 'date_to': date_to,
            'partner_type': account_type, 'target_move': target_move, 'partner_id': partner.id})
        sign = -1 if account_type == 'payable' else 1
        opening = Report._pl_initial(options).get(partner.id, 0.0)
        items = self.env['account.move.line'].search(
            Report._pl_domain(options) + [('date', '>=', options['date_from']), ('date', '<=', options['date_to'])],
            order='date, move_name, id')
        running, lines = opening, []
        for aml in items:
            running += aml.debit - aml.credit
            label = aml.name if aml.name and aml.name != aml.move_id.name else ''
            lines.append({
                'date': aml.date, 'reference': aml.move_id.name or '',
                'description': ' - '.join(filter(None, [label, aml.move_id.ref or ''])),
                'due_date': aml.date_maturity if aml.date_maturity != aml.date else False,
                'debit': aml.debit, 'credit': aml.credit, 'balance': sign * running,
            })
        ageing = []
        if account_type in ('receivable', 'payable'):
            aged_options = Report.get_options('aged_balance', {
                'date_filter': 'custom', 'date_to': options['date_to'],
                'partner_type': account_type, 'target_move': target_move})
            open_items = Report._aged_items(aged_options, partner_id=partner.id)
            columns = Report._aged_columns()  # due date, the age buckets, total
            ageing = [{'name': columns[index]['name'], 'amount': sum(item['values'][index] for item in open_items)}
                      for index in range(1, len(columns) - 1)]
        is_zero = self.env.company.currency_id.is_zero
        if is_zero(running):
            closing_label = _('Balance')
        elif running > 0:
            closing_label = _('Balance due by %s', partner.display_name)
        else:
            closing_label = _('Balance due to %s', partner.display_name)
        return {
            'partner': partner, 'company': self.env.company, 'currency': self.env.company.currency_id,
            'date_from': options['date_from'], 'date_to': options['date_to'], 'account_type': account_type,
            'opening': sign * opening, 'lines': lines, 'closing': abs(running), 'closing_label': closing_label,
            'total_debit': sum(l['debit'] for l in lines), 'total_credit': sum(l['credit'] for l in lines),
            'ageing': ageing,
        }
