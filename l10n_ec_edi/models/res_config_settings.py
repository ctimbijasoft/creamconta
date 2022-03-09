# -*- coding: utf-8 -*-

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # == PAC web-services ==
    l10n_ec_edi_pac = fields.Selection(
        related='company_id.l10n_ec_edi_pac', readonly=False,
        string='MX PAC*')
    '''l10n_ec_edi_pac_test_env = fields.Boolean(
        related='company_id.l10n_ec_edi_pac_test_env', readonly=False,
        string='MX Jasoft test environment*')
    l10n_ec_edi_pac_username = fields.Char(
        related='company_id.l10n_ec_edi_pac_username', readonly=False,
        string='MX PAC username*')
    l10n_ec_edi_pac_password = fields.Char(
        related='company_id.l10n_ec_edi_pac_password', readonly=False,
        string='MX PAC password*')'''
    l10n_ec_edi_certificate_ids = fields.Many2many(
        related='company_id.l10n_ec_edi_certificate_ids', readonly=False,
        string='MX Certificates*')

    # == SRI EDI ==
    l10n_ec_edi_fiscal_regime = fields.Selection(
        related='company_id.l10n_ec_edi_fiscal_regime', readonly=False,
        string="Fiscal Regime",
        help="It is used to fill Ecudorian XML SRI required field ")

    l10n_ec_edi_withhold_agent = fields.Selection(
        related='company_id.l10n_ec_edi_withhold_agent', readonly=False,
        string="Agente de retención",
        help="It is used to fill Mexican XML SRI required field ")

    l10n_ec_edi_withhold_agent_number = fields.Char(
        related='company_id.l10n_ec_edi_withhold_agent_number', readonly=False,
        string="Agent. Ret. No.",
        help="It is used to fill Mexican XML SRI required field ")

    l10n_ec_edi_nc_printer_point = fields.Many2one(
        related='company_id.l10n_ec_edi_nc_printer_point', readonly=False,
        string="Printer Point N/C",
        help="It is used to default N/C Cli ")

    l10n_ec_edi_mail_template_id = fields.Many2one(
        related='company_id.l10n_ec_edi_mail_template_id',
        readonly=False,
        string="Email Template confirmation ")



