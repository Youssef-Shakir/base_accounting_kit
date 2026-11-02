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
"""Statement of account of a contact, printed, exported, e-mailed or opened in the
partner ledger (DoniaLink)."""
import base64
import io

from werkzeug.urls import url_encode

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import xlsxwriter


class PartnerStatementWizard(models.TransientModel):
    _name = 'partner.statement.wizard'
    _description = 'Statement of Account'

    partner_id = fields.Many2one('res.partner', string='Partner', required=True)
    date_from = fields.Date(string='From', required=True,
                            default=lambda self: self.env.company.compute_fiscalyear_dates(
                                fields.Date.context_today(self))['date_from'])
    date_to = fields.Date(string='To', required=True, default=fields.Date.context_today)
    account_type = fields.Selection([('receivable', 'Receivable'), ('payable', 'Payable'),
                                      ('both', 'Receivable and Payable')],
                                     string='Accounts', required=True, default='receivable')
    target_move = fields.Selection([('posted', 'Posted entries'), ('all', 'Including drafts')],
                                   string='Entries', required=True, default='posted')

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        partner = self.env['res.partner'].browse(values.get('partner_id'))
        if partner and 'account_type' in fields_list:
            # a supplier gets its payable statement, a contact that is both gets both sides
            if partner.supplier_rank and partner.customer_rank:
                values['account_type'] = 'both'
            elif partner.supplier_rank:
                values['account_type'] = 'payable'
        return values

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for wizard in self:
            if wizard.date_from > wizard.date_to:
                raise UserError(_('The start date must be before the end date.'))

    def _report_data(self):
        self.ensure_one()
        return {'partner_id': self.partner_id.id, 'date_from': fields.Date.to_string(self.date_from),
                'date_to': fields.Date.to_string(self.date_to), 'account_type': self.account_type,
                'target_move': self.target_move}

    def _file_name(self, extension):
        return '%s - %s %s.%s' % (_('Statement'), self.partner_id.commercial_partner_id.display_name,
                                  fields.Date.to_string(self.date_to), extension)

    def action_print_pdf(self):
        return self.env.ref('base_accounting_kit.action_report_partner_statement').report_action(
            self.partner_id, data=self._report_data())

    def action_print_xlsx(self):
        return {'type': 'ir.actions.act_url', 'target': 'download',
                'url': '/donialink_accounting/partner_statement/xlsx?%s' % url_encode(self._report_data())}

    def action_send_email(self):
        """The mail composer, with the statement PDF attached, to check before sending."""
        self.ensure_one()
        partner = self.partner_id.commercial_partner_id
        pdf, _type = self.env['ir.actions.report']._render_qweb_pdf(
            'base_accounting_kit.action_report_partner_statement', partner.ids, data=self._report_data())
        attachment = self.env['ir.attachment'].create({
            'name': self._file_name('pdf'), 'type': 'binary', 'datas': base64.b64encode(pdf),
            'mimetype': 'application/pdf', 'res_model': 'mail.compose.message',
        })
        return {
            'type': 'ir.actions.act_window', 'res_model': 'mail.compose.message', 'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_model': 'res.partner', 'default_res_ids': partner.ids,
                'default_composition_mode': 'comment', 'default_partner_ids': partner.ids,
                'default_subject': _('Statement of Account %(from)s - %(to)s', **{
                    'from': self.date_from, 'to': self.date_to}),
                'default_body': _('<p>Dear %s,</p><p>Please find attached your statement of account.</p>',
                                  partner.name),
                'default_attachment_ids': attachment.ids,
            },
        }

    def action_open_ledger(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('base_accounting_kit.action_dynamic_partner_ledger')
        action['params'] = dict(action.get('params') or {}, options={
            'date_filter': 'custom', 'date_from': fields.Date.to_string(self.date_from),
            'date_to': fields.Date.to_string(self.date_to), 'partner_type': self.account_type,
            'target_move': self.target_move, 'partner_id': self.partner_id.commercial_partner_id.id,
            'unfold_all': True})
        action['name'] = _('Partner Ledger: %s', self.partner_id.commercial_partner_id.display_name)
        return action

    @api.model
    def get_xlsx(self, data):
        """The statement as an XLSX file (bytes)."""
        partner = self.env['res.partner'].browse(int(data['partner_id'])).exists()
        if not partner:
            raise UserError(_('The partner no longer exists.'))
        st = partner._dl_statement(data['date_from'], data['date_to'], data.get('account_type') or 'receivable',
                                   data.get('target_move') or 'posted')
        currency = st['currency']
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet(_('Statement')[:31])
        if self.env['res.lang']._lang_get(self.env.lang or 'en_US').direction == 'rtl':
            sheet.right_to_left()
        money = '#,##0' + ('.' + '0' * currency.decimal_places if currency.decimal_places else '')
        f_title = workbook.add_format({'bold': True, 'font_size': 14})
        f_bold = workbook.add_format({'bold': True})
        f_head = workbook.add_format({'bold': True, 'bottom': 1, 'align': 'center'})
        f_date = workbook.add_format({'num_format': 'yyyy-mm-dd'})
        f_amount = workbook.add_format({'num_format': money})
        f_total = workbook.add_format({'bold': True, 'top': 1, 'num_format': money})

        sheet.write(0, 0, _('Statement of Account'), f_title)
        sheet.write(1, 0, st['company'].name)
        sheet.write(2, 0, st['partner'].display_name, f_bold)
        sheet.write(3, 0, '%s - %s' % (st['date_from'], st['date_to']))
        headers = [_('Date'), _('Reference'), _('Description'), _('Due Date'), _('Debit'), _('Credit'), _('Balance')]
        for col, width in enumerate((12, 22, 40, 12, 16, 16, 16)):
            sheet.set_column(col, col, width)
        row = 5
        for col, name in enumerate(headers):
            sheet.write(row, col, name, f_head)
        row += 1
        sheet.write(row, 2, _('Opening Balance'), f_bold)
        sheet.write_number(row, 6, st['opening'], f_amount)
        for line in st['lines']:
            row += 1
            sheet.write_datetime(row, 0, fields.Datetime.to_datetime(line['date']), f_date)
            sheet.write_string(row, 1, line['reference'])
            sheet.write_string(row, 2, line['description'])
            if line['due_date']:
                sheet.write_datetime(row, 3, fields.Datetime.to_datetime(line['due_date']), f_date)
            sheet.write_number(row, 4, line['debit'], f_amount)
            sheet.write_number(row, 5, line['credit'], f_amount)
            sheet.write_number(row, 6, line['balance'], f_amount)
        row += 1
        sheet.write(row, 2, st['closing_label'], f_bold)
        sheet.write_number(row, 4, st['total_debit'], f_total)
        sheet.write_number(row, 5, st['total_credit'], f_total)
        sheet.write_number(row, 6, st['closing'], f_total)
        if st['ageing']:
            row += 2
            for col, bucket in enumerate(st['ageing']):
                sheet.write(row, col, bucket['name'], f_head)
                sheet.write_number(row + 1, col, bucket['amount'], f_amount)
        sheet.freeze_panes(6, 0)
        workbook.close()
        return output.getvalue()


class ReportPartnerStatement(models.AbstractModel):
    _name = 'report.base_accounting_kit.report_partner_statement'
    _description = 'Statement of Account Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        data = data or {}
        partners = self.env['res.partner'].browse(docids or [data.get('partner_id')]).exists()
        if not data.get('date_to'):
            raise UserError(_('Print the statement from the contact: Customer Statement › Statement of Account.'))
        statements = [partner._dl_statement(data.get('date_from'), data['date_to'],
                                            data.get('account_type') or 'receivable',
                                            data.get('target_move') or 'posted')
                      for partner in partners.commercial_partner_id]
        return {'doc_ids': partners.ids, 'doc_model': 'res.partner', 'docs': partners,
                'statements': statements, 'data': data}
