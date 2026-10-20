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
"""Interactive general ledger, partner ledger and aged partner balance.

Accounts / partners are listed first; their journal items are loaded only when the
line is unfolded (``get_children``), so large ledgers stay fast. The aged balance is
correct at past dates: payments reconciled after the "as of" date do not reduce it.
"""
from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .dynamic_report import AS_OF_REPORTS, PERIOD_ONLY_REPORTS, REPORTS

REPORTS.update({
    'general_ledger': {'title': 'General Ledger', 'tree': None, 'default_filter': 'this_month'},
    'partner_ledger': {'title': 'Partner Ledger', 'tree': None, 'default_filter': 'this_year'},
    'aged_balance': {'title': 'Aged Partner Balance', 'tree': None, 'default_filter': 'today'},
})
AS_OF_REPORTS.add('aged_balance')
PERIOD_ONLY_REPORTS.update({'general_ledger', 'partner_ledger'})
LAZY_REPORTS = ('general_ledger', 'partner_ledger', 'aged_balance')
ITEMS_LIMIT = 1000  # journal items shown under one account / partner; the rest opens in a list
ACCOUNT_TYPES = {
    'receivable': ('asset_receivable',),
    'payable': ('liability_payable',),
    'both': ('asset_receivable', 'liability_payable'),
}
AGE_BUCKETS = 6  # not due, 1-30, 31-60, 61-90, 91-120, older


class AccountDynamicReport(models.AbstractModel):
    _inherit = 'account.dynamic.report'

    # ------------------------------------------------------------------
    # Options and dispatch
    # ------------------------------------------------------------------

    @api.model
    def get_options(self, report_key, previous=None):
        options = super().get_options(report_key, previous)
        previous = previous or {}
        if report_key == 'partner_ledger':
            options['partner_type'] = previous.get('partner_type') if previous.get('partner_type') in ACCOUNT_TYPES else 'both'
        elif report_key == 'aged_balance':
            options['partner_type'] = previous.get('partner_type') if previous.get('partner_type') in (
                'receivable', 'payable') else 'receivable'
        if report_key in LAZY_REPORTS:
            options['search'] = str(previous.get('search') or '').strip()[:100]
            options['unfold_all'] = bool(previous.get('unfold_all'))
            options['hide_zero'] = False
        return options

    @api.model
    def _compute_report(self, report_key, options):
        if report_key == 'general_ledger':
            return self._general_ledger(options)
        if report_key == 'partner_ledger':
            return self._partner_ledger(options)
        if report_key == 'aged_balance':
            return self._aged_balance(options)
        return super()._compute_report(report_key, options)

    @api.model
    def get_children(self, report_key, options, line_id):
        """Lines under an account / partner line, loaded when the user unfolds it."""
        self._check_access()
        options = self.get_options(report_key, options)
        kind, _sep, ref = line_id.partition('-')
        ref = int(ref or 0)
        if report_key == 'general_ledger' and kind == 'account':
            account = self.env['account.account'].browse(ref)
            initial = self._gl_initial(options, account.ids).get(account, 0.0)
            columns = self._general_ledger_columns()
            lines = self._gl_items(options, account, initial, line_id)
        elif report_key == 'partner_ledger' and kind == 'partner':
            initial = self._pl_initial(options).get(ref or False, 0.0)
            columns = self._partner_ledger_columns()
            lines = self._pl_items(options, ref, initial, line_id)
        elif report_key == 'aged_balance' and kind == 'partner':
            columns = self._aged_columns()
            lines = [line for line in self._aged_items(options, partner_id=ref) if line]
            for line in lines:
                line.update(parent_id=line_id, ancestors=[line_id], level=1)
        else:
            raise UserError(_('Unknown report line.'))
        return self._round_values(columns, lines)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @api.model
    def _aml_domain(self, options):
        domain = [('company_id', '=', self.env.company.id),
                  ('display_type', 'not in', ('line_section', 'line_note'))]
        domain.append(('parent_state', '=', 'posted') if options['target_move'] == 'posted'
                      else ('parent_state', '!=', 'cancel'))
        return domain

    @api.model
    def _date_text(self, value):
        lang = self.env['res.lang']._lang_get(self.env.lang or 'en_US')
        return value.strftime(lang.date_format if lang else '%m/%d/%Y') if value else ''

    @api.model
    def _child(self, parent_id, line_id, name, kind, values, **extra):
        return dict({'id': line_id, 'parent_id': parent_id, 'ancestors': [parent_id], 'name': name,
                     'kind': kind, 'level': 1, 'values': values, 'foldable': False}, **extra)

    # ------------------------------------------------------------------
    # General ledger
    # ------------------------------------------------------------------

    @api.model
    def _general_ledger_columns(self):
        return [{'name': _('Date'), 'type': 'text'},
                {'name': _('Partner'), 'type': 'text'}, {'name': _('Label'), 'type': 'text'},
                {'name': _('Debit')}, {'name': _('Credit')}, {'name': _('Balance')}]

    @api.model
    def _gl_initial(self, options, account_ids=None):
        """Balance before the period: all history for balance sheet accounts, the current
        fiscal year for profit and loss accounts (as in the trial balance)."""
        Line = self.env['account.move.line']
        start = fields.Date.to_date(options['date_from'])
        fy_start = self.env.company.compute_fiscalyear_dates(start)['date_from']
        base = self._aml_domain(options) + [('date', '<', start)]
        if account_ids is not None:
            base.append(('account_id', 'in', account_ids))
        initial = defaultdict(float)
        for domain in ([('account_id.include_initial_balance', '=', True)],
                       [('account_id.include_initial_balance', '=', False), ('date', '>=', fy_start)]):
            for account, balance in Line._read_group(base + domain, ['account_id'], ['balance:sum']):
                initial[account] += balance
        return initial

    @api.model
    def _general_ledger(self, options):
        Line = self.env['account.move.line']
        columns = self._general_ledger_columns()
        account_ids = None
        if options['search']:
            account_ids = self.env['account.account'].search(
                ['|', ('code', '=ilike', options['search'] + '%'), ('name', 'ilike', options['search'])]).ids
        initial = self._gl_initial(options, account_ids)
        domain = self._aml_domain(options) + [('date', '>=', options['date_from']), ('date', '<=', options['date_to'])]
        if account_ids is not None:
            domain.append(('account_id', 'in', account_ids))
        period = {account: (debit, credit) for account, debit, credit in
                  Line._read_group(domain, ['account_id'], ['debit:sum', 'credit:sum'])}
        is_zero = self.env.company.currency_id.is_zero
        accounts = sorted({a for a, v in initial.items() if not is_zero(v)} | set(period), key=lambda a: a.code or '')
        lines, totals = [], [0.0, 0.0, 0.0]
        for account in accounts:
            debit, credit = period.get(account, (0.0, 0.0))
            end = initial.get(account, 0.0) + debit - credit
            totals = [totals[0] + debit, totals[1] + credit, totals[2] + end]
            line_id = 'account-%s' % account.id
            lines.append({
                'id': line_id, 'parent_id': None, 'ancestors': [], 'kind': 'section', 'level': 0,
                'name': '%s %s' % (account.code, account.name) if account.code else account.name,
                'values': [None, None, None, debit, credit, end],
                'foldable': True, 'lazy': True, 'account_id': account.id,
            })
            if options['unfold_all']:
                lines += self._gl_items(options, account, initial.get(account, 0.0), line_id)
        lines.append({'id': 'total', 'parent_id': None, 'ancestors': [], 'kind': 'total', 'level': 0,
                      'name': _('Total'), 'values': [None, None, None] + totals, 'foldable': False})
        return columns, lines

    @api.model
    def _gl_items(self, options, account, initial, parent_id):
        lines = []
        if not self.env.company.currency_id.is_zero(initial):
            lines.append(self._child(parent_id, '%s-initial' % parent_id, _('Initial Balance'), 'initial',
                                     [None, None, None, None, None, initial]))
        items = self.env['account.move.line'].search(
            self._aml_domain(options) + [('account_id', '=', account.id), ('date', '>=', options['date_from']),
                                         ('date', '<=', options['date_to'])],
            order='date, move_name, id', limit=ITEMS_LIMIT + 1)
        running = initial
        for aml in items[:ITEMS_LIMIT]:
            running += aml.debit - aml.credit
            lines.append(self._child(
                parent_id, 'aml-%s' % aml.id, aml.move_id.name, 'item',
                [self._date_text(aml.date), aml.partner_id.display_name or '',
                 aml.name or '', aml.debit, aml.credit, running],
                move_id=aml.move_id.id))
        if len(items) > ITEMS_LIMIT:
            lines.append(self._child(parent_id, '%s-more' % parent_id,
                                     _('More items: open all the journal items of this account'), 'more',
                                     [None] * 6, account_id=account.id))
        return lines

    # ------------------------------------------------------------------
    # Partner ledger
    # ------------------------------------------------------------------

    @api.model
    def _partner_ledger_columns(self):
        return [{'name': _('Date'), 'type': 'text'},
                {'name': _('Account'), 'type': 'text'}, {'name': _('Label'), 'type': 'text'},
                {'name': _('Debit')}, {'name': _('Credit')}, {'name': _('Balance')}]

    @api.model
    def _pl_domain(self, options):
        domain = self._aml_domain(options) + [
            ('account_id.account_type', 'in', ACCOUNT_TYPES[options['partner_type']])]
        if options['search']:
            domain.append(('partner_id.name', 'ilike', options['search']))
        return domain

    @api.model
    def _pl_initial(self, options):
        """{partner id (False = no partner): balance before the period} (receivables and
        payables carry their whole history)."""
        return {(partner.id or False): balance for partner, balance in self.env['account.move.line']._read_group(
            self._pl_domain(options) + [('date', '<', options['date_from'])], ['partner_id'], ['balance:sum'])}

    @api.model
    def _partner_ledger(self, options):
        Line = self.env['account.move.line']
        columns = self._partner_ledger_columns()
        initial = self._pl_initial(options)
        period = {(partner.id or False): (debit, credit) for partner, debit, credit in Line._read_group(
            self._pl_domain(options) + [('date', '>=', options['date_from']), ('date', '<=', options['date_to'])],
            ['partner_id'], ['debit:sum', 'credit:sum'])}
        is_zero = self.env.company.currency_id.is_zero
        partner_ids = {p for p, v in initial.items() if not is_zero(v)} | set(period)
        partners = self.env['res.partner'].browse([p for p in partner_ids if p])
        ordered = sorted(partners, key=lambda p: (p.display_name or '').lower()) + (
            [False] if False in partner_ids else [])
        lines, totals = [], [0.0, 0.0, 0.0]
        for partner in ordered:
            pid = partner.id if partner else False
            debit, credit = period.get(pid, (0.0, 0.0))
            end = initial.get(pid, 0.0) + debit - credit
            totals = [totals[0] + debit, totals[1] + credit, totals[2] + end]
            line_id = 'partner-%s' % (pid or 0)
            lines.append({
                'id': line_id, 'parent_id': None, 'ancestors': [], 'kind': 'section', 'level': 0,
                'name': partner.display_name if partner else _('Unknown partner'),
                'values': [None, None, None, debit, credit, end],
                'foldable': True, 'lazy': True, 'partner_id': pid or 0,
            })
            if options['unfold_all']:
                lines += self._pl_items(options, pid, initial.get(pid, 0.0), line_id)
        lines.append({'id': 'total', 'parent_id': None, 'ancestors': [], 'kind': 'total', 'level': 0,
                      'name': _('Total'), 'values': [None, None, None] + totals, 'foldable': False})
        return columns, lines

    @api.model
    def _pl_items(self, options, partner_id, initial, parent_id):
        lines = []
        if not self.env.company.currency_id.is_zero(initial):
            lines.append(self._child(parent_id, '%s-initial' % parent_id, _('Initial Balance'), 'initial',
                                     [None, None, None, None, None, initial]))
        items = self.env['account.move.line'].search(
            self._pl_domain(options) + [('partner_id', '=', partner_id or False),
                                        ('date', '>=', options['date_from']), ('date', '<=', options['date_to'])],
            order='date, move_name, id', limit=ITEMS_LIMIT + 1)
        running = initial
        for aml in items[:ITEMS_LIMIT]:
            running += aml.debit - aml.credit
            lines.append(self._child(
                parent_id, 'aml-%s' % aml.id, aml.move_id.name, 'item',
                [self._date_text(aml.date), aml.account_id.code or aml.account_id.name,
                 aml.name or '', aml.debit, aml.credit, running],
                move_id=aml.move_id.id))
        if len(items) > ITEMS_LIMIT:
            lines.append(self._child(parent_id, '%s-more' % parent_id,
                                     _('More items: open all the journal items of this partner'), 'more',
                                     [None] * 6, partner_id=partner_id or 0))
        return lines

    # ------------------------------------------------------------------
    # Aged partner balance
    # ------------------------------------------------------------------

    @api.model
    def _aged_columns(self):
        return [{'name': _('Due Date'), 'type': 'text'}, {'name': _('Not due')}, {'name': _('1-30')},
                {'name': _('31-60')}, {'name': _('61-90')}, {'name': _('91-120')}, {'name': _('Older')},
                {'name': _('Total')}]

    @api.model
    def _aged_items(self, options, partner_id=None):
        """Open items at the 'as of' date, one line each with its amount in its age bucket.

        Open at a past date = not reconciled, or reconciled by payments made after it:
        only reconciliations dated up to the 'as of' date reduce the amount due."""
        as_of = fields.Date.to_date(options['date_to'])
        sign = 1 if options['partner_type'] == 'receivable' else -1
        domain = self._aml_domain(options) + [
            ('date', '<=', as_of), ('account_id.account_type', 'in', ACCOUNT_TYPES[options['partner_type']]),
            '|', ('reconciled', '=', False), '|', ('matched_debit_ids.max_date', '>', as_of),
            ('matched_credit_ids.max_date', '>', as_of)]
        if partner_id is not None:
            domain.append(('partner_id', '=', partner_id or False))
        elif options['search']:
            domain.append(('partner_id.name', 'ilike', options['search']))
        is_zero = self.env.company.currency_id.is_zero
        items = []
        for aml in self.env['account.move.line'].search(domain, order='date_maturity, date, id'):
            residual = aml.balance \
                - sum(p.amount for p in aml.matched_credit_ids if p.max_date <= as_of) \
                + sum(p.amount for p in aml.matched_debit_ids if p.max_date <= as_of)
            if is_zero(residual):
                continue
            due = aml.date_maturity or aml.date
            late = (as_of - due).days
            bucket = 0 if late <= 0 else min((late - 1) // 30 + 1, AGE_BUCKETS - 1)
            values = [self._date_text(due)] + [0.0] * AGE_BUCKETS + [sign * residual]
            values[1 + bucket] = sign * residual
            items.append({
                'id': 'aml-%s' % aml.id, 'name': ' '.join(filter(None, [aml.move_id.name, aml.move_id.ref or ''])),
                'kind': 'item', 'values': values, 'foldable': False, 'move_id': aml.move_id.id,
                'partner_key': aml.partner_id.id or 0, 'partner_name': aml.partner_id.display_name,
            })
        return items

    @api.model
    def _aged_balance(self, options):
        columns = self._aged_columns()
        per_partner = defaultdict(list)
        names = {}
        for item in self._aged_items(options):
            per_partner[item['partner_key']].append(item)
            names[item['partner_key']] = item['partner_name'] or _('Unknown partner')
        lines, totals = [], [0.0] * (AGE_BUCKETS + 1)
        for key in sorted(per_partner, key=lambda k: (k == 0, names[k].lower())):
            sums = [sum(item['values'][i] for item in per_partner[key]) for i in range(1, AGE_BUCKETS + 2)]
            totals = [a + b for a, b in zip(totals, sums)]
            line_id = 'partner-%s' % key
            lines.append({
                'id': line_id, 'parent_id': None, 'ancestors': [], 'kind': 'section', 'level': 0,
                'name': names[key], 'values': [None] + sums, 'foldable': True, 'lazy': True, 'partner_id': key,
            })
            if options['unfold_all']:
                for item in per_partner[key]:
                    lines.append(dict(item, parent_id=line_id, ancestors=[line_id], level=1))
        lines.append({'id': 'total', 'parent_id': None, 'ancestors': [], 'kind': 'total', 'level': 0,
                      'name': _('Total'), 'values': [None] + totals, 'foldable': False})
        return columns, lines

    # ------------------------------------------------------------------
    # Actions, PDF and XLSX
    # ------------------------------------------------------------------

    @api.model
    def action_open_line(self, report_key, options, line):
        """What a click on a line opens: an account's journal items, a journal entry,
        or the full list behind a 'more items' line."""
        self._check_access()
        if line.get('move_id'):
            return {'type': 'ir.actions.act_window', 'res_model': 'account.move', 'res_id': line['move_id'],
                    'views': [(False, 'form')], 'target': 'current'}
        if line.get('account_id'):
            return self.action_open_journal_items(report_key, options, line['account_id'])
        if report_key == 'partner_ledger' and 'partner_id' in line:
            options = self.get_options(report_key, options)
            domain = self._pl_domain(options) + [('partner_id', '=', line['partner_id'] or False),
                                                 ('date', '>=', options['date_from']),
                                                 ('date', '<=', options['date_to'])]
            return {'type': 'ir.actions.act_window', 'name': _('Journal Items'), 'res_model': 'account.move.line',
                    'views': [(self.env.ref('account.view_move_line_tree').id, 'list'), (False, 'form')],
                    'domain': domain, 'context': {'create': False}, 'target': 'current'}
        return False

    @api.model
    def action_print_pdf(self, report_key, options):
        if report_key not in LAZY_REPORTS:
            return super().action_print_pdf(report_key, options)
        self._check_access()
        options = self.get_options(report_key, options)
        selection = {'receivable': 'customer', 'payable': 'supplier', 'both': 'customer_supplier'}
        if report_key == 'general_ledger':
            wizard = self.env['account.report.general.ledger'].create({
                'date_from': options['date_from'], 'date_to': options['date_to'],
                'target_move': options['target_move'], 'display_account': 'movement',
                'initial_balance': True, 'sortby': 'sort_date',
            })
        elif report_key == 'partner_ledger':
            wizard = self.env['account.report.partner.ledger'].create({
                'date_from': options['date_from'], 'date_to': options['date_to'],
                'target_move': options['target_move'], 'reconciled': True,
                'result_selection': selection[options['partner_type']],
            })
        else:
            wizard = self.env['account.aged.trial.balance'].create({
                'date_from': options['date_to'], 'period_length': 30,
                'target_move': options['target_move'],
                'result_selection': selection[options['partner_type']],
            })
        return wizard.with_context(active_model=wizard._name, active_id=wizard.id,
                                   active_ids=[wizard.id]).check_report()

    @api.model
    def get_xlsx(self, report_key, options):
        if report_key in LAZY_REPORTS:
            options = dict(options or {}, unfold_all=True)
        return super().get_xlsx(report_key, options)
