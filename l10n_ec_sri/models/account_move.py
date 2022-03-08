# -*- coding: utf-8 -*-
from odoo import api, fields, models

import logging

_logger = logging.getLogger(__name__)

class AccountMove(models.Model):
    _inherit = 'account.move'
    ref_account = fields.Char(string='Referencia Factura', required=False)

    # ==== SRI attachment fields ====
    l10n_ec_edi_sri_access_key = fields.Char(string='UUID', copy=True,
                                       help='Folio in electronic invoice, is returned by SRI when send to stamp.')