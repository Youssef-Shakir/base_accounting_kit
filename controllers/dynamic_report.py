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
import json

from odoo import fields, http
from odoo.http import content_disposition, request


class DynamicReportController(http.Controller):

    @http.route('/donialink_accounting/report/xlsx', type='http', auth='user', methods=['POST'])
    def report_xlsx(self, report_key, options, **kwargs):
        """XLSX export of an interactive report, with the options shown on screen."""
        Report = request.env['account.dynamic.report']
        content = Report.get_xlsx(report_key, json.loads(options))
        title = Report.get_options(report_key, json.loads(options))
        name = '%s %s.xlsx' % (report_key.replace('_', ' ').title(), title['date_to'] or fields.Date.today())
        return request.make_response(content, headers=[
            ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
            ('Content-Disposition', content_disposition(name)),
        ])

    @http.route('/donialink_accounting/partner_statement/xlsx', type='http', auth='user', methods=['GET'])
    def partner_statement_xlsx(self, partner_id, date_from, date_to, account_type='receivable',
                               target_move='posted', **kwargs):
        """XLSX of a contact's statement of account."""
        Wizard = request.env['partner.statement.wizard']
        data = {'partner_id': partner_id, 'date_from': date_from, 'date_to': date_to,
                'account_type': account_type, 'target_move': target_move}
        partner = request.env['res.partner'].browse(int(partner_id))
        name = '%s %s.xlsx' % (partner.commercial_partner_id.display_name, date_to)
        return request.make_response(Wizard.get_xlsx(data), headers=[
            ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
            ('Content-Disposition', content_disposition(name)),
        ])
