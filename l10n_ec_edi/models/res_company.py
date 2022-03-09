# -*- coding: utf-8 -*-

import base64
import logging
import requests

from lxml import etree, objectify
from werkzeug.urls import url_quote
from os.path import join

from odoo import api, fields, models, tools, SUPERUSER_ID

_logger = logging.getLogger(__name__)


class ResCompany(models.Model):
    _inherit = 'res.company'

    # == PAC web-services ==
    l10n_ec_edi_pac = fields.Selection(
        selection=[('demo', 'Demo'), ('pruebas', 'Test SRI'),
                   ('produccion', 'Production SRI')],
        string='PAC',
        help='The PAC that will sign/cancel the invoices',
        default='demo')
    '''l10n_ec_edi_pac_test_env = fields.Boolean(
        string='Jasoft test environment',
        help='Enable the usage of test credentials',
        default=False)
    l10n_ec_edi_pac_username = fields.Char(
        string='PAC username',
        help='The username used to request the seal from the PAC')
    l10n_ec_edi_pac_password = fields.Char(
        string='PAC password',
        help='The password used to request the seal from the PAC')'''
    l10n_ec_edi_certificate_ids = fields.Many2many('l10n_ec_edi.certificate',
        string='Certificates')

    l10n_ec_edi_nc_printer_point = fields.Many2one('account.printer.point',
        string='Printer Point')

    # == SRI EDI ==
    l10n_ec_edi_fiscal_regime = fields.Selection(
        [('regular', 'Regimen Regular (sin msgs adicionales en el RIDE)'),
         ('micro', 'Régimen Impositivo para  Microempresas')],
        string="Fiscal Regime",
        help="It is used to fill Ecuadorian XML SRI required field "
             "Comprobante.Emisor.RegimenFiscal.")

    l10n_ec_edi_withhold_agent = fields.Selection(
        [('not_designated', 'Sin designación (sin msgs adicionales en el RIDE)'),
         ('designated_withhold_agent', 'Agente de Retención Designado')],
        string="Agente de retención",
        help="It is used to fill Ecuadorian XML SRI required field ")

    l10n_ec_edi_withhold_agent_number = fields.Char(
        string="Agent. Ret. No.",
        help="It is used to fill Ecuadorian XML SRI required field ")

    l10n_ec_edi_forced_accounting = fields.Boolean(
        string="Forced Accounting",
        help="It is used to fill Ecuadorian XML SRI required field ")

    l10n_ec_edi_mail_template_id = fields.Many2one('mail.template', string="Email Template confirmation ",
      help="Email sent to the customer once the invoice is valid.")

    def _compute_l10n_ec_edi_colony(self):
        for company in self:
            address_data = company.partner_id.sudo().address_get(adr_pref=['contact'])
            if address_data['contact']:
                partner = company.partner_id.sudo().browse(address_data['contact'])
                company.l10n_ec_edi_colony = partner.l10n_ec_edi_colony
            else:
                company.l10n_ec_edi_colony = None

    def _inverse_l10n_ec_edi_colony(self):
        for company in self:
            company.partner_id.l10n_ec_edi_colony = company.l10n_ec_edi_colony

    def _compute_l10n_ec_edi_colony_code(self):
        for company in self:
            address_data = company.partner_id.sudo().address_get(
                adr_pref=['contact'])
            if address_data['contact']:
                partner = company.partner_id.browse(address_data['contact'])
                company.l10n_ec_edi_colony_code = (
                    partner.l10n_ec_edi_colony_code)

    def _inverse_l10n_ec_edi_colony_code(self):
        for company in self:
            company.partner_id.l10n_ec_edi_colony_code = (
                company.l10n_ec_edi_colony_code)

    @api.model
    def _load_xsd_attachments(self):
        url = 'http://www.sat.gob.mx/sitio_internet/cfd/3/cfdv33.xsd'
        xml_ids = self.env['ir.model.data'].search(
            [('name', 'like', 'xsd_cached_%')])
        xsd_files = ['%s.%s' % (x.module, x.name) for x in xml_ids]
        for xsd in xsd_files:
            self.env.ref(xsd).unlink()
        self._load_xsd_files(url)

    @api.model
    def _load_xsd_files(self, url):
        fname = url.split('/')[-1]
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
        except requests.exceptions.HTTPError:
            logging.getLogger(__name__).info(
                'I cannot connect with the given URL.')
            return ''
        try:
            res = objectify.fromstring(response.content)
        except etree.XMLSyntaxError as e:
            logging.getLogger(__name__).info(
                'You are trying to load an invalid xsd file.\n%s', e)
            return ''
        namespace = {'xs': 'http://www.w3.org/2001/XMLSchema'}
        if fname == 'cfdv33.xsd':
            # This is the xsd root
            res = self._load_xsd_complements(res)
        sub_urls = res.xpath('//xs:import', namespaces=namespace)
        for s_url in sub_urls:
            s_url_catch = self._load_xsd_files(s_url.get('schemaLocation'))
            s_url.attrib['schemaLocation'] = url_quote(s_url_catch)
        try:
            xsd_string = etree.tostring(res, pretty_print=True)
        except etree.XMLSyntaxError:
            logging.getLogger(__name__).info('XSD file downloaded is not valid')
            return ''
        if not xsd_string:
            logging.getLogger(__name__).info('XSD file downloaded is empty')
            return ''
        env = api.Environment(self._cr, SUPERUSER_ID, {})
        xsd_fname = 'xsd_cached_%s' % fname.replace('.', '_')
        attachment = env.ref('l10n_ec_edi.%s' % xsd_fname, False)
        filestore = tools.config.filestore(self._cr.dbname)
        if attachment:
            return join(filestore, attachment.store_fname)
        attachment = env['ir.attachment'].create({
            'name': xsd_fname,
            'datas': base64.encodebytes(xsd_string),
        })
        # Forcing the triggering of the store_fname
        attachment._inverse_datas()
        self._cr.execute(
            """INSERT INTO ir_model_data
            (name, res_id, module, model, noupdate)
            VALUES (%s, %s, 'l10n_ec_edi', 'ir.attachment', true)""", (
                xsd_fname, attachment.id))
        return join(filestore, attachment.store_fname)

    @api.model
    def _load_xsd_complements(self, content):
        complements = [
            ['http://www.sat.gob.mx/servicioparcialconstruccion',
             'http://www.sat.gob.mx/sitio_internet/cfd/servicioparcialconstruccion/servicioparcialconstruccion.xsd'],
            ['http://www.sat.gob.mx/EstadoDeCuentaCombustible',
             'http://www.sat.gob.mx/sitio_internet/cfd/EstadoDeCuentaCombustible/ecc12.xsd'],
            ['http://www.sat.gob.mx/donat',
             'http://www.sat.gob.mx/sitio_internet/cfd/donat/donat11.xsd'],
            ['http://www.sat.gob.mx/divisas',
             'http://www.sat.gob.mx/sitio_internet/cfd/divisas/Divisas.xsd'],
            ['http://www.sat.gob.mx/implocal',
             'http://www.sat.gob.mx/sitio_internet/cfd/implocal/implocal.xsd'],
            ['http://www.sat.gob.mx/leyendasFiscales',
             'http://www.sat.gob.mx/sitio_internet/cfd/leyendasFiscales/leyendasFisc.xsd'],
            ['http://www.sat.gob.mx/pfic',
             'http://www.sat.gob.mx/sitio_internet/cfd/pfic/pfic.xsd'],
            ['http://www.sat.gob.mx/TuristaPasajeroExtranjero',
             'http://www.sat.gob.mx/sitio_internet/cfd/TuristaPasajeroExtranjero/TuristaPasajeroExtranjero.xsd'],
            ['http://www.sat.gob.mx/detallista',
             'http://www.sat.gob.mx/sitio_internet/cfd/detallista/detallista.xsd'],
            ['http://www.sat.gob.mx/registrofiscal',
             'http://www.sat.gob.mx/sitio_internet/cfd/sriregistrofiscal/sriregistrofiscal.xsd'],
            ['http://www.sat.gob.mx/nomina12',
             'http://www.sat.gob.mx/sitio_internet/cfd/nomina/nomina12.xsd'],
            ['http://www.sat.gob.mx/pagoenespecie',
             'http://www.sat.gob.mx/sitio_internet/cfd/pagoenespecie/pagoenespecie.xsd'],
            ['http://www.sat.gob.mx/valesdedespensa',
             'http://www.sat.gob.mx/sitio_internet/cfd/valesdedespensa/valesdedespensa.xsd'],
            ['http://www.sat.gob.mx/consumodecombustibles',
             'http://www.sat.gob.mx/sitio_internet/cfd/consumodecombustibles/consumodecombustibles.xsd'],
            ['http://www.sat.gob.mx/aerolineas',
             'http://www.sat.gob.mx/sitio_internet/cfd/aerolineas/aerolineas.xsd'],
            ['http://www.sat.gob.mx/notariospublicos',
             'http://www.sat.gob.mx/sitio_internet/cfd/notariospublicos/notariospublicos.xsd'],
            ['http://www.sat.gob.mx/vehiculousado',
             'http://www.sat.gob.mx/sitio_internet/cfd/vehiculousado/vehiculousado.xsd'],
            ['http://www.sat.gob.mx/renovacionysustitucionvehiculos',
             'http://www.sat.gob.mx/sitio_internet/cfd/renovacionysustitucionvehiculos/renovacionysustitucionvehiculos.xsd'],
            ['http://www.sat.gob.mx/certificadodestruccion',
             'http://www.sat.gob.mx/sitio_internet/cfd/certificadodestruccion/certificadodedestruccion.xsd'],
            ['http://www.sat.gob.mx/arteantiguedades',
             'http://www.sat.gob.mx/sitio_internet/cfd/arteantiguedades/obrasarteantiguedades.xsd'],
            ['http://www.sat.gob.mx/ComercioExterior11',
             'http://www.sat.gob.mx/sitio_internet/cfd/ComercioExterior11/ComercioExterior11.xsd'],
            ['http://www.sat.gob.mx/Pagos',
             'http://www.sat.gob.mx/sitio_internet/cfd/Pagos/Pagos10.xsd'],
            ['http://www.sat.gob.mx/iedu',
             'http://www.sat.gob.mx/sitio_internet/cfd/iedu/iedu.xsd'],
            ['http://www.sat.gob.mx/ventavehiculos',
             'http://www.sat.gob.mx/sitio_internet/cfd/ventavehiculos/ventavehiculos11.xsd'],
            ['http://www.sat.gob.mx/terceros',
             'http://www.sat.gob.mx/sitio_internet/cfd/terceros/terceros11.xsd'],
            ['http://www.sat.gob.mx/spei',
             'http://www.sat.gob.mx/sitio_internet/cfd/spei/spei.xsd'],
            ['http://www.sat.gob.mx/ine',
             'http://www.sat.gob.mx/sitio_internet/cfd/ine/INE11.xsd'],
            ['http://www.sat.gob.mx/acreditamiento',
             'http://www.sat.gob.mx/sitio_internet/cfd/acreditamiento/AcreditamientoIEPS10.xsd'],
            ['http://www.sat.gob.mx/TimbreFiscalDigital',
             'http://www.sat.gob.mx/sitio_internet/cfd/TimbreFiscalDigital/TimbreFiscalDigitalv11.xsd'],
        ]
        for complement in complements:
            xsd = {'namespace': complement[0], 'schemaLocation': complement[1]}
            node = etree.Element('{http://www.w3.org/2001/XMLSchema}import', xsd)
            content.insert(0, node)
        return content
