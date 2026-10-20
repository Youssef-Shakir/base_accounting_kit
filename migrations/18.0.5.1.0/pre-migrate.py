# -*- coding: utf-8 -*-
"""18.0.5.1.0 (DoniaLink): the standard financial report trees were loaded as noupdate
data, so their fixes would never reach existing databases. Let this upgrade rewrite them
(account types per line, equity section, depreciation, cumulative balance sheet)."""


STANDARD_TREES = (
    'account_financial_report_profitandloss0', 'account_financial_report_income0',
    'account_financial_report_other_income0', 'financial_report_gross_profit',
    'financial_report_cost_of_revenue', 'account_financial_report_operating_income0',
    'account_financial_report_expense0', 'account_financial_report_balancesheet0',
    'account_financial_report_assets0', 'account_financial_report_liabilitysum0',
    'account_financial_report_liability0', 'account_financial_report_profitloss_toreport0',
)


def migrate(cr, version):
    cr.execute("""
        UPDATE ir_model_data
           SET noupdate = false
         WHERE module = 'base_accounting_kit'
           AND model = 'account.financial.report'
           AND name IN %s
    """, [STANDARD_TREES])
    # the common report wizard form was declared as noupdate data: let upgrades update it
    cr.execute("""
        UPDATE ir_model_data
           SET noupdate = false
         WHERE module = 'base_accounting_kit' AND name = 'account_report_view_form'
    """)
