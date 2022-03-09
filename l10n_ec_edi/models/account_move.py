# -*- coding: utf-8 -*-

from odoo import api, fields, models, tools, _
from odoo.exceptions import ValidationError, UserError
from odoo.tools.float_utils import float_repr

import base64
import random

import logging
from lxml import etree
from lxml.objectify import fromstring
from pytz import timezone
from datetime import datetime
from dateutil.relativedelta import relativedelta

from zeep import Client
from zeep.transports import Transport

SRI_XSLT_CADENA = 'l10n_ec_edi/data/2_20/cadenaoriginal.xslt'
SRI_XSLT_CADENA_TFD = 'l10n_ec_edi/data/xslt/2_20/cadenaoriginal_TFD_1_1.xslt'

_logger = logging.getLogger(__name__)

class AccountMove(models.Model):
    _inherit = 'account.move'

    #name = fields.Char(string='Number', copy=False, readonly=False, store=True, index=True, tracking=True)


    # ==== SRI flow fields ====
    l10n_ec_edi_sri_request = fields.Selection(
        selection=[
            ('on_invoice', "On Invoice"),
            ('on_refund', "On Credit Note"),
            ('on_payment', "On Payment"),
        ],
        string="Request a SRI", store=True,
        compute='_compute_l10n_ec_edi_sri_request',
        help="Flag indicating a SRI should be generated for this journal entry.")
    l10n_ec_edi_sat_status = fields.Selection(
        selection=[
            ('none', "State not defined"),
            ('undefined', "Not Synced Yet"),
            ('not_found', "Not Found"),
            ('cancelled', "Cancelled"),
            ('valid', "Valid"),
        ],
        string="SRI status", readonly=True, copy=False, required=True, tracking=True,
        default='undefined',
        help="Refers to the status of the journal entry inside the SAT system.")
    l10n_ec_edi_post_time = fields.Datetime(
        string="Posted Time", readonly=True, copy=False,
        help="Keep empty to use the current México central time")
    l10n_ec_edi_auth_time = fields.Datetime(
        string="Posted Time", readonly=True, copy=False,
        help="Keep empty to use the current México central time")
    l10n_ec_edi_amount_iva = fields.Monetary(string='Subtotal IVA', copy=False, readonly=True,
        help='The total amount reported on the sri with IVA',
        compute ='_compute_amount_taxes')
    l10n_ec_edi_amount_iva_zero = fields.Monetary(string='Subtotal 0%', copy=False, readonly=True,
        help='The total amount reported on the sri without IVA',
        compute ='_compute_amount_taxes')



    '''l10n_ec_edi_usage = fields.Selection(
        selection=[
            ('G01', 'Acquisition of merchandise'),
            ('G02', 'Returns, discounts or bonuses'),
            ('G03', 'General expenses'),
            ('I01', 'Constructions'),
            ('I02', 'Office furniture and equipment investment'),
            ('I03', 'Transportation equipment'),
            ('I04', 'Computer equipment and accessories'),
            ('I05', 'Dices, dies, molds, matrices and tooling'),
            ('I06', 'Telephone communications'),
            ('I07', 'Satellite communications'),
            ('I08', 'Other machinery and equipment'),
            ('D01', 'Medical, dental and hospital expenses.'),
            ('D02', 'Medical expenses for disability'),
            ('D03', 'Funeral expenses'),
            ('D04', 'Donations'),
            ('D05', 'Real interest effectively paid for mortgage loans (room house)'),
            ('D06', 'Voluntary contributions to SAR'),
            ('D07', 'Medical insurance premiums'),
            ('D08', 'Mandatory School Transportation Expenses'),
            ('D09', 'Deposits in savings accounts, premiums based on pension plans.'),
            ('D10', 'Payments for educational services (Colegiatura)'),
            ('P01', 'To define'),
        ],
        string="Usage",
        default='P01',
        help="Used in SRI 2_20 to express the key to the usage that will gives the receiver to this invoice. This "
             "value is defined by the customer.\nNote: It is not cause for cancellation if the key set is not the usage "
             "that will give the receiver of the document.")
    l10n_ec_edi_origin = fields.Char(
        string='SRI Origin',
        copy=False,
        help="In some cases like payments, credit notes, debit notes, invoices re-signed or invoices that are redone "
             "due to payment in advance will need this field filled, the format is:\n"
             "Origin Type|UUID1, UUID2, ...., UUIDn.\n"
             "Where the origin type could be:\n"
             "- 01: Nota de crédito\n"
             "- 02: Nota de débito de los documentos relacionados\n"
             "- 03: Devolución de mercancía sobre facturas o traslados previos\n"
             "- 04: Sustitución de los SRI previos\n"
             "- 05: Traslados de mercancias facturados previamente\n"
             "- 06: Factura generada por los traslados previos\n"
             "- 07: SRI por aplicación de anticipo")'''

    # ==== SRI certificate fields ====
    l10n_ec_edi_certificate_id = fields.Many2one(
        comodel_name='l10n_ec_edi.certificate',
        string="Source Certificate")
    l10n_ec_edi_cer_source = fields.Char(
        string='Certificate Source',
        help="Used in SRI like attribute derived from the exception of certificates of Origin of the "
             "Free Trade Agreements that Mexico has celebrated with several countries. If it has a value, it will "
             "indicate that it serves as certificate of origin and this value will be set in the SRI node "
             "'NumCertificadoOrigen'.")

    # ==== SRI attachment fields ====
    l10n_ec_edi_sri_uuid = fields.Char(string='UUID', copy=False, readonly=True,
        help='Folio in electronic invoice, is returned by SAT when send to stamp.')

    l10n_ec_edi_sri_supplier_rfc = fields.Char(string='Supplier RFC', copy=False, readonly=True,
        help='The supplier tax identification number.',
        compute='_compute_sri_values')
    l10n_ec_edi_sri_customer_rfc = fields.Char(string='Customer RFC', copy=False, readonly=True,
        help='The customer tax identification number.',
        compute='_compute_sri_values')
    l10n_ec_edi_sri_amount = fields.Monetary(string='Total Amount', copy=False, readonly=True,
        help='The total amount reported on the sri.',
        compute='_compute_sri_values')

    # ==== Other fields ====
    l10n_ec_edi_payment_method_id = fields.Many2one('l10n_ec_edi.payment.method',
        string="Payment Way",
        help="Indicates the way the invoice was/will be paid, where the options could be: "
             "Cash, Nominal Check, Credit Card, etc. Leave empty if unkown and the XML will show 'Unidentified'.",
        default=lambda self: self.env.ref('l10n_ec_edi.payment_method_otros', raise_if_not_found=False))
    l10n_ec_edi_payment_policy = fields.Selection(string='Payment Policy',
        selection=[('PPD', 'PPD'), ('PUE', 'PUE')],
        compute='_compute_l10n_ec_edi_payment_policy')

    printer_point = fields.Many2one('account.printer.point', string='Printer Point', ondelete='set null')


    # -------------------------------------------------------------------------
    # HELPERS
    # -------------------------------------------------------------------------

    def _get_l10n_ec_edi_signed_edi_document(self):
        self.ensure_one()

        sri_ec_edi = self.env.ref('l10n_ec_edi.edi_sri_ec')
        return self.edi_document_ids.filtered(lambda document: document.edi_format_id == sri_ec_edi and document.attachment_id)

    def _get_l10n_ec_edi_issued_address(self):
        self.ensure_one()
        return self.company_id.partner_id.commercial_partner_id

    def _l10n_ec_edi_decode_sri(self, sri_data=None):
        ''' Helper to extract relevant data from the SRI to be used, for example, when printing the invoice.
        :param sri_data:   The optional sri data.
        :return:            A python dictionary.
        '''
        self.ensure_one()

        def get_node(sri_node, attribute, namespaces):
            if hasattr(sri_node, 'Complemento'):
                node = sri_node.Complemento.xpath(attribute, namespaces=namespaces)
                return node[0] if node else None
            else:
                return None

        def get_cadena(sri_node, template):
            if sri_node is None:
                return None
            cadena_root = etree.parse(tools.file_open(template))
            return str(etree.XSLT(cadena_root)(sri_node))

        # Find a signed sri.
        if not sri_data:
            signed_edi = self._get_l10n_ec_edi_signed_edi_document()
            _logger.warning(166)
            _logger.warning(signed_edi)
            if signed_edi:
                sri_data = base64.decodebytes(signed_edi.attachment_id.with_context(bin_size=False).datas)

        # Nothing to decode.
        if not sri_data:
            return {}
        _logger.info(172)
        _logger.warning(sri_data)
        '''sri_node = fromstring(sri_data)
        tfd_node = get_node(
            sri_node,
            'tfd:TimbreFiscalDigital[1]',
            {'tfd': 'http://www.sat.gob.mx/TimbreFiscalDigital'},
        )
        _logger.warning(180)
        _logger.warning(sri_node)'''

        return {
            'uuid': ({} if tfd_node is None else tfd_node).get('UUID'),
            #'supplier_rfc': sri_node.Emisor.get('Rfc', sri_node.Emisor.get('rfc')),
            'customer_rfc': sri_node.Receptor.get('Rfc', sri_node.Receptor.get('rfc')),
            'amount_total': sri_node.get('Total', sri_node.get('total')),
            'sri_node': sri_node,
            'usage': sri_node.Receptor.get('UsoSRI'),
            'payment_method': sri_node.get('formaDePago', sri_node.get('MetodoPago')),
            'bank_account': sri_node.get('NumCtaPago'),
            'sello': sri_node.get('sello', sri_node.get('Sello', 'No identificado')),
            'sello_sat': tfd_node is not None and tfd_node.get('selloSAT', tfd_node.get('SelloSAT', 'No identificado')),
            'cadena': get_cadena(sri_node, SRI_XSLT_CADENA),
            'certificate_number': sri_node.get('noCertificado', sri_node.get('NoCertificado')),
            'certificate_sat_number': tfd_node is not None and tfd_node.get('NoCertificadoSAT'),
            'expedition': sri_node.get('LugarExpedicion'),
            'fiscal_regime': sri_node.Emisor.get('RegimenFiscal', ''),
            'emission_date_str': sri_node.get('fecha', sri_node.get('Fecha', '')).replace('T', ' '),
            'stamp_date': tfd_node is not None and tfd_node.get('FechaTimbrado', '').replace('T', ' '),
        }

    @api.model
    def _l10n_ec_edi_sri_amount_to_text(self):
        """Method to transform a float amount to text words
        E.g. 100 - ONE HUNDRED
        :returns: Amount transformed to words mexican format for invoices
        :rtype: str
        """
        self.ensure_one()

        currency_name = self.currency_id.name.upper()

        # M.N. = Moneda Nacional (National Currency)
        # M.E. = Moneda Extranjera (Foreign Currency)
        currency_type = 'M.N' if currency_name == 'USD' else 'M.E.'

        # Split integer and decimal part
        amount_i, amount_d = divmod(self.amount_total, 1)
        amount_d = round(amount_d, 2)
        amount_d = int(round(amount_d * 100, 2))

        words = self.currency_id.with_context(lang=self.partner_id.lang or 'es_ES').amount_to_text(amount_i).upper()
        return '%(words)s %(amount_d)02d/100 %(currency_type)s' % {
            'words': words,
            'amount_d': amount_d,
            'currency_type': currency_type,
        }

    @api.model
    def _l10n_ec_edi_write_sri_origin(self, code, uuids):
        ''' Format the code and uuids passed as parameter in order to fill the l10n_ec_edi_origin field.
        The code corresponds to the following types:
            - 01: Nota de crédito
            - 02: Nota de débito de los documentos relacionados
            - 03: Devolución de mercancía sobre facturas o traslados previos
            - 04: Sustitución de los SRI previos
            - 05: Traslados de mercancias facturados previamente
            - 06: Factura generada por los traslados previos
            - 07: SRI por aplicación de anticipo

        The generated string must match the following template:
        <code>|<uuid1>,<uuid2>,...,<uuidn>

        :param code:    A valid code as a string between 01 and 07.
        :param uuids:   A list of uuids returned by the government.
        :return:        A valid string to be put inside the l10n_ec_edi_origin field.
        '''
        return '%s|%s' % (code, ','.join(uuids))

    '''@api.model
    def _l10n_ec_edi_read_sri_origin(self, sri_origin):
        splitted = sri_origin.split('|')
        if len(splitted) != 2:
            return False

        try:
            code = int(splitted[0])
        except ValueError:
            return False

        if code < 1 or code > 7:
            return False
        return splitted[0], [uuid.strip() for uuid in splitted[1].split(',')]'''

    @api.model
    def _l10n_ec_edi_get_sri_partner_timezone(self, partner):
        code = partner.state_id.code

        # By default, takes the central area timezone
        return timezone('America/Guayaquil')

    # -------------------------------------------------------------------------
    # COMPUTE METHODS
    # -------------------------------------------------------------------------

    @api.depends('move_type', 'company_id')
    def _compute_l10n_ec_edi_sri_request(self):
        for move in self:
            if move.country_code != 'EC':
                move.l10n_ec_edi_sri_request = False
            elif move.move_type == 'out_invoice':
                move.l10n_ec_edi_sri_request = 'on_invoice'
            elif move.move_type == 'out_refund':
                move.l10n_ec_edi_sri_request = 'on_refund'
            else:
                move.l10n_ec_edi_sri_request = False

    @api.depends('amount_by_group')
    def _compute_amount_taxes(self):
        _logger.warning('l10n_ec_edi_amount_iva_zero')
        amount_iva = 0.0
        for move in self:
            for tax in move.amount_by_group:
                if "IVA" in tax[0]:
                    amount_iva += tax[2]
            move.l10n_ec_edi_amount_iva_zero = 0.0
            move.l10n_ec_edi_amount_iva = amount_iva
            move.l10n_ec_edi_amount_iva_zero = move.amount_untaxed - amount_iva

    @api.depends('edi_document_ids')   #*************************
    def _compute_sri_values(self):
        '''Fill the invoice fields from the sri values.
        '''
        _logger.info('_compute_sri_values')
        '''for move in self:
            #sri_infos = move._l10n_ec_edi_decode_sri()  #_10

            move.l10n_ec_edi_sri_uuid = "sri_infos.get('uuid')"
            move.l10n_ec_edi_sri_supplier_rfc = "sri_infos.get('supplier_rfc')"
            move.l10n_ec_edi_sri_customer_rfc = "sri_infos.get('customer_rfc')"
            move.l10n_ec_edi_sri_amount = 198989#"sri_infos.get('amount_total')"'''

    '''@api.depends('move_type', 'invoice_date_due', 'invoice_date', 'invoice_payment_term_id', 'invoice_payment_term_id.line_ids')
    def _compute_l10n_ec_edi_payment_policy(self):
        for move in self:
            if move.is_invoice(include_receipts=True) and move.invoice_date_due and move.invoice_date:
                if move.move_type == 'out_invoice':
                    # In SRI 2_20 - rule 2.7.1.43 which establish that
                    # invoice payment term should be PPD as soon as the due date
                    # is after the last day of  the month (the month of the invoice date).
                    if move.invoice_date_due.month > move.invoice_date.month or \
                       move.invoice_date_due.year > move.invoice_date.year or \
                       len(move.invoice_payment_term_id.line_ids) > 1:  # to be able to force PPD
                        move.l10n_ec_edi_payment_policy = 'PPD'
                    else:
                        move.l10n_ec_edi_payment_policy = 'PUE'
                else:
                    move.l10n_ec_edi_payment_policy = 'PUE'
            else:
                move.l10n_ec_edi_payment_policy = False
                '''

    # -------------------------------------------------------------------------
    # CONSTRAINTS
    # -------------------------------------------------------------------------

    #@api.constrains('l10n_ec_edi_origin')
    '''def _check_l10n_ec_edi_origin(self):
        error_message = _("The following SRI origin %s is invalid and must match the "
                          "<code>|<uuid1>,<uuid2>,...,<uuidn> template.\n"
                          "Here are the specification of this value:\n"
                          "- 01: Nota de crédito\n"
                          "- 02: Nota de débito de los documentos relacionados\n"
                          "- 03: Devolución de mercancía sobre facturas o traslados previos\n"
                          "- 04: Sustitución de los SRI previos\n"
                          "- 05: Traslados de mercancias facturados previamente\n"
                          "- 06: Factura generada por los traslados previos\n"
                          "- 07: SRI por aplicación de anticipo\n"
                          "For example: 01|89966ACC-0F5C-447D-AEF3-3EED22E711EE,89966ACC-0F5C-447D-AEF3-3EED22E711EE")

        for move in self:
            if not move.l10n_ec_edi_origin:
                continue

            # This method
            decoded_origin = move._l10n_ec_edi_read_sri_origin(move.l10n_ec_edi_origin)
            if not decoded_origin:
                raise ValidationError(error_message % move.l10n_ec_edi_origin)'''

    # -------------------------------------------------------------------------
    # SAT
    # -------------------------------------------------------------------------
    def _l10n_ec_edi_get_edi_credentials(self, edi_pac):
        if not edi_pac:
            return {
                'errors': [_("The environment is missing.")]
            }
        if edi_pac == 'pruebas':
            return {
                'environment': '1',
                'reception_url': 'https://celcer.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline?wsdl',
                'authorization_url': 'https://celcer.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantesOffline?wsdl',
            }
        else:
            if edi_pac == 'produccion':
                return {
                    'environment': '2',
                    'reception_url': 'https://cel.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline?wsdl',
                    'authorization_url': 'https://cel.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantesOffline?wsdl',
                }
            elif edi_pac == 'proudccion':
                return {
                    'environment': '2',
                    'reception_url': 'https://cel.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline?wsdl',
                    'authorization_url': 'https://cel.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantesOffline?wsdl',
                }
            else:
                return {
                    'environment': '0',
                    'reception_url': '',
                    'authorization_url': '',
                }


    def _l10n_ec_edi_sri_authorization(self, credentials, uuid):
        try:
            transport = Transport(timeout=20)
            client = Client(credentials['authorization_url'], transport=transport)
            response = client.service.autorizacionComprobante(uuid)
        except Exception as e:
            return {
                'errors': [_("The SRI service failed to validate with the following error: %s", str(e))],
            }

        #_logger.warning(response.autorizaciones)
        errors = []

        for autorizacion in response.autorizaciones['autorizacion']:
            autorizacion.comprobante = ''
            _logger.warning(autorizacion)
            errors.append(_("Clave de acceso : %s") % response.claveAccesoConsultada)
            _logger.warning(412)
            _logger.warning(autorizacion.estado)
            if autorizacion.estado == 'AUTORIZADO':
                for move in self:
                    move.l10n_ec_edi_auth_time = autorizacion.fechaAutorizacion.utcnow()

            else:
                for mensaje in autorizacion['mensajes'].mensaje:
                    errors.append(_("%s: %s") % (mensaje.mensaje, mensaje.informacionAdicional))
                return {'errors': errors}

        return {'status': 'OK'}


    def _l10n_ec_edi_format_error_message(self, error_title, errors):
        bullet_list_msg = ''.join('\n\t%s' % msg for msg in errors)
        return '%s%s' % (error_title, bullet_list_msg)

    def _create_sri_attachment_pdf(self, invoice):
        sri_filename = ('%s-%s.pdf' % (invoice.journal_id.code, invoice.name)).replace('/', '')
        pdf = self.env.ref('account.account_invoices')._render_qweb_pdf(self.id)[0]
        pdf = base64.b64encode(pdf)
        return self.env['ir.attachment'].create({
            'name': sri_filename,
            'type': 'binary',
            'datas': pdf,
            'res_model': invoice._name,
            'res_id': invoice.id,
            'mimetype': 'application/x-pdf'
        })

    def button_cancel_posted_moves(self):
        # OVERRIDE
        for invoice in self:
            _logger.warning(476)
            _logger.warning(invoice.edi_state)
            _logger.warning(invoice.l10n_ec_edi_sat_status)
            if invoice.l10n_ec_edi_sat_status == 'valid':
                raise ValidationError(_(
                    '%s ') % 'Comprobante no puede ser cancelado, ya se encuentra autorizado o aún no ha sido enviado')

            else:
                invoice.edi_state = 'to_send'

            # == Chatter ==
            invoice.with_context(no_new_invoice=True).message_post(
                body=_("The SRI document has been successfully cancelled."),
                subtype_xmlid='account.mt_invoice_validated',
            )

        edi_result = super().button_cancel_posted_moves()
        return edi_result

    def l10n_ec_edi_update_sat_status(self, cron_mode=False):
        '''Authorization both systems: Odoo & SAT to make sure the invoice is valid.
        '''

        edi_result = {}

        _logger.warning(423)
        for move in self:
            _logger.warning(425)
            _logger.warning(move)

            env_name = move.company_id.l10n_ec_edi_pac
            _logger.warning(env_name)

            credentials = move._l10n_ec_edi_get_edi_credentials(env_name)
            _logger.info(975),
            _logger.info(move.move_type)

            if move.move_type in ('out_invoice', 'out_refund'):
                if env_name != 'demo':
                    _logger.info("intentando autorizar " + move.l10n_ec_edi_sri_uuid)
                    res = move._l10n_ec_edi_sri_authorization(credentials, move.l10n_ec_edi_sri_uuid)
                    if res.get('errors'):
                        edi_result = {
                            'error': move._l10n_ec_edi_format_error_message(
                                _("SRI failed to authorization the electronic document:"), res['errors'])
                            #'attachment': self._create_invoice_sri_attachment(invoice, base64.encodebytes(sri_str)),
                        }
                        if cron_mode == False:
                            raise ValidationError(_('%s ') % edi_result['error'])
                        else:
                            _logger.error(edi_result['error'])
                        continue
                    status = res.get('status')
                else:
                    status = 'OK'

                _logger.warning(status)
                if status == 'OK':
                    move.l10n_ec_edi_sat_status = 'valid'

                    self.env.cr.execute(
                        'UPDATE account_move SET l10n_ec_edi_sat_status = \'valid\' WHERE id=%s',
                        (move.id,)
                    )

                    sri_attachment_pdf = move._create_sri_attachment_pdf(move)
                    move.with_context(no_new_invoice=True).message_post(
                        body=_("El documento electrónico fue autorizado con éxito por el SRI."),
                        attachment_ids=sri_attachment_pdf.ids
                    )
                    move.invoice_validate_send_email()
                elif status == 'Cancelado':
                    move.l10n_ec_edi_sat_status = 'cancelled'
                elif status == 'No Encontrado':
                    move.l10n_ec_edi_sat_status = 'not_found'
                elif status == 'No definido':
                    move.l10n_ec_edi_sat_status = 'undefined'
                else:
                    move.l10n_ec_edi_sat_status = 'none'

    @api.model
    def ir_cron_send_invoice(self):
        # Update the 'l10n_ec_edi_sat_status' field.
        sri_edi_format = self.env.ref('l10n_ec_edi.edi_sri_ec')
        to_process = self.env['account.edi.document'].search([
            ('edi_format_id', '=', sri_edi_format.id),
            ('state', 'in', ('sent')),
            ('move_id.l10n_ec_edi_sat_status', 'in', ('undefined', 'not_found', 'none')),
        ])
        to_process.move_id.l10n_ec_edi_update_sat_status(self, True)

    @api.model
    def _l10n_ec_edi_cron_update_sat_status(self):
        ''' Call the SAT to know if the invoice is available government-side or if the invoice has been cancelled.
        In the second case, the cancellation could be done Odoo-side and then we need to check if the SAT is up-to-date,
        or could be done manually government-side forcing Odoo to update the invoice's state.
        '''

        # Update the 'l10n_ec_edi_sat_status' field.
        sri_edi_format = self.env.ref('l10n_ec_edi.edi_sri_ec')
        to_process = self.env['account.edi.document'].search([
            ('edi_format_id', '=', sri_edi_format.id),
            ('move_id.edi_state', 'in', ['sent']),
            ('move_id.l10n_ec_edi_sat_status', 'not in', ['valid'])
        ], limit=5)
        '''
        to_process = self.env['account.edi.document'].search([
            ('edi_format_id', '=', sri_edi_format.id),
            ('state', 'in', ['sent']),
            ('move_id.l10n_ec_edi_sat_status', 'not in', ['valid'])
        ])
        '''
        to_process.move_id.l10n_ec_edi_update_sat_status(True)

        # Handle the case when the invoice has been cancelled manually government-side.
        to_process\
            .filtered(lambda doc: doc.state == 'sent' and doc.move_id.l10n_ec_edi_sat_status == 'cancelled')\
            .move_id\
            .button_cancel()

    # -------------------------------------------------------------------------
    # BUSINESS METHODS
    # -------------------------------------------------------------------------

    def _update_payments_edi_documents(self):
        # OVERRIDE
        # Set the sri origin with code '04' meaning the payment becomes an update of its previous state.
        for payment in self:
            if payment.l10n_ec_edi_sri_uuid:
                payment.l10n_ec_edi_origin = payment._l10n_ec_edi_write_sri_origin('04', [payment.l10n_ec_edi_sri_uuid])
        return super()._update_payments_edi_documents()

    def _post(self, soft=True):
        # OVERRIDE
        certificate_date = self.env['l10n_ec_edi.certificate'].sudo().get_mx_current_datetime()

        self._compute_amount_taxes()

        for move in self:

            issued_address = move._get_l10n_ec_edi_issued_address()
            tz = self._l10n_ec_edi_get_sri_partner_timezone(issued_address)
            tz_force = self.env['ir.config_parameter'].sudo().get_param('l10n_ec_edi_tz_%s' % move.journal_id.id, default=None)
            if tz_force:
                tz = timezone(tz_force)

            move.l10n_ec_edi_post_time = fields.Datetime.to_string(datetime.now(tz))

            if move.l10n_ec_edi_sri_request in ('on_invoice', 'on_refund'):

                # ==== Invoice + Refund ====
                # Line having a negative amount is not allowed.
                for line in move.invoice_line_ids:
                    if line.price_subtotal < 0:
                        raise UserError(_("Invoice lines having a negative amount are not allowed to generate the SRI. "
                                          "Please create a credit note instead."))

               # Assign time and date coming from a certificate.
                if not move.invoice_date:
                    move.invoice_date = certificate_date.date()
                    move.with_context(check_move_validity=False)._onchange_invoice_date()

        return super()._post(soft=soft)

    def button_draft(self):
        # OVERRIDE
        res = super().button_draft()

        '''
        for move in self:
            if move.l10n_ec_edi_sri_uuid:
                move.l10n_ec_edi_origin = move._l10n_ec_edi_write_sri_origin('04', [move.l10n_ec_edi_sri_uuid])
            if move.payment_id:
                move.payment_id.l10n_ec_edi_force_generate_sri = False
            elif move.statement_line_id:
                move.statement_line_id.l10n_ec_edi_force_generate_sri = False
                '''

        return res

    def _reverse_moves(self, default_values_list, cancel=False):
        # OVERRIDE
        # The '01' code is used to indicate the document is a credit note.

        '''for default_vals, move in zip(default_values_list, self):
            if move.l10n_ec_edi_sri_uuid:
                default_vals['l10n_ec_edi_origin'] = move._l10n_ec_edi_write_sri_origin('01', [move.l10n_ec_edi_sri_uuid])
                '''
        return super()._reverse_moves(default_values_list, cancel=cancel)

    def _get_name_invoice_report(self):
        self.ensure_one()
        if self.l10n_latam_use_documents and self.company_id.country_id.code == 'EC':
            return 'l10n_ec_edi.report_invoice_document'
        return super()._get_name_invoice_report()

    def _post(self, soft=True):

        result = super()._post(soft)
        _logger.warning(19)
        try:
            if self.move_type:
                if self.move_type in ['out_invoice', 'out_refund'] and not self.l10n_ec_edi_sri_uuid:
                    self.l10n_ec_edi_sri_uuid = self.get_access_key()
                    _logger.warning(self.l10n_ec_edi_sri_uuid)
        except Exception:
            _logger.exception("tools.email_send failed to deliver email")

        return result

    def get_access_key(self):
        _logger.warning(26)
        for move in self:
            if not self.l10n_ec_edi_sri_uuid:
                printer_point = move.printer_point.printer_point
                environment = '2' if move.company_id.l10n_ec_edi_pac == 'produccion' else '1'
                numerico = random.randint(100000, 99999999)
                tipo_emision = '1'
                access_key = move.invoice_date.strftime('%d%m%Y') + move.l10n_latam_document_type_id.code.zfill(2) + \
                             move.company_id.vat + environment + (printer_point + '').replace('-', '') + \
                             str(move.sequence_number).zfill(9) + str(numerico).zfill(8) + tipo_emision

                _logger.warning(access_key[::-1])

                digito_validador = self._get_digito_validador(access_key[::-1])
                _logger.warning(access_key[::-1])
                access_key += str(digito_validador)
                return access_key
            else:
                return self.l10n_ec_edi_sri_uuid

    def _get_data_out_refund(self):
        invoice = self
        data = {}
        if invoice.move_type == 'out_refund':
            if 'REEMBOLSO' in invoice.ref:
                invoice_ref = invoice.ref.replace('REEMBOLSO', '')
                reason = 'Cambio de factura'
                invoice_origin = self.env['account.move'].search([
                    ('invoice_origin', '=', invoice_ref)], limit=1)
            elif 'Reversa de: ' in invoice.ref:
                invoice_ref = invoice.ref.replace('Reversa de: ', '')
                reason = invoice_ref[invoice_ref.find(','):]
                invoice_ref = invoice_ref.replace(reason, '')
                reason = reason[2:]
                invoice_origin = self.env['account.move'].search([
                    ('name', '=', invoice_ref)], limit=1)
            else:
                invoice_ref = invoice.ref
                raise ValueError('N/C sin comprobante de referencia')

            data = {
                'move': invoice_origin,
                'move_name': invoice_origin.name[invoice_origin.name.find(' ')+1:],
                'move_date': invoice_origin.invoice_date.strftime('%d/%m/%Y'),
                'reason': reason
            }

        return data

    def _get_digito_validador(self, cadena):
        pivote = 2
        cantidadTotal = 0
        b = 1
        for element in cadena:
            if pivote == 8:
                pivote = 2
            temporal = int(element)
            b += 1
            temporal *= pivote
            pivote += 1
            cantidadTotal += temporal
        cantidadTotal = 11 - cantidadTotal % 11
        if cantidadTotal == 11:
            cantidadTotal = 0
        if cantidadTotal == 10:
            cantidadTotal = 1
        return cantidadTotal

    def invoice_validate_send_email(self):
        if self.env.su:
            # sending mail in sudo was meant for it being sent from superuser
            self = self.with_user(SUPERUSER_ID)
        for invoice in self.filtered(lambda x: x.move_type == 'out_invoice'):
            # send template only on customer invoice
            # subscribe the partner to the invoice
            _logger.warning('invoice_validate_send_email')
            _logger.warning(invoice.partner_id.id)
            if invoice.company_id.l10n_ec_edi_mail_template_id:
                _logger.warning('invoice_validate_send_email send 2222')
                invoice.message_subscribe([invoice.partner_id.id])
                invoice.message_post_with_template(
                    invoice.company_id.l10n_ec_edi_mail_template_id.id,
                    composition_mode="mass_mail",
                    email_layout_xmlid="mail.message_notification_email"
                )
        return True