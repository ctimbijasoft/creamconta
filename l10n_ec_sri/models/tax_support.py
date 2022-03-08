# -*- coding: utf-8 -*-
from odoo import api, fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'
    tax_support_id = fields.Many2one('account.sri.tax.support', string="Sustento Tributario", ondelete='set null')


class TaxSupport(models.Model):
    _name = "account.sri.tax.support"
    _description = "Sustento Tributario"
    _rec_name = 'name'

    code = fields.Char(string='Código', required=True)
    name = fields.Char(string='Nombre', required=True)
    priority = fields.Integer(string='Prioridad', required=True)
    enabled = fields.Boolean(string='Enabled')
    account_ids = fields.One2many('account.move', 'tax_support_id', string='Account')
