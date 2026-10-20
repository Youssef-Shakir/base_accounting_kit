# -*- coding: utf-8 -*-
#############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2024-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Cybrosys Techno Solutions(<https://www.cybrosys.com>)
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE (LGPL v3) for more details.
#
#    You should have received a copy of the GNU LESSER GENERAL PUBLIC LICENSE
#    (LGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
#############################################################################
{
    'name': 'DoniaLink Accounting',
    'version': '18.0.5.1.0',
    'category': 'Accounting',
    'summary': 'Full accounting for Odoo Community: financial reports, assets, budgets, PDC, follow-ups, day/bank/cash books',
    'description': """
DoniaLink Accounting | محاسبة دنيا لينك
======================================

Complete accounting for Odoo 18 Community, maintained by DoniaLink for its café and
restaurant clients: profit and loss, balance sheet, trial balance, general and partner
ledgers, aged balances, cash flow, tax report, day/bank/cash books, assets, budgets,
post-dated cheques, follow-ups, recurring entries and bank statement import.

DoniaLink 18.0.5.1.0 fixes:

* Balance sheet is cumulative at the end date (it summed only the selected period)
* Equity is its own section (it was listed under Liability) and Profit (Loss) to report
  covers all unclosed results
* Depreciation is included in the profit and loss
* Report lines select accounts by account type, never by their (translatable) name
* Journal item details exclude cancelled entries and follow the report's company
* Accounts without a code no longer break the financial reports
* Odoo 19 readiness: no deprecated access checks, batch create on assets

Based on the Odoo 18 Full Accounting Kit by Cybrosys Techno Solutions (LGPL-3).
Developed by Yousif Shakir - Donialink | تطوير يوسف شاكر
    """,
    'author': 'Donialink, Yousif Shakir, Cybrosys Techno Solutions',
    'company': 'Donialink',
    'maintainer': 'Yousif Shakir',
    'website': 'https://www.donialink.com',
    'depends': ['account', 'sale', 'account_check_printing', 'analytic',
                'base_account_budget'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/account_financial_report_data.xml',
        'data/cash_flow_data.xml',
        'data/followup_levels.xml',
        'data/multiple_invoice_data.xml',
        'data/recurring_entry_cron.xml',
        'data/account_pdc_data.xml',
        'views/reports_config_view.xml',
        'views/accounting_menu.xml',
        'views/account_group.xml',
        'views/credit_limit_view.xml',
        'views/account_configuration.xml',
        'views/res_config_settings_views.xml',
        'views/account_followup.xml',
        'views/followup_line_views.xml',
        'views/followup_report.xml',
        'views/res_partner_views.xml',
        'wizard/asset_depreciation_confirmation_views.xml',
        'wizard/asset_modify_views.xml',
        'views/account_asset_asset_views.xml',
        'views/account_asset_category_views.xml',
        'views/account_move_views.xml',
        'views/product_template_views.xml',
        'views/multiple_invoice_layout_view.xml',
        'views/multiple_invoice_form.xml',
        'views/account_journal_views.xml',
        'wizard/financial_report_views.xml',
        'wizard/account_report_general_ledger_views.xml',
        'wizard/account_report_partner_ledger_views.xml',
        'wizard/kit_account_tax_report_views.xml',
        'wizard/account_balance_report_views.xml',
        'wizard/account_aged_trial_balance_views.xml',
        'wizard/account_print_journal_views.xml',
        'wizard/cash_flow_report_views.xml',
        'wizard/account_bank_book_report_views.xml',
        'wizard/account_cash_book_report_views.xml',
        'wizard/account_day_book_report_views.xml',
        'report/report_financial_template.xml',
        'report/general_ledger_report_template.xml',
        'report/report_journal_audit_template.xml',
        'report/report_aged_partner_template.xml',
        'report/report_trial_balance_template.xml',
        'report/report_tax_template.xml',
        'report/report_partner_ledger_template.xml',
        'report/cash_flow_report_template.xml',
        'report/account_bank_book_template.xml',
        'report/account_cash_book_template.xml',
        'report/account_day_book_template.xml',
        'report/account_asset_report_views.xml',
        'report/report.xml',
        'report/multiple_invoice_layouts.xml',
        'report/multiple_invoice_report_template.xml',
        'report/res_partner_reports.xml',
        'report/res_partner_templates.xml',
        'views/account_recurring_payments_view.xml',
        'views/account_move_line_views.xml',
        'views/account_bank_statement_views.xml',
        'views/account_bank_statement_line_views.xml',
        'views/account_payment_view.xml',
        'wizard/account_lock_date_views.xml',
        'wizard/import_bank_statement_views.xml',
    ],
    'external_dependencies': {
            'python': ['openpyxl', 'ofxparse', 'qifparse']
        },
    'assets': {
        'web.assets_backend': [
            'base_accounting_kit/static/src/scss/style.scss',
            'base_accounting_kit/static/src/scss/bank_rec_widget.css',
            'base_accounting_kit/static/src/js/bank_reconcile_form_list_widget.js',
            'base_accounting_kit/static/src/js/KanbanController.js',
            'base_accounting_kit/static/src/js/ListController.js',
            'base_accounting_kit/static/src/js/bank_reconcile_form_lines_widget.js',
            'base_accounting_kit/static/src/js/action_manager.js',
            'base_accounting_kit/static/src/xml/bank_rec_widget.xml',
            'base_accounting_kit/static/src/xml/bank_reconcile_widget.xml',
            'base_accounting_kit/static/src/dynamic_report/*',
        ]
    },
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,
    'application': True,
}
