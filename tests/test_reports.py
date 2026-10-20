# -*- coding: utf-8 -*-
"""Smoke and consistency tests of the accounting reports (DoniaLink fixes)."""
import json
import logging
import traceback

from odoo.tools.safe_eval import safe_eval

from odoo.tests import TransactionCase, tagged

_logger = logging.getLogger(__name__)

# wizard model -> (method that prints, extra values)
WIZARDS = {
    'account.balance.report': ('check_report', {'display_account': 'movement'}),
    'account.report.general.ledger': ('check_report', {}),
    'account.report.partner.ledger': ('check_report', {}),
    'account.aged.trial.balance': ('check_report', {}),
    'account.print.journal': ('check_report', {}),
    'kit.account.tax.report': ('check_report', {}),
    'cash.flow.report': ('check_report', {}),
    'account.bank.book.report': ('check_report', {}),
    'account.cash.book.report': ('check_report', {}),
    'account.day.book.report': ('check_report', {}),
}


@tagged('post_install', '-at_install')
class TestReportsSmoke(TransactionCase):

    def _render(self, action):
        """Render like the web client: the action data travels as JSON (dates become strings)."""
        report = self.env['ir.actions.report']._get_report_from_name(action['report_name'])
        context = dict(action.get('context') or {})
        data = json.loads(json.dumps(action.get('data'), default=str))
        docids = (data or {}).get('ids') or context.get('active_ids') or []
        return report.with_context(context)._render_qweb_html(report.report_name, docids, data=data)

    def test_all_reports_render(self):
        failures = []
        dates = {'date_from': '2025-01-01', 'date_to': '2026-12-31'}
        for model, (method, extra) in WIZARDS.items():
            if model not in self.env:
                failures.append(f'{model}: model missing')
                continue
            try:
                with self.env.cr.savepoint():
                    window = self.env['ir.actions.act_window'].search([('res_model', '=', model)], limit=1)
                    action_context = safe_eval(window.context or '{}', {'uid': self.env.uid}) if window else {}
                    Wizard = self.env[model].with_context(action_context, active_model='ir.ui.menu', active_ids=[])
                    values = {k: v for k, v in dict(dates, **extra).items() if k in Wizard._fields}
                    wizard = Wizard.create(values)
                    # a button click passes the wizard as the active record
                    wizard = wizard.with_context(active_model=model, active_id=wizard.id, active_ids=[wizard.id])
                    action = getattr(wizard, method)()
                    self._render(action)
                    # the View button opens the same report as a web page; its data travels in the URL
                    web = getattr(wizard.with_context(report_view_html=True), method)()
                    self.assertEqual(web['report_type'], 'qweb-html')
                    self.assertLess(len(json.dumps(web.get('data'), default=str)), 4000, 'URL too long for the web view')
            except Exception:
                failures.append(f'{model}:\n{traceback.format_exc()}')
        for name in ('account_financial_report_profitandloss0', 'account_financial_report_balancesheet0'):
            try:
                with self.env.cr.savepoint():
                    wizard = self.env['financial.report'].create(dict(
                        dates, account_report_id=self.env.ref(f'base_accounting_kit.{name}').id))
                    self._render(wizard.view_report_pdf())
                    web = wizard.with_context(report_view_html=True).view_report_pdf()
                    self.assertEqual(web['report_type'], 'qweb-html')
                    self.assertLess(len(json.dumps(web.get('data'), default=str)), 4000, 'URL too long for the web view')
            except Exception:
                failures.append(f'financial.report {name}:\n{traceback.format_exc()}')
        if failures:
            _logger.error('Report failures:\n%s', '\n'.join(failures))
        self.assertFalse(failures, f'{len(failures)} report(s) failed, see log')


@tagged('post_install', '-at_install')
class TestFinancialReports(TransactionCase):
    """DoniaLink fixes of the balance sheet and profit and loss."""

    PL_TYPES = ('income', 'income_other', 'expense', 'expense_depreciation', 'expense_direct_cost')

    def _lines(self, xmlid, date_from, date_to):
        report = self.env.ref(f'base_accounting_kit.{xmlid}')
        wizard = self.env['financial.report'].create({
            'account_report_id': report.id, 'date_from': date_from, 'date_to': date_to})
        form = wizard._apply_cumulative(wizard.read(
            ['date_from', 'enable_filter', 'debit_credit', 'date_to', 'account_report_id',
             'target_move', 'view_format', 'company_id'])[0])
        form['used_context'] = wizard._build_contexts({'form': form})
        return {(line['type'], line.get('r_id') or line.get('account')): line
                for line in wizard.get_account_lines(form)}

    def _sum(self, domain):
        return sum(self.env['account.move.line'].search(
            [('parent_state', '=', 'posted'), ('company_id', '=', self.env.company.id)] + domain).mapped('balance'))

    def test_balance_sheet_cumulative_and_balanced(self):
        # a start date late in the history must not change balances at the end date
        late = self._lines('account_financial_report_balancesheet0', '2026-10-01', '2026-12-31')
        none = self._lines('account_financial_report_balancesheet0', False, '2026-12-31')
        assets = self.env.ref('base_accounting_kit.account_financial_report_assets0').id
        root = self.env.ref('base_accounting_kit.account_financial_report_balancesheet0').id
        self.assertAlmostEqual(late[('report', assets)]['balance'], none[('report', assets)]['balance'], 2)
        expected_assets = self._sum([('date', '<=', '2026-12-31'), ('account_id.account_type', 'in', (
            'asset_receivable', 'asset_cash', 'asset_current', 'asset_non_current', 'asset_prepayments',
            'asset_fixed'))])
        self.assertAlmostEqual(late[('report', assets)]['balance'], expected_assets, 2)
        # assets = liabilities + equity (+ unclosed profit): the whole sheet sums to zero
        self.assertAlmostEqual(late[('report', root)]['balance'], 0.0, 2)

    def test_equity_not_under_liabilities(self):
        equity = self.env.ref('base_accounting_kit.financial_report_equity_sum')
        liabilities = self.env.ref('base_accounting_kit.account_financial_report_liabilitysum0')
        self.assertEqual(equity.parent_id, self.env.ref('base_accounting_kit.account_financial_report_balancesheet0'))
        self.assertNotIn('equity', liabilities._get_children_by_order().mapped('account_type_ids'))

    def test_profit_and_loss_includes_depreciation(self):
        lines = self._lines('account_financial_report_profitandloss0', '2025-01-01', '2026-12-31')
        root = self.env.ref('base_accounting_kit.account_financial_report_profitandloss0').id
        expected = -self._sum([('date', '>=', '2025-01-01'), ('date', '<=', '2026-12-31'),
                               ('account_id.account_type', 'in', self.PL_TYPES)])
        self.assertAlmostEqual(lines[('report', root)]['balance'], expected, 2)
        depreciation = self.env.ref('base_accounting_kit.financial_report_depreciation')
        self.assertEqual(depreciation.account_type_ids, 'expense_depreciation')

    def test_renaming_a_line_does_not_change_figures(self):
        before = self._lines('account_financial_report_balancesheet0', False, '2026-12-31')
        assets = self.env.ref('base_accounting_kit.account_financial_report_assets0')
        assets.name = 'الموجودات'
        after = self._lines('account_financial_report_balancesheet0', False, '2026-12-31')
        self.assertAlmostEqual(before[('report', assets.id)]['balance'], after[('report', assets.id)]['balance'], 2)


@tagged('post_install', '-at_install')
class TestDynamicReports(TransactionCase):
    """Interactive reports (DoniaLink): options, figures, drill-down, PDF and XLSX."""

    def setUp(self):
        super().setUp()
        self.Report = self.env['account.dynamic.report']
        self.wide = {'date_filter': 'custom', 'date_from': '2025-01-01', 'date_to': '2026-12-31',
                     'hide_zero': False}

    def _sum(self, domain):
        return sum(self.env['account.move.line'].search(
            [('parent_state', '=', 'posted'), ('company_id', '=', self.env.company.id)] + domain).mapped('balance'))

    def test_all_options_load(self):
        for key in ('profit_and_loss', 'balance_sheet', 'trial_balance'):
            for date_filter in ('today', 'this_month', 'last_month', 'this_quarter', 'last_quarter',
                                'this_year', 'last_year'):
                for comparison in ('none', 'previous_period', 'previous_year'):
                    report = self.Report.get_report(key, {'date_filter': date_filter, 'comparison': comparison,
                                                          'target_move': 'all'})
                    self.assertTrue(report['columns'], key)
                    for line in report['lines']:
                        self.assertEqual(len(line['values']), len(report['columns']), (key, line['name']))

    def test_profit_and_loss_matches_journal_items(self):
        report = self.Report.get_report('profit_and_loss', self.wide)
        root = report['lines'][0]
        expected = -self._sum([('date', '>=', '2025-01-01'), ('date', '<=', '2026-12-31'), ('account_id.account_type', 'in', (
            'income', 'income_other', 'expense', 'expense_depreciation', 'expense_direct_cost'))])
        self.assertAlmostEqual(root['values'][0], expected, 2)
        self.assertEqual(root['level'], 0)
        self.assertTrue(root['foldable'])

    def test_balance_sheet_balances_with_comparison(self):
        report = self.Report.get_report('balance_sheet', dict(self.wide, comparison='previous_year'))
        self.assertEqual(len(report['columns']), 3)  # as of, last year, variation
        self.assertFalse(report['options']['date_from'])
        self.assertAlmostEqual(report['lines'][0]['values'][0], 0.0, 2)

    def test_trial_balance_columns_add_up(self):
        report = self.Report.get_report('trial_balance', self.wide)
        for line in report['lines']:
            initial, debit, credit, end = line['values']
            self.assertAlmostEqual(initial + debit - credit, end, 2, line['name'])
        total = report['lines'][-1]
        self.assertEqual(total['kind'], 'total')
        self.assertAlmostEqual(total['values'][1], total['values'][2], 2)  # debit = credit

    def test_hide_zero(self):
        shown = self.Report.get_report('profit_and_loss', dict(self.wide, hide_zero=True))
        for line in shown['lines']:
            if line['kind'] == 'account':
                self.assertTrue(any(line['values']))

    def test_drill_down_pdf_and_xlsx(self):
        report = self.Report.get_report('profit_and_loss', self.wide)
        account_line = next((l for l in report['lines'] if l['kind'] == 'account'), None)
        if account_line:
            action = self.Report.action_open_journal_items('profit_and_loss', self.wide, account_line['account_id'])
            self.assertEqual(action['res_model'], 'account.move.line')
            items = self.env['account.move.line'].search(action['domain'])
            # the journal items behind a line add up to it (the line may show the reversed sign)
            self.assertAlmostEqual(abs(sum(items.mapped('balance'))), abs(account_line['values'][0]), 2)
        for key in ('profit_and_loss', 'balance_sheet', 'trial_balance'):
            pdf = self.Report.action_print_pdf(key, self.wide)
            self.assertEqual(pdf['type'], 'ir.actions.report')
            content = self.Report.get_xlsx(key, self.wide)
            self.assertEqual(content[:2], b'PK')  # zip container of an xlsx file


@tagged('post_install', '-at_install')
class TestDynamicLedgers(TransactionCase):
    """Interactive general ledger, partner ledger and aged balance (DoniaLink)."""

    def setUp(self):
        super().setUp()
        self.Report = self.env['account.dynamic.report']
        self.wide = {'date_filter': 'custom', 'date_from': '2025-01-01', 'date_to': '2026-12-31'}

    def test_general_ledger_matches_trial_balance(self):
        gl = self.Report.get_report('general_ledger', self.wide)
        tb = self.Report.get_report('trial_balance', dict(self.wide, hide_zero=False))
        tb_by_account = {l['account_id']: l['values'] for l in tb['lines'] if l['kind'] == 'account'}
        sections = [l for l in gl['lines'] if l['kind'] == 'section']
        self.assertTrue(all(l['lazy'] for l in sections))
        for section in sections:
            debit, credit, end = section['values'][3:]
            tb_values = tb_by_account.get(section['account_id'], [0, 0, 0, 0])
            self.assertAlmostEqual(debit, tb_values[1], 2, section['name'])
            self.assertAlmostEqual(credit, tb_values[2], 2, section['name'])
            self.assertAlmostEqual(end, tb_values[3], 2, section['name'])
        # the running balance of the last item is the account's end balance
        for section in sections[:5]:
            children = self.Report.get_children('general_ledger', self.wide, section['id'])
            balances = [c for c in children if c['kind'] in ('item', 'initial')]
            if balances:
                self.assertAlmostEqual(balances[-1]['values'][5], section['values'][5], 2, section['name'])
        unfolded = self.Report.get_report('general_ledger', dict(self.wide, unfold_all=True))
        self.assertGreaterEqual(len(unfolded['lines']), len(gl['lines']))

    def test_partner_ledger_total(self):
        report = self.Report.get_report('partner_ledger', dict(self.wide, partner_type='both'))
        total = report['lines'][-1]
        expected = sum(self.env['account.move.line'].search([
            ('parent_state', '=', 'posted'), ('company_id', '=', self.env.company.id), ('date', '<=', '2026-12-31'),
            ('account_id.account_type', 'in', ('asset_receivable', 'liability_payable'))]).mapped('balance'))
        self.assertAlmostEqual(total['values'][5], expected, 2)
        for section in [l for l in report['lines'] if l['kind'] == 'section'][:3]:
            self.Report.get_children('partner_ledger', self.wide, section['id'])

    def test_aged_balance_today_matches_open_items(self):
        report = self.Report.get_report('aged_balance', {'date_filter': 'today', 'partner_type': 'receivable'})
        total = report['lines'][-1]['values'][-1]
        expected = sum(self.env['account.move.line'].search([
            ('parent_state', '=', 'posted'), ('company_id', '=', self.env.company.id),
            ('date', '<=', report['options']['date_to']), ('reconciled', '=', False),
            ('account_id.account_type', '=', 'asset_receivable')]).mapped('amount_residual'))
        self.assertAlmostEqual(total, expected, 2)
        for line in report['lines']:
            # the buckets add up to the total of each line
            self.assertAlmostEqual(sum(line['values'][1:-1]), line['values'][-1], 2, line['name'])

    def test_aged_balance_at_a_past_date(self):
        partner = self.env['res.partner'].create({'name': 'Aged Test Customer'})
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': partner.id, 'invoice_date': '2026-01-10',
            'invoice_date_due': '2026-01-10',
            'invoice_line_ids': [(0, 0, {'name': 'Coffee', 'quantity': 1, 'price_unit': 100.0, 'tax_ids': []})],
        })
        invoice.action_post()
        self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=invoice.ids).create({'payment_date': '2026-02-15'}
        )._create_payments()

        def partner_total(as_of):
            report = self.Report.get_report('aged_balance', {
                'date_filter': 'custom', 'date_to': as_of, 'partner_type': 'receivable', 'search': 'Aged Test'})
            lines = [l for l in report['lines'] if l['kind'] == 'section']
            return lines[0]['values'] if lines else None

        before = partner_total('2026-01-31')
        self.assertIsNotNone(before, 'invoice unpaid at 31 January')
        self.assertAlmostEqual(before[-1], invoice.amount_total, 2)
        self.assertAlmostEqual(before[2], invoice.amount_total, 2)  # 1-30 days late
        self.assertIsNone(partner_total('2026-03-01'), 'paid on 15 February')
        section_id = 'partner-%s' % partner.id
        items = self.Report.get_children('aged_balance', {
            'date_filter': 'custom', 'date_to': '2026-01-31', 'partner_type': 'receivable'}, section_id)
        self.assertEqual(items[0]['move_id'], invoice.id)
        action = self.Report.action_open_line('aged_balance', {}, {'move_id': invoice.id})
        self.assertEqual((action['res_model'], action['res_id']), ('account.move', invoice.id))

    def test_pdf_and_xlsx(self):
        for key in ('general_ledger', 'partner_ledger', 'aged_balance'):
            pdf = self.Report.action_print_pdf(key, self.wide)
            self.assertEqual(pdf['type'], 'ir.actions.report', key)
            self.assertEqual(self.Report.get_xlsx(key, self.wide)[:2], b'PK', key)
