# -*- coding: utf-8 -*-
from odoo import api, fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'
    sri_payment_method = fields.Many2one('account.sri.payment.method', string='Forma de Pago', ondelete='set null')


class SriPaymentMethod(models.Model):
    _name = "account.sri.payment.method"
    _rec_name = 'payment_method_name'
    _description = "Payment Method"

    payment_method_code = fields.Char(string='Code', required=True)
    payment_method_name = fields.Char(string='Name', required=True)
    payment_method_available = fields.Boolean(string='Enabled')
    account_ids = fields.One2many('account.move', 'sri_payment_method', string='Account')
