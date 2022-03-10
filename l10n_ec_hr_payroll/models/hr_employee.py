# -*- coding: utf-8 -*-

from odoo import models, fields, api


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    acumula_fondos_reserva = fields.Boolean(string="Acumula fondos de reserva", default=True)
    acumula_xiii_salario = fields.Boolean(string="Acumula XIII salario", default=True)
    acumula_xiv_salario = fields.Boolean(string="Acumula XIV salario", default=True)
