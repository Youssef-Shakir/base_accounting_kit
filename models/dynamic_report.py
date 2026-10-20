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
"""Interactive financial reports (profit and loss, balance sheet, trial balance).

The web client action ``donialink_accounting_report`` calls ``get_report`` with the
options chosen in the report header (period, entries, comparison, zero lines) and
shows foldable lines. Account lines open their journal items; the report exports to
XLSX (``get_xlsx``) and PDF (``action_print_pdf``, the existing QWeb reports).

Figures come from the same engines as the printed reports: the financial report
trees of this module for the P&L and the balance sheet, and journal items grouped
by account for the trial balance.
"""
import io
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import xlsxwriter

REPORTS = {
    'profit_and_loss': {
        'title': 'Profit and Loss',
        'tree': 'base_accounting_kit.account_financial_report_profitandloss0',
        'default_filter': 'this_year',
    },
    'balance_sheet': {
        'title': 'Balance Sheet',
        'tree': 'base_accounting_kit.account_financial_report_balancesheet0',
        'default_filter': 'today',
    },
    'trial_balance': {
        'title': 'Trial Balance',
        'tree': None,
        'default_filter': 'this_month',
    },
}
DATE_FILTERS = ['today', 'this_month', 'last_month', 'this_quarter', 'last_quarter',
                'this_year', 'last_year', 'custom']
# reports showing balances at one date (no start date)
AS_OF_REPORTS = {'balance_sheet'}
# reports over a period: 'today' would be a one-day period, use this month instead
PERIOD_ONLY_REPORTS = {'trial_balance'}
COMPARABLE_REPORTS = {'profit_and_loss', 'balance_sheet'}


class AccountDynamicReport(models.AbstractModel):
    _name = 'account.dynamic.report'
    _description = 'Interactive Financial Report'

    # ------------------------------------------------------------------
    # Options
    # ------------------------------------------------------------------

    @api.model
    def _check_access(self):
        if not self.env.user.has_group('account.group_account_readonly') \
                and not self.env.user.has_group('account.group_account_invoice'):
            raise UserError(_('You are not allowed to see accounting reports.'))

    @api.model
    def _period(self, date_filter, date_from=None, date_to=None):
        """(date_from, date_to) of a period filter; date_from is None for 'today'."""
        today = fields.Date.context_today(self)
        company = self.env.company
        if date_filter == 'today':
            return None, today
        if date_filter == 'this_month':
            return today.replace(day=1), today.replace(day=1) + relativedelta(months=1, days=-1)
        if date_filter == 'last_month':
            first = today.replace(day=1) - relativedelta(months=1)
            return first, first + relativedelta(months=1, days=-1)
        if date_filter in ('this_quarter', 'last_quarter'):
            first = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
            if date_filter == 'last_quarter':
                first -= relativedelta(months=3)
            return first, first + relativedelta(months=3, days=-1)
        if date_filter in ('this_year', 'last_year'):
            ref = today if date_filter == 'this_year' else today - relativedelta(years=1)
            fy = company.compute_fiscalyear_dates(ref)
            return fy['date_from'], fy['date_to']
        # custom
        start = fields.Date.to_date(date_from) if date_from else None
        end = fields.Date.to_date(date_to) if date_to else today
        if start and start > end:
            raise UserError(_('The start date must be before the end date.'))
        return start, end

    @api.model
    def _comparison_period(self, options):
        start, end = fields.Date.to_date(options['date_from']), fields.Date.to_date(options['date_to'])
        if options['comparison'] == 'previous_year':
            return (start - relativedelta(years=1) if start else None), end - relativedelta(years=1)
        if start:  # previous period of the same length
            length = (end - start).days + 1
            return start - timedelta(days=length), start - timedelta(days=1)
        return None, end - relativedelta(years=1)

    @api.model
    def get_options(self, report_key, previous=None):
        """Normalized options; ``previous`` are the options sent back by the web client."""
        if report_key not in REPORTS:
            raise UserError(_('Unknown report.'))
        previous = previous or {}
        date_filter = previous.get('date_filter') or REPORTS[report_key]['default_filter']
        if date_filter not in DATE_FILTERS:
            date_filter = REPORTS[report_key]['default_filter']
        if report_key in PERIOD_ONLY_REPORTS and date_filter == 'today':
            date_filter = 'this_month'
        start, end = self._period(date_filter, previous.get('date_from'), previous.get('date_to'))
        if report_key in AS_OF_REPORTS:
            start = None  # balances at the end date
        elif not start:
            start = end.replace(day=1)
        options = {
            'report_key': report_key,
            'date_filter': date_filter,
            'date_from': fields.Date.to_string(start) if start else False,
            'date_to': fields.Date.to_string(end),
            'target_move': 'all' if previous.get('target_move') == 'all' else 'posted',
            'comparison': previous.get('comparison') if previous.get('comparison') in (
                'previous_period', 'previous_year') and report_key in COMPARABLE_REPORTS else 'none',
            'hide_zero': previous.get('hide_zero', True) is not False,
            'company_id': self.env.company.id,
        }
        return options

    @api.model
    def _period_label(self, date_from, date_to):
        lang = self.env['res.lang']._lang_get(self.env.lang or 'en_US')
        fmt = lang.date_format if lang else '%m/%d/%Y'
        end = fields.Date.to_date(date_to)
        if not date_from:
            return _('As of %s', end.strftime(fmt))
        start = fields.Date.to_date(date_from)
        return '%s - %s' % (start.strftime(fmt), end.strftime(fmt))

    # ------------------------------------------------------------------
    # Report lines
    # ------------------------------------------------------------------

    @api.model
    def get_report(self, report_key, options=None):
        """Everything the web client shows: options, columns and lines."""
        self._check_access()
        options = self.get_options(report_key, options)
        columns, lines = self._compute_report(report_key, options)
        if options['hide_zero']:
            lines = self._hide_zero(lines)
        company = self.env.company
        # amounts rounded to the currency (no 2531.849999 or 1e-12 totals on screen or in XLSX)
        self._round_values(columns, lines)
        return {
            'title': _(REPORTS[report_key]['title']),
            'company': company.name,
            'options': options,
            'period_label': self._period_label(options['date_from'], options['date_to']),
            'columns': columns,
            'lines': lines,
            'currency_id': company.currency_id.id,
        }

    @api.model
    def _compute_report(self, report_key, options):
        """(columns, lines) of a report. Columns: {'name', 'type'}; type is 'monetary'
        (default), 'percent' or 'text'. Lines: {'id', 'parent_id', 'ancestors', 'name',
        'kind', 'level', 'values', 'foldable'} plus optional 'lazy' (children loaded on
        unfold by get_children), 'account_id', 'partner_id', 'move_id'."""
        if report_key == 'trial_balance':
            return self._trial_balance(options)
        return self._financial(report_key, options)

    @api.model
    def _round_values(self, columns, lines):
        """Amounts rounded to the currency (no 2531.849999 or 1e-12 on screen or in XLSX)."""
        digits = self.env.company.currency_id.decimal_places
        for line in lines:
            line['values'] = [
                round(value, digits) + 0.0
                if value is not None and columns[i].get('type', 'monetary') == 'monetary'
                and not columns[i].get('percent') else value
                for i, value in enumerate(line['values'])
            ]
        return lines

    @api.model
    def _hide_zero(self, lines):
        is_zero = self.env.company.currency_id.is_zero
        return [line for line in lines
                if line['kind'] != 'account' or any(not is_zero(v or 0.0) for v in line['values'])]

    @api.model
    def _financial_lines(self, report_key, date_from, date_to, target_move):
        """{key: line} of the financial report tree for one period."""
        tree = self.env.ref(REPORTS[report_key]['tree'], raise_if_not_found=False)
        if not tree:
            raise UserError(_('The standard report "%s" was deleted.', REPORTS[report_key]['title']))
        wizard = self.env['financial.report'].create({
            'account_report_id': tree.id,
            'date_from': date_from or False,
            'date_to': date_to,
            'target_move': target_move,
            'company_id': self.env.company.id,
            'debit_credit': False,
        })
        form = wizard._apply_cumulative(wizard.read(
            ['date_from', 'enable_filter', 'debit_credit', 'date_to', 'account_report_id',
             'target_move', 'view_format', 'company_id'])[0])
        form['used_context'] = wizard._build_contexts({'form': form})
        raw = wizard.get_account_lines(form)
        wizard.unlink()
        return raw

    @api.model
    def _financial(self, report_key, options):
        periods = [(options['date_from'], options['date_to'])]
        if options['comparison'] != 'none':
            start, end = self._comparison_period(options)
            periods.append((fields.Date.to_string(start) if start else False, fields.Date.to_string(end)))
        if report_key == 'balance_sheet':
            periods = [(False, end) for _start, end in periods]
        columns = [{'name': self._period_label(start, end)} for start, end in periods]

        lines, index = [], {}
        id_by_kit = {}
        for col, (start, end) in enumerate(periods):
            for raw in self._financial_lines(report_key, start, end, options['target_move']):
                if raw['type'] == 'report':
                    key = 'section-%s' % raw['r_id']
                    id_by_kit[raw['id']] = key
                else:
                    key = 'account-%s-%s' % (raw['parent'], raw['account'])
                if key not in index:
                    parent = id_by_kit.get(raw['parent']) if raw['parent'] else None
                    parent_line = index.get(parent)
                    line = {
                        'id': key,
                        'parent_id': parent,
                        'ancestors': (parent_line['ancestors'] + [parent]) if parent_line else [],
                        'name': raw['name'],
                        'kind': 'section' if raw['type'] == 'report' else 'account',
                        'account_id': raw.get('account') or False,
                        'level': (len(parent_line['ancestors']) + 1) if parent_line else 0,
                        'values': [None] * len(periods),
                    }
                    index[key] = line
                    lines.append(line)
                index[key]['values'][col] = raw['balance']
        for line in lines:
            line['values'] = [v or 0.0 for v in line['values']]
            line['foldable'] = line['kind'] == 'section' and any(
                other['parent_id'] == line['id'] for other in lines)
        if len(periods) > 1:
            columns.append({'name': _('Variation %'), 'type': 'percent'})
            for line in lines:
                current, previous = line['values'][0], line['values'][1]
                line['values'].append(round((current - previous) / abs(previous) * 100, 1) if previous else None)
            columns[-1]['percent'] = True
        return columns, lines

    @api.model
    def _trial_balance(self, options):
        Line = self.env['account.move.line']
        start, end = fields.Date.to_date(options['date_from']), fields.Date.to_date(options['date_to'])
        base = [('company_id', '=', self.env.company.id),
                ('display_type', 'not in', ('line_section', 'line_note'))]
        base.append(('parent_state', '=', 'posted') if options['target_move'] == 'posted'
                    else ('parent_state', '!=', 'cancel'))
        fy_start = self.env.company.compute_fiscalyear_dates(start)['date_from']

        def totals(domain):
            return {account: (debit, credit) for account, debit, credit in Line._read_group(
                base + domain, ['account_id'], ['debit:sum', 'credit:sum'])}

        # initial balance: everything before the period for balance sheet accounts,
        # the current fiscal year only for profit and loss accounts
        initial_bs = totals([('date', '<', start), ('account_id.include_initial_balance', '=', True)])
        initial_pl = totals([('date', '<', start), ('date', '>=', fy_start),
                             ('account_id.include_initial_balance', '=', False)])
        period = totals([('date', '>=', start), ('date', '<=', end)])
        accounts = sorted(set(initial_bs) | set(initial_pl) | set(period), key=lambda a: a.code or '')
        lines = []
        sums = [0.0] * 4
        for account in accounts:
            d0, c0 = initial_bs.get(account) or initial_pl.get(account) or (0.0, 0.0)
            debit, credit = period.get(account, (0.0, 0.0))
            values = [d0 - c0, debit, credit, d0 - c0 + debit - credit]
            sums = [a + b for a, b in zip(sums, values)]
            lines.append({
                'id': 'account-%s' % account.id, 'parent_id': None, 'ancestors': [],
                'name': '%s %s' % (account.code, account.name) if account.code else account.name,
                'kind': 'account', 'account_id': account.id, 'level': 1, 'values': values,
                'foldable': False,
            })
        lines.append({'id': 'total', 'parent_id': None, 'ancestors': [], 'name': _('Total'),
                      'kind': 'total', 'account_id': False, 'level': 0, 'values': sums, 'foldable': False})
        columns = [{'name': _('Initial Balance')}, {'name': _('Debit')}, {'name': _('Credit')},
                   {'name': _('End Balance')}]
        return columns, lines

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    @api.model
    def action_open_journal_items(self, report_key, options, account_id):
        """Journal items behind an account line, for the report's period and entries."""
        self._check_access()
        options = self.get_options(report_key, options)
        account = self.env['account.account'].browse(account_id)
        domain = [('account_id', '=', account.id), ('company_id', '=', self.env.company.id),
                  ('date', '<=', options['date_to'])]
        if options['date_from'] and not (report_key == 'trial_balance' and account.include_initial_balance):
            if report_key != 'balance_sheet':
                domain.append(('date', '>=', options['date_from']))
        domain.append(('parent_state', '=', 'posted') if options['target_move'] == 'posted'
                      else ('parent_state', '!=', 'cancel'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Journal Items: %s', account.display_name),
            'res_model': 'account.move.line',
            'views': [(self.env.ref('account.view_move_line_tree').id, 'list'), (False, 'form')],
            'domain': domain,
            'context': {'search_default_group_by_move': 0, 'create': False},
            'target': 'current',
        }

    @api.model
    def action_print_pdf(self, report_key, options):
        """The printed (QWeb PDF) version of the report with the same options."""
        self._check_access()
        options = self.get_options(report_key, options)
        if report_key == 'trial_balance':
            wizard = self.env['account.balance.report'].create({
                'date_from': options['date_from'], 'date_to': options['date_to'],
                'target_move': options['target_move'],
                'display_account': 'movement' if options['hide_zero'] else 'all',
            })
            return wizard.with_context(active_model='account.balance.report', active_id=wizard.id,
                                       active_ids=[wizard.id]).check_report()
        wizard = self.env['financial.report'].create({
            'account_report_id': self.env.ref(REPORTS[report_key]['tree']).id,
            'date_from': options['date_from'] or False,
            'date_to': options['date_to'],
            'target_move': options['target_move'],
            'company_id': self.env.company.id,
        })
        return wizard.with_context(active_model='financial.report', active_id=wizard.id,
                                   active_ids=[wizard.id]).view_report_pdf()

    # ------------------------------------------------------------------
    # XLSX
    # ------------------------------------------------------------------

    @api.model
    def get_xlsx(self, report_key, options):
        """The report as shown on screen, as an XLSX file (bytes)."""
        report = self.get_report(report_key, options)
        currency = self.env.company.currency_id
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet(report['title'][:31])
        if self.env['res.lang']._lang_get(self.env.lang or 'en_US').direction == 'rtl':
            sheet.right_to_left()
        money = '#,##0' + ('.' + '0' * currency.decimal_places if currency.decimal_places else '')
        f_title = workbook.add_format({'bold': True, 'font_size': 14})
        f_head = workbook.add_format({'bold': True, 'bottom': 1, 'align': 'center'})
        f_section = workbook.add_format({'bold': True, 'num_format': money})
        f_section_name = workbook.add_format({'bold': True})
        f_amount = workbook.add_format({'num_format': money})
        f_percent = workbook.add_format({'num_format': '0.0"%"'})
        f_total = workbook.add_format({'bold': True, 'top': 1, 'num_format': money})

        sheet.write(0, 0, report['title'], f_title)
        sheet.write(1, 0, report['company'])
        sheet.write(2, 0, report['period_label'])
        sheet.write(3, 0, _('Posted entries') if report['options']['target_move'] == 'posted' else _('All entries'))
        sheet.set_column(0, 0, 50)
        sheet.set_column(1, len(report['columns']), 18)
        row = 5
        sheet.write(row, 0, '', f_head)
        for col, column in enumerate(report['columns'], start=1):
            sheet.write(row, col, column['name'], f_head)
        for line in report['lines']:
            row += 1
            is_section = line['kind'] in ('section', 'total')
            sheet.write(row, 0, '    ' * line['level'] + line['name'], f_section_name if is_section else None)
            for col, value in enumerate(line['values'], start=1):
                if value is None:
                    continue
                if report['columns'][col - 1].get('type') == 'text':
                    sheet.write_string(row, col, str(value))
                elif report['columns'][col - 1].get('percent'):
                    sheet.write_number(row, col, value, f_percent)
                else:
                    fmt = f_total if line['kind'] == 'total' else f_section if is_section else f_amount
                    sheet.write_number(row, col, value, fmt)
        sheet.freeze_panes(6, 1)
        workbook.close()
        return output.getvalue()
