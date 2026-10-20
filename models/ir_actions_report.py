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
from odoo import models


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    def report_action(self, docids, data=None, config=True):
        """Open the report as a web page inside Odoo instead of downloading a PDF
        when the wizard's "View" button asks for it (context key report_view_html).
        The web page has its own Print button."""
        action = super().report_action(docids, data=data, config=config)
        if self.env.context.get('report_view_html') and action.get('report_type') == 'qweb-pdf':
            action['report_type'] = 'qweb-html'
        return action
