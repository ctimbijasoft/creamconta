# coding: utf-8
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class ResCurrency(models.Model):
    _inherit = 'res.currency'

    l10n_ec_edi_decimal_places = fields.Integer(
        'Number of decimals', readonly=True,
        help='Number of decimals to be supported for this currency, according '
        'to the SAT. It will be used in the SRI to format amounts.')
