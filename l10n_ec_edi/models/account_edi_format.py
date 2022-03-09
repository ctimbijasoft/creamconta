# -*- coding: utf-8 -*-
from odoo import api, models, fields, tools, _
from odoo.tools.xml_utils import _check_with_xsd

import logging
import re
import base64
import json
import requests
import random
import string

from lxml import etree
from lxml.objectify import fromstring
from datetime import datetime
from io import BytesIO
from zeep import Client, Settings
from zeep.transports import Transport
from json.decoder import JSONDecodeError
from pprint import pprint

_logger = logging.getLogger(__name__)


class AccountEdiFormat(models.Model):
    _inherit = 'account.edi.format'

    # -------------------------------------------------------------------------
    # SRI: Helpers
    # -------------------------------------------------------------------------

    @api.model
    def _l10n_ec_edi_get_serie_and_folio(self, move):
        _logger.warning(36)
        _logger.warning(move.name)
        _logger.warning(move.printer_point)
        _logger.warning(move.printer_point.printer_point)
        _logger.warning(move.printer_point.id)
        if not move.printer_point.printer_point:
            _logger.warning("cambiando printer point")
            printer_point_id = self.env['account.printer.point'].search([
                ('id', '=', int(move.printer_point.id))
            ])
            _logger.warning(printer_point_id)
            _logger.warning(printer_point_id.printer_point)
            _logger.warning(printer_point_id.printer_point_address)
            move.printer_point = printer_point_id
            _logger.warning(move.printer_point.printer_point_address)
        if move.printer_point.printer_point:
            printer_point = move.printer_point.printer_point.split('-')
            establecimiento = printer_point[0]
            punto_emision = printer_point[1]
        else:
            try:
                printer_point = move.name.split(' ')[1].split('-')
                _logger.warning(move.printer_point)
                establecimiento = printer_point[0]
                punto_emision = printer_point[1]
            except Exception as e:
                _logger.error(e)
                establecimiento = ''
                punto_emision = ''
        return {
            'sri_estab': establecimiento,
            'sri_ptoemi': punto_emision,
        }

    '''@api.model
    def _l10n_ec_edi_sri_append_addenda(self, move, sri, addenda):
        
        addenda_values = {'record': move, 'sri': sri}

        addenda = addenda._render(values=addenda_values).strip()
        if not addenda:
            return sri

        sri_node = fromstring(sri)
        addenda_node = fromstring(addenda)

        # Add a root node Addenda if not specified explicitly by the user.
        if addenda_node.tag != '{http://www.sat.gob.mx/cfd/3}Addenda':
            node = etree.Element(etree.QName('http://www.sat.gob.mx/cfd/3', 'Addenda'))
            node.append(addenda_node)
            addenda_node = node

        sri_node.append(addenda_node)
        return etree.tostring(sri_node, pretty_print=True, xml_declaration=True, encoding='UTF-8')'''

    @api.model
    def _l10n_ec_edi_check_configuration(self, move):
        company = move.company_id
        env_name = company.l10n_ec_edi_pac

        errors = []

        _logger.warning(company)
        _logger.warning(company.sudo().l10n_ec_edi_certificate_ids)

        # == Check the certificate ==
        certificate = company.l10n_ec_edi_certificate_ids.sudo().get_valid_certificate()

        _logger.warning(certificate)
        if not certificate:
            errors.append(_('No valid certificate found'))

        # == Check the credentials to call the PAC web-service ==
        '''if env_name:
            pac_test_env = company.l10n_ec_edi_pac_test_env
            pac_password = company.l10n_ec_edi_pac_password
            if not pac_test_env and not pac_password:
                errors.append(_('No PAC credentials specified.'))
        else:
            errors.append(_('No PAC specified.'))'''

        # == Check the 'l10n_ec_edi_decimal_places' field set on the currency  ==
        currency_precision = move.currency_id.l10n_ec_edi_decimal_places
        if currency_precision is False:
            errors.append(_(
                "The SAT does not provide information for the currency %s.\n"
                "You must get manually a key from the PAC to confirm the "
                "currency rate is accurate enough.") % move.currency_id)

        return errors

    @api.model
    def _l10n_ec_edi_format_error_message(self, error_title, errors):
        bullet_list_msg = ''.join('<li>%s</li>' % msg for msg in errors)
        return '%s<ul>%s</ul>' % (error_title, bullet_list_msg)

    # -------------------------------------------------------------------------
    # SRI Generation: Generic
    # ----------------------------------------

    def _l10n_ec_edi_get_common_sri_values(self, move):
        ''' Generic values to generate a sri for a journal entry.
        :param move:    The account.move record to which generate the SRI.
        :return:        A python dictionary.
        '''

        def _format_string_sri(text, size=100):
            """Replace from text received the characters that are not found in the
            regex. This regex is taken from SAT documentation
            https://goo.gl/C9sKH6
            text: Text to remove extra characters
            size: Cut the string in size len
            Ex. 'Product ABC (small size)' - 'Product ABC small size'"""
            if not text:
                return None
            text = text.replace('|', ' ')
            return text.strip()[:size]

        def _get_digito_validador(cadena):
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

        def _format_float_sri(amount, precision):
            if amount is None or amount is False:
                return None
            return '%.*f' % (precision, amount)

        company = move.company_id
        environment = '2' if move.company_id.l10n_ec_edi_pac == 'produccion' else '1'
        certificate = company.l10n_ec_edi_certificate_ids.sudo().get_valid_certificate()
        currency_precision = move.currency_id.l10n_ec_edi_decimal_places

        customer = move.partner_id if move.partner_id.type == 'invoice' else move.partner_id.commercial_partner_id
        supplier = move.company_id.partner_id.commercial_partner_id

        numerico = random.randint(100000, 99999999)
        tipo_emision = '1'

        supplier_address = supplier.street_name + (' ' + supplier.street_number) if supplier.street_number else '' + \
                                                                                                                (
                                                                                                                            ' y ' + supplier.street2) if supplier.street2 else ''

        _logger.warning(147)
        _logger.warning(move.printer_point.printer_point)

        if not move.l10n_ec_edi_sri_uuid:
            _logger.warning(173)
            _logger.warning("Generando nuevo access key")
            _logger.info(move.sequence_number)
            _logger.info(numerico)
            _logger.info(tipo_emision)
            _logger.info(move.l10n_latam_document_type_id)
            _logger.info(move.l10n_latam_document_type_id.code)
            _logger.info(move.invoice_date.strftime('%d%m%Y'))
            _logger.info(move.l10n_latam_document_type_id.code.zfill(2))
            _logger.info(supplier.vat)
            _logger.info(environment)
            _logger.info(str(move.sequence_number).zfill(9))
            _logger.info(str(numerico).zfill(8))

            if move.printer_point.printer_point == False:
                printer_point = '001-001'
            else:
                printer_point = move.printer_point.printer_point
            _logger.info(printer_point)
            access_key = move.invoice_date.strftime('%d%m%Y') + move.l10n_latam_document_type_id.code.zfill(2) + \
                         supplier.vat + environment + (printer_point + '').replace('-', '') + \
                         str(move.sequence_number).zfill(9) + str(numerico).zfill(8) + tipo_emision

            digito_validador = _get_digito_validador(access_key[::-1])
            access_key += str(digito_validador)
        else:
            _logger.warning(188)
            _logger.warning("Modificando Documento SRI")
            access_key = move.l10n_ec_edi_sri_uuid

        if not customer:
            customer_rfc = False
        elif customer.country_id and customer.country_id.code != 'EC':
            customer_rfc = 'XEXX010101000'
        elif customer.vat:
            customer_rfc = customer.vat.strip()
        elif customer.country_id.code in (False, 'EC'):
            customer_rfc = 'XAXX010101000'
        else:
            customer_rfc = 'XEXX010101000'

        '''if move.l10n_ec_edi_origin:
            origin_type, origin_uuids = move._l10n_ec_edi_read_sri_origin(move.l10n_ec_edi_origin)
        else:
            origin_type = None
            origin_uuids = []'''

        return {
            **self._l10n_ec_edi_get_serie_and_folio(move),
            'certificate': certificate,
            'environment': environment,
            'access_key': access_key,
            # 'certificate_number': certificate.serial_number,
            # 'certificate_key': 'none',#certificate.sudo().get_data()[0],
            'record': move,
            'sri_date': '',  # move.l10n_ec_edi_post_time.strftime('%Y-%m-%dT%H:%M:%S'),
            'supplier': supplier,
            'customer': customer,
            'payment_method': move.sri_payment_method.payment_method_code,
            # 'customer_rfc': customer_rfc,
            'supplier_address': supplier_address,
            'currency_precision': currency_precision,
            # 'origin_type': origin_type,
            # 'origin_uuids': origin_uuids,
            'format_string': _format_string_sri,
            'format_float': _format_float_sri,
        }

    # -------------------------------------------------------------------------
    # SRI Generation: Invoices
    # -------------------------------------------------------------------------

    def _l10n_ec_edi_get_invoice_line_sri_values(self, invoice, line):
        sri_values = {'line': line}

        # ==== Amounts ====

        sri_values['price_unit_wo_discount'] = line.price_unit * (1 - (line.discount / 100.0))
        sri_values['total_wo_discount'] = invoice.currency_id.round(line.price_unit * line.quantity)
        sri_values['discount_amount'] = invoice.currency_id.round(sri_values['total_wo_discount'] - line.price_subtotal)
        sri_values['subtotal_with_discount'] = invoice.currency_id.round(sri_values['total_wo_discount'] - sri_values['discount_amount'])

        try:
            sri_values['price_subtotal_unit'] = invoice.currency_id.round(sri_values['total_wo_discount'] / line.quantity)
        except Exception as e:
            sri_values['price_subtotal_unit'] = 0

        # ==== Taxes ====

        tax_details = line.tax_ids.compute_all(
            sri_values['price_unit_wo_discount'],
            currency=line.currency_id,
            quantity=line.quantity,
            product=line.product_id,
            partner=line.partner_id,
            is_refund=invoice.move_type in ('out_refund', 'in_refund'),
        )

        print(tax_details)

        sri_values['tax_details'] = {}
        for tax_res in tax_details['taxes']:
            tax = self.env['account.tax'].browse(tax_res['id'])

            ##ctif tax.l10n_ec_tax_type == 'Exento':
            ##ct    continue

            # tax_rep_field = 'invoice_repartition_line_ids' if invoice.move_type == 'out_invoice' else 'refund_repartition_line_ids'
            # tags = tax[tax_rep_field].tag_ids
            # tax_name = {'ISR': '001', 'IVA': '002', 'IEPS': '003'}.get(tags.name) if len(tags) == 1 else None

            percent_id = '0'
            if tax.amount > 0:
                if tax.amount == 8.00:
                    percent_id = '8'
                else:
                    percent_id = '2'

            print(313313)
            print(percent_id)

            if percent_id == '2':
                print(2121212)
                percent_id = self._l10n_ec_get_percent_id(invoice.date)
                print(percent_id)

            amount = tax.amount
            if percent_id == '8':
                amount = 8.00

            sri_values['tax_details'].setdefault(tax, {
                'tax': tax,
                'base': round(tax_res['base'], 2),
                'tax_type': '2',  # IVA
                'tax_amount': amount,
                'percent_id': percent_id,
                'total': 0.0,
            })

            sri_values['tax_details'][tax]['total'] += tax_res['amount']
            _logger.warning(sri_values['tax_details'])

        sri_values['tax_details'] = list(sri_values['tax_details'].values())
        sri_values['tax_details_transferred'] = [tax_res for tax_res in sri_values['tax_details'] if
                                                 tax_res['tax_amount'] >= 0.0]
        sri_values['tax_details_withholding'] = [tax_res for tax_res in sri_values['tax_details'] if
                                                 tax_res['tax_amount'] < 0.0]

        return sri_values

    def _l10n_ec_get_percent_id(self, date):
        d1 = datetime(2022, 2, 26)
        d2 = datetime(2022, 3, 1)
        if d1.date() <= date <= d2.date():
            return '8'
        return '2'

    def _l10n_ec_edi_get_invoice_sri_values(self, invoice):
        ''' Doesn't check if the config is correct so you need to call _l10n_ec_edi_check_config first.

        :param invoice:
        :return:
        '''

        sri_values = {
            **self._l10n_ec_edi_get_common_sri_values(invoice),
            'document_type': 'I' if invoice.move_type == 'out_invoice' else 'E',
            'currency_name': invoice.currency_id.name,
            'payment_method_code': '',  # (invoice.l10n_ec_edi_payment_method_id.code or '').replace('NA', '99'),
            'payment_policy': ''  # invoice.l10n_ec_edi_payment_policy,
        }

        # ==== Invoice Values ====

        invoice_lines = invoice.invoice_line_ids.filtered(lambda inv: not inv.display_type)

        if invoice.currency_id == invoice.company_currency_id:
            sri_values['currency_conversion_rate'] = None
        else:
            sign = 1 if invoice.move_type in ('out_invoice', 'out_receipt', 'in_refund') else -1
            total_amount_currency = sign * invoice.amount_total
            total_balance = invoice.amount_total_signed
            sri_values['currency_conversion_rate'] = total_balance / total_amount_currency

        if invoice.partner_bank_id:
            digits = [s for s in invoice.partner_bank_id.acc_number if s.isdigit()]
            acc_4number = ''.join(digits)[-4:]
            sri_values['account_4num'] = acc_4number if len(acc_4number) == 4 else None
        else:
            sri_values['account_4num'] = None

        '''if sri_values['customer'].country_id.l10n_ec_edi_code != 'MEX' and sri_values['customer_rfc'] not in ('XEXX010101000', 'XAXX010101000'):
            sri_values['customer_fiscal_residence'] = sri_values['customer'].country_id.l10n_ec_edi_code
        else:
            sri_values['customer_fiscal_residence'] = None'''

        # ==== Invoice lines ====

        sri_values['invoice_line_values'] = []
        for line in invoice_lines:
            sri_values['invoice_line_values'].append(self._l10n_ec_edi_get_invoice_line_sri_values(invoice, line))

        # ==== Totals ====

        sri_values['total_amount_base_iva_12'] = 0.0
        sri_values['total_amount_base_iva_0'] = 0.0
        sri_values['tax_amount'] = {}
        sri_values['tax_amount'].setdefault('base12', {
            'tax_type': '2',  # IVA
            'percent_id': self._l10n_ec_get_percent_id(invoice.date),
            'total_base': 0.0,
            'total_value': 0.0
        })
        sri_values['tax_amount'].setdefault('base0', {
            'tax_type': '2',  # IVA
            'percent_id': '0',
            'total_base': 0.0,
            'total_value': 0.0
        })
        for line in sri_values['invoice_line_values']:
            for taxs in line['tax_details']:
                if taxs['percent_id'] == '0':
                    sri_values['tax_amount']['base0']['total_base'] += taxs['base']
                    sri_values['tax_amount']['base0']['total_value'] += taxs['total']
                else:
                    sri_values['tax_amount']['base12']['total_base'] += taxs['base']
                    sri_values['tax_amount']['base12']['total_value'] += taxs['total']

        _logger.warning(329)
        _logger.warning(sri_values['tax_amount'])

        sri_values['tax_amount']['base0']['total_value'] = round(sri_values['tax_amount']['base0']['total_value'], 2)
        sri_values['tax_amount']['base0']['total_base'] = round(sri_values['tax_amount']['base0']['total_base'], 2)
        sri_values['tax_amount']['base12']['total_base'] = round(sri_values['tax_amount']['base12']['total_base'], 2)
        sri_values['tax_amount']['base12']['total_value'] = round(sri_values['tax_amount']['base12']['total_value'], 2)

        sri_values['total_amount_untaxed_wo_discount'] = sum(
            vals['total_wo_discount'] for vals in sri_values['invoice_line_values'])
        sri_values['total_amount_untaxed_discount'] = sum(
            vals['discount_amount'] for vals in sri_values['invoice_line_values'])

        sri_values['total_with_discount'] = invoice.currency_id.round(sri_values['total_amount_untaxed_wo_discount'] - sri_values['total_amount_untaxed_discount'])

        # ==== Taxes ====

        sri_values['tax_details_transferred'] = {}
        sri_values['tax_details_withholding'] = {}
        for vals in sri_values['invoice_line_values']:
            for tax_res in vals['tax_details_transferred']:
                sri_values['tax_details_transferred'].setdefault(tax_res['tax'], {
                    'tax': tax_res['tax'],
                    # 'tax_type': tax_res['tax_type'],
                    'tax_amount': tax_res['tax_amount'],
                    # 'tax_name': tax_res['tax_name'],
                    'total': 0.0,
                })
                sri_values['tax_details_transferred'][tax_res['tax']]['total'] += tax_res['total']
            for tax_res in vals['tax_details_withholding']:
                sri_values['tax_details_withholding'].setdefault(tax_res['tax'], {
                    'tax': tax_res['tax'],
                    'tax_type': tax_res['tax_type'],
                    'tax_amount': tax_res['tax_amount'],
                    # 'tax_name': tax_res['tax_name'],
                    'total': 0.0,
                })
                sri_values['tax_details_withholding'][tax_res['tax']]['total'] += tax_res['total']

        sri_values['tax_details_transferred'] = list(sri_values['tax_details_transferred'].values())
        sri_values['tax_details_withholding'] = list(sri_values['tax_details_withholding'].values())
        sri_values['total_tax_details_transferred'] = sum(
            vals['total'] for vals in sri_values['tax_details_transferred'])
        sri_values['total_tax_details_withholding'] = sum(
            vals['total'] for vals in sri_values['tax_details_withholding'])

        print(441)
        print(sri_values)
        return sri_values

    def _l10n_ec_edi_export_invoice_sri(self, invoice):
        ''' Create the SRI attachment for the invoice passed as parameter.

        :param move:    An account.move record.
        :return:        A dictionary with one of the following key:
        * sri_str:     A string of the unsigned sri of the invoice.
        * error:        An error if the sri was not successfuly generated.
        '''

        # == SRI values ==
        _logger.warning('321')
        sri_values = self._l10n_ec_edi_get_invoice_sri_values(invoice)

        # == Generate the SRI ==
        # sri = self.env.ref('l10n_ec_edi.sriv33')._render(sri_values)
        if invoice.move_type == 'out_invoice':
            sri = self.env.ref('l10n_ec_edi.srifacv110v2')._render(sri_values)
        elif invoice.move_type == 'out_refund':
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

            print(invoice_ref)
            print(reason)
            print(invoice_origin)

            sri_values['invoice_origin'] = invoice_origin
            sri_values['out_refund_reason'] = reason

            sri = self.env.ref('l10n_ec_edi.sri_nc_v110v2')._render(sri_values)




        print(sri)


        # decoded_sri_values = invoice._l10n_ec_edi_decode_sri(sri_data=sri)

        # sri_cadena_crypted = sri_values['certificate'].sudo().get_encrypted_cadena(decoded_sri_values['cadena'])
        if invoice.company_id.l10n_ec_edi_pac != 'demo':
            sri_cadena_crypted = sri_values['certificate'].sudo().get_encrypted_cadena(sri,
                                                                                       sri_values['access_key'])
        else:
            sri_cadena_crypted = sri

        # decoded_sri_values['sri_node'].attrib['Sello'] = sri_cadena_crypted

        # == Optional check using the XSD ==
        # xsd_attachment = self.env.ref('l10n_ec_edi.xsd_cached_cfdv33_xsd', False)
        # xsd_datas = base64.b64decode(xsd_attachment.datas) if xsd_attachment else None

        '''if xsd_datas:
            try:
                with BytesIO(xsd_datas) as xsd:
                    _check_with_xsd(decoded_sri_values['sri_node'], xsd)
            except (IOError, ValueError):
                _logger.info(_('The xsd file to validate the XML structure was not found'))
            except Exception as e:
                return {'errors': str(e).split('\\n')}'''

        #invoice.l10n_ec_edi_sri_uuid = sri_values['access_key']

        return {
            # 'sri_str': etree.tostring(decoded_sri_values['sri_node'], pretty_print=True, xml_declaration=True, encoding='UTF-8'),
            'sri_str': sri_cadena_crypted,
            'sri_uuid': sri_values['access_key']
        }

    # -------------------------------------------------------------------------
    # SRI Generation: Payments
    # -------------------------------------------------------------------------

    #def _l10n_ec_edi_export_payment_sri(self, move): '''
        ''' Create the SRI attachment for the journal entry passed as parameter being a payment used to pay some
        invoices.

        :param move:    An account.move record.
        :return:        A dictionary with one of the following key:
        * sri_str:     A string of the unsigned sri of the invoice.
        * error:        An error if the sri was not successfuly generated.
       
    
        invoice_vals_list = []
        for partial, amount, invoice_line in move._get_reconciled_invoices_partials():
            invoice = invoice_line.move_id

            if not invoice.l10n_ec_edi_sri_request:
                continue

            invoice_vals_list.append({
                'invoice': invoice,
                'exchange_rate': invoice.amount_total / abs(invoice.amount_total_signed),
                'payment_policy': invoice.l10n_ec_edi_payment_policy,
                'number_of_payments': len(invoice._get_reconciled_payments()) + len(
                    invoice._get_reconciled_statement_lines()),
                'amount_paid': amount,
                **self._l10n_ec_edi_get_serie_and_folio(invoice),
            })

        mxn_currency = self.env["res.currency"].search([('name', '=', 'USD')], limit=1)
        if move.currency_id == mxn_currency:
            rate_payment_curr_mxn = None
        else:
            rate_payment_curr_mxn = move.currency_id._convert(1.0, mxn_currency, move.company_id, move.date,
                                                              round=False)

        payment_method_code = move.l10n_ec_edi_payment_method_id.code
        is_payment_code_emitter_ok = payment_method_code in ('02', '03', '04', '05', '06', '28', '29', '99')
        is_payment_code_receiver_ok = payment_method_code in ('02', '03', '04', '05', '28', '29', '99')
        is_payment_code_bank_ok = payment_method_code in ('02', '03', '04', '28', '29', '99')

        partner_bank = move.partner_bank_id.bank_id
        if partner_bank.country and partner_bank.country.code != 'EC':
            partner_bank_vat = 'XEXX010101000'
        else:  # if no partner_bank (e.g. cash payment), partner_bank_vat is not set.
            partner_bank_vat = partner_bank.l10n_ec_edi_vat

        payment_account_ord = re.sub(r'\s+', '', move.partner_bank_id.acc_number or '') or None
        payment_account_receiver = re.sub(r'\s+', '', move.journal_id.bank_account_id.acc_number or '') or None

        receivable_lines = move.line_ids.filtered(lambda line: line.account_internal_type == 'receivable')
        currencies = receivable_lines.mapped('currency_id')
        amount = abs(sum(receivable_lines.mapped('amount_currency')) if len(currencies) == 1 else sum(
            receivable_lines.mapped('balance')))

        sri_values = {
            **self._l10n_ec_edi_get_common_sri_values(move),
            'invoice_vals_list': invoice_vals_list,
            'currency': currencies[0] if len(currencies) == 1 else move.currency_id,
            'amount': amount,
            'rate_payment_curr_mxn': rate_payment_curr_mxn,
            'emitter_vat_ord': is_payment_code_emitter_ok and partner_bank_vat,
            'bank_vat_ord': is_payment_code_bank_ok and partner_bank.name,
            'payment_account_ord': is_payment_code_emitter_ok and payment_account_ord,
            'receiver_vat_ord': is_payment_code_receiver_ok and move.journal_id.bank_account_id.bank_id.l10n_ec_edi_vat,
            'payment_account_receiver': is_payment_code_receiver_ok and payment_account_receiver,
        }

        sri_payment_datetime = datetime.combine(fields.Datetime.from_string(move.date),
                                                datetime.strptime('12:00:00', '%H:%M:%S').time())
        sri_values['sri_payment_date'] = sri_payment_datetime.strftime('%Y-%m-%dT%H:%M:%S')

        if sri_values['customer'].country_id.l10n_ec_edi_code != 'MEX':
            sri_values['customer_fiscal_residence'] = sri_values['customer'].country_id.l10n_ec_edi_code
        else:
            sri_values['customer_fiscal_residence'] = None

        sri = self.env.ref('l10n_ec_edi.payment10')._render(sri_values)

        _logger.info('_l10n_ec_edi_export_payment_sri')
        decoded_sri_values = move._l10n_ec_edi_decode_sri(sri_data=sri)
        sri_cadena_crypted = sri_values['certificate'].sudo().get_encrypted_cadena(decoded_sri_values['cadena'])
        decoded_sri_values['sri_node'].attrib['Sello'] = sri_cadena_crypted

        return {
            'sri_str': etree.tostring(decoded_sri_values['sri_node'], pretty_print=True, xml_declaration=True,
                                      encoding='UTF-8'),
        }
    '''

    # -------------------------------------------------------------------------
    # SRI: PACs
    # -------------------------------------------------------------------------

    def _l10n_ec_edi_get_edi_credentials(self, move):
        edi_pac = move.company_id.l10n_ec_edi_pac
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

    def _l10n_ec_edi_sri_reception(self, move, credentials, document):
        # credentials.reception_url = 'https://celcer.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline?wsdl'
        #_logger.warning(credentials['reception_url'])
        #_logger.warning(document)
        try:
            transport = Transport(timeout=60)
            client = Client(credentials['reception_url'], transport=transport)
            response = client.service.validarComprobante(document)
        except Exception as e:
            _logger.error(624)
            _logger.error(e)
            return {
                'errors': [_("The SRI service failed to validate with the following error: %s", str(e))],
            }

        _logger.warning(response)
        if response.estado != 'RECIBIDA':
            errors = []

            for comprobante in response['comprobantes'].comprobante:
                errors.append(_("Clave de acceso : %s") % comprobante.claveAcceso)
                for mensaje in comprobante['mensajes'].mensaje:
                    if mensaje.informacionAdicional == None:
                        errors.append(_("Error : %s") % mensaje.mensaje)
                    else:
                        errors.append(_("Error : %s") % mensaje.informacionAdicional)

            _logger.warning(len([x for x in errors if 'CLAVE ACCESO REGISTRADA' in x]))
            if len([x for x in errors if 'CLAVE ACCESO REGISTRADA' in x]) == 0:
                return {'errors': errors}

            '''code = getattr(response.Incidencias.Incidencia[0], 'CodigoError', None)
            msg = getattr(response.Incidencias.Incidencia[0], 'MensajeIncidencia', None)
            errors = []
            if code:
                errors.append(_("Code : %s") % code)
            if msg:
                errors.append(_("Message : %s") % msg)
            return {'errors': errors}'''
        '''sri_signed = getattr(response, 'xml', None)
        if sri_signed:
            sri_signed = sri_signed.encode('utf-8')'''
        return {
            'sri_signed': document,
            'sri_encoding': 'str',
            'sri_uuid': move.l10n_ec_edi_sri_uuid
        }

    '''def _l10n_ec_edi_sritest_sign(self, move, credentials, sri):
        try:
            transport = Transport(timeout=20)
            client = Client(credentials['sign_url'], transport=transport)
            response = client.service.stamp(sri, credentials['username'], credentials['password'])
        except Exception as e:
            return {
                'errors': [_("The Finkok service failed to sign with the following error: %s", str(e))],
            }

        if response.Incidencias and not response.xml:
            code = getattr(response.Incidencias.Incidencia[0], 'CodigoError', None)
            msg = getattr(response.Incidencias.Incidencia[0], 'MensajeIncidencia', None)
            errors = []
            if code:
                errors.append(_("Code : %s") % code)
            if msg:
                errors.append(_("Message : %s") % msg)
            return {'errors': errors}

        sri_signed = getattr(response, 'xml', None)
        if sri_signed:
            sri_signed = sri_signed.encode('utf-8')

        return {
            'sri_signed': sri_signed,
            'sri_encoding': 'str',
        }

    def _l10n_ec_edi_sritest_cancel(self, move, credentials, sri):
        uuid = move.l10n_ec_edi_sri_uuid
        certificates = move.company_id.l10n_ec_edi_certificate_ids
        certificate = certificates.sudo().get_valid_certificate()
        company = move.company_id
        cer_pem = certificate.get_pem_cer(certificate.content)
        key_pem = certificate.get_pem_key(certificate.key, certificate.password)
        try:
            transport = Transport(timeout=20)
            client = Client(credentials['cancel_url'], transport=transport)
            uuid_type = client.get_type('ns0:stringArray')()
            uuid_type.string = [uuid]
            invoices_list = client.get_type('ns1:UUIDS')(uuid_type)
            response = client.service.cancel(
                invoices_list,
                credentials['username'],
                credentials['password'],
                company.vat,
                cer_pem,
                key_pem,
            )
        except Exception as e:
            return {
                'errors': [_("The Finkok service failed to cancel with the following error: %s", str(e))],
            }

        if not getattr(response, 'Folios', None):
            code = getattr(response, 'CodEstatus', None)
            msg = _("Cancelling got an error") if code else _('A delay of 2 hours has to be respected before to cancel')
        else:
            code = getattr(response.Folios.Folio[0], 'EstatusUUID', None)
            cancelled = code in ('201', '202')  # cancelled or previously cancelled
            # no show code and response message if cancel was success
            code = '' if cancelled else code
            msg = '' if cancelled else _("Cancelling got an error")

        errors = []
        if code:
            errors.append(_("Code : %s") % code)
        if msg:
            errors.append(_("Message : %s") % msg)
        if errors:
            return {'errors': errors}

        return {'success': True}'''

    def _l10n_ec_edi_sritest_sign_invoice(self, invoice, credentials, sri):
        return self._l10n_ec_edi_sri_reception(invoice, credentials, sri)

    def _l10n_ec_edi_sritest_cancel_invoice(self, invoice, credentials, sri):
        return self._l10n_ec_edi_sritest_cancel(invoice, credentials, sri)

    '''def _l10n_ec_edi_sritest_sign_payment(self, move, credentials, sri):
        return self._l10n_ec_edi_sritest_sign(move, credentials, sri)

    def _l10n_ec_edi_sritest_cancel_payment(self, move, credentials, sri):
        return self._l10n_ec_edi_sritest_cancel(move, credentials, sri)'''

    def _l10n_ec_edi_get_solfact_credentials(self, move):
        if move.company_id.l10n_ec_edi_pac_test_env:
            return {
                'username': 'testing@solucionfactible.com',
                'password': 'timbrado.SF.16672',
                'url': 'https://testing.solucionfactible.com/ws/services/Timbrado?wsdl',
            }
        else:
            if not move.company_id.l10n_ec_edi_pac_username or not move.company_id.l10n_ec_edi_pac_password:
                return {
                    'errors': [_("The username and/or password are missing.")]
                }

            return {
                'username': move.company_id.l10n_ec_edi_pac_username,
                'password': move.company_id.l10n_ec_edi_pac_password,
                'url': 'https://solucionfactible.com/ws/services/Timbrado?wsdl',
            }

    '''def _l10n_ec_edi_solfact_sign(self, move, credentials, sri):
        try:
            transport = Transport(timeout=20)
            client = Client(credentials['url'], transport=transport)
            response = client.service.timbrar(credentials['username'], credentials['password'], sri, False)
        except Exception as e:
            return {
                'errors': [_("The Test SRI service failed to sign with the following error: %s", str(e))],
            }

        if (response.status != 200):
            # ws-timbrado-timbrar - status 200 : SRI correctamente validado y timbrado.
            return {
                'errors': [_("The Test SRI service failed to sign with the following error: %s", response.mensaje)],
            }

        res = response.resultados

        sri_signed = getattr(res[0] if res else response, 'sriTimbrado', None)
        if sri_signed:
            return {
                'sri_signed': sri_signed,
                'sri_encoding': 'str',
            }

        msg = getattr(res[0] if res else response, 'mensaje', None)
        code = getattr(res[0] if res else response, 'status', None)
        errors = []
        if code:
            errors.append(_("Code : %s") % code)
        if msg:
            errors.append(_("Message : %s") % msg)
        return {'errors': errors}

    def _l10n_ec_edi_solfact_cancel(self, move, credentials, sri):
        uuids = [move.l10n_ec_edi_sri_uuid]
        certificates = move.company_id.l10n_ec_edi_certificate_ids
        certificate = certificates.sudo().get_valid_certificate()
        cer_pem = certificate.get_pem_cer(certificate.content)
        key_pem = certificate.get_pem_key(certificate.key, certificate.password)
        key_password = certificate.password

        try:
            transport = Transport(timeout=20)
            client = Client(credentials['url'], transport=transport)
            response = client.service.cancelar(
                credentials['username'], credentials['password'], uuids, cer_pem, key_pem, key_password)
        except Exception as e:
            return {
                'errors': [_("The Test SRI service failed to cancel with the following error: %s", str(e))],
            }

        if (response.status not in (200, 201)):
            # ws-timbrado-cancelar - status 200 : El proceso de cancelación se ha completado correctamente.
            # ws-timbrado-cancelar - status 201 : El folio se ha cancelado con éxito.
            return {
                'errors': [_("The Test SRI service failed to cancel with the following error: %s", response.mensaje)],
            }

        res = response.resultados
        code = getattr(res[0], 'statusUUID', None) if res else getattr(response, 'status', None)
        cancelled = code in ('201', '202')  # cancelled or previously cancelled
        # no show code and response message if cancel was success
        msg = '' if cancelled else getattr(res[0] if res else response, 'mensaje', None)
        code = '' if cancelled else code

        errors = []
        if code:
            errors.append(_("Code : %s") % code)
        if msg:
            errors.append(_("Message : %s") % msg)
        if errors:
            return {'errors': errors}

        return {'success': True}

    def _l10n_ec_edi_solfact_sign_invoice(self, invoice, credentials, sri):
        return self._l10n_ec_edi_solfact_sign(invoice, credentials, sri)

    def _l10n_ec_edi_solfact_cancel_invoice(self, invoice, credentials, sri):
        return self._l10n_ec_edi_solfact_cancel(invoice, credentials, sri)

    def _l10n_ec_edi_solfact_sign_payment(self, move, credentials, sri):
        return self._l10n_ec_edi_solfact_sign(move, credentials, sri)

    def _l10n_ec_edi_solfact_cancel_payment(self, move, credentials, sri):
        return self._l10n_ec_edi_solfact_cancel(move, credentials, sri)

    def _l10n_ec_edi_get_sw_token(self, credentials):
        if credentials['password'] and not credentials['username']:
            # token is configured directly instead of user/password
            return {
                'token': credentials['password'].strip(),
            }

        try:
            headers = {
                'user': credentials['username'],
                'password': credentials['password'],
                'Cache-Control': "no-cache"
            }
            response = requests.post(credentials['login_url'], headers=headers)
            response.raise_for_status()
            response_json = response.json()
            return {
                'token': response_json['data']['token'],
            }
        except (requests.exceptions.RequestException, KeyError, TypeError) as req_e:
            return {
                'errors': [str(req_e)],
            }

    def _l10n_ec_edi_get_sw_credentials(self, move):
        if move.company_id.l10n_ec_edi_pac_test_env:
            credentials = {
                'username': 'demo',
                'password': '123456789',
                'login_url': 'https://services.test.sw.com.mx/security/authenticate',
                'sign_url': 'https://services.test.sw.com.mx/sri33/stamp/v3/b64',
                'cancel_url': 'https://services.test.sw.com.mx/sri33/cancel/csd',
            }
        else:
            if not move.company_id.l10n_ec_edi_pac_username or not move.company_id.l10n_ec_edi_pac_password:
                return {
                    'errors': [_("The username and/or password are missing.")]
                }

            credentials = {
                'username': move.company_id.l10n_ec_edi_pac_username,
                'password': move.company_id.l10n_ec_edi_pac_password,
                'login_url': 'https://services.sw.com.mx/security/authenticate',
                'sign_url': 'https://services.sw.com.mx/sri33/stamp/v3/b64',
                'cancel_url': 'https://services.sw.com.mx/sri33/cancel/csd',
            }

        # Retrieve a valid token.
        credentials.update(self._l10n_ec_edi_get_sw_token(credentials))

        return credentials

    def _l10n_ec_edi_sw_call(self, url, headers, payload=None):
        try:
            response = requests.post(url, data=payload, headers=headers,
                                     verify=True, timeout=20)
        except requests.exceptions.RequestException as req_e:
            return {'status': 'error', 'message': str(req_e)}
        msg = ""
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as res_e:
            msg = str(res_e)
        try:
            response_json = response.json()
        except JSONDecodeError:
            # If it is not possible get json then
            # use response exception message
            return {'status': 'error', 'message': msg}
        if (response_json['status'] == 'error' and
                response_json['message'].startswith('307')):
            # XML signed previously
            sri = base64.encodebytes(
                response_json['messageDetail'].encode('UTF-8'))
            sri = sri.decode('UTF-8')
            response_json['data'] = {'sri': sri}
            # We do not need an error message if XML signed was
            # retrieved then cleaning them
            response_json.update({
                'message': None,
                'messageDetail': None,
                'status': 'success',
            })
        return response_json

    def _l10n_ec_edi_sw_sign(self, move, credentials, sri):
        _logger.warning(sri)
        sri_b64 = base64.encodebytes(sri).decode('UTF-8')
        _logger.warning(sri_b64)
        random_values = [random.choice(string.ascii_letters + string.digits) for n in range(30)]
        boundary = ''.join(random_values)
        payload = """--%(boundary)s
Content-Type: text/xml
Content-Transfer-Encoding: binary
Content-Disposition: form-data; name="xml"; filename="xml"

%(sri_b64)s
--%(boundary)s--
""" % {'boundary': boundary, 'sri_b64': sri_b64}
        payload = payload.replace('\n', '\r\n').encode('UTF-8')

        headers = {
            'Authorization': "bearer " + credentials['token'],
            'Content-Type': ('multipart/form-data; '
                             'boundary="%s"') % boundary,
        }

        response_json = self._l10n_ec_edi_sw_call(credentials['sign_url'], headers, payload=payload)

        try:
            sri_signed = response_json['data']['sri']
        except (KeyError, TypeError):
            sri_signed = None

        if sri_signed:
            return {
                'sri_signed': sri_signed.encode('UTF-8'),
                'sri_encoding': 'base64',
            }
        else:
            code = response_json.get('message')
            msg = response_json.get('messageDetail')
            errors = []
            if code:
                errors.append(_("Code : %s") % code)
            if msg:
                errors.append(_("Message : %s") % msg)
            return {'errors': errors}

    def _l10n_ec_edi_sw_cancel(self, move, credentials, sri):
        headers = {
            'Authorization': "bearer " + credentials['token'],
            'Content-Type': "application/json"
        }
        certificates = move.company_id.l10n_ec_edi_certificate_ids
        certificate = certificates.sudo().get_valid_certificate()

        _logger.info(729)
        _logger.info('_l10n_ec_edi_sw_cancel')
        sri_infos = move._l10n_ec_edi_decode_sri(sri_data=sri)

        payload = json.dumps({
            'rfc': sri_infos['supplier_rfc'],
            'b64Cer': certificate.content.decode('UTF-8'),
            'b64Key': certificate.key.decode('UTF-8'),
            'password': certificate.password,
            'uuid': sri_infos['uuid'],
        })
        response_json = self._l10n_ec_edi_sw_call(credentials['cancel_url'], headers, payload=payload.encode('UTF-8'))

        cancelled = response_json['status'] == 'success'
        if cancelled:
            return {
                'success': cancelled
            }

        code = response_json.get('message')
        msg = response_json.get('messageDetail')
        errors = []
        if code:
            errors.append(_("Code : %s") % code)
        if msg:
            errors.append(_("Message : %s") % msg)
        return {'errors': errors}

    def _l10n_ec_edi_sw_sign_invoice(self, invoice, credentials, sri):
        return self._l10n_ec_edi_sw_sign(invoice, credentials, sri)

    def _l10n_ec_edi_sw_cancel_invoice(self, invoice, credentials, sri):
        return self._l10n_ec_edi_sw_cancel(invoice, credentials, sri)

    def _l10n_ec_edi_sw_sign_payment(self, move, credentials, sri):
        return self._l10n_ec_edi_sw_sign(move, credentials, sri)

    def _l10n_ec_edi_sw_cancel_payment(self, move, credentials, sri):
        return self._l10n_ec_edi_sw_cancel(move, credentials, sri)'''

    # -------------------------------------------------------------------------
    # BUSINESS FLOW: EDI
    # -------------------------------------------------------------------------

    def _needs_web_services(self):
        # OVERRIDE
        return self.code == 'sri_ec' or super()._needs_web_services()

    def _is_compatible_with_journal(self, journal):
        # OVERRIDE
        self.ensure_one()
        if self.code != 'sri_ec':
            return super()._is_compatible_with_journal(journal)
        return journal.type == 'sale' and journal.country_code == 'EC'

    def _is_required_for_invoice(self, invoice):
        # OVERRIDE
        self.ensure_one()
        if self.code != 'sri_ec':
            return super()._is_required_for_invoice(invoice)

        # Determine on which invoices the Mexican SRI must be generated.
        return invoice.move_type in ('out_invoice', 'out_refund') and invoice.country_code == 'EC'

    '''def _is_required_for_payment(self, move):
        # OVERRIDE
        self.ensure_one()
        if self.code != 'sri_ec':
            return super()._is_required_for_payment(move)

        # Determine on which invoices the Mexican SRI must be generated.
        if move.country_code != 'EC':
            return False

        if (move.payment_id or move.statement_line_id).l10n_ec_edi_force_generate_sri:
            return True

        reconciled_invoices = move._get_reconciled_invoices()
        return 'PPD' in reconciled_invoices.mapped('l10n_ec_edi_payment_policy')'''

    def _l10n_ec_edi_cron_send_to_sri(self):
        to_process = self.env['account.move'].search([
            ('move_type', 'in', ['out_invoice', 'out_refund']),
            ('edi_state', 'in', ['to_send']),
            ('l10n_ec_edi_sat_status', 'not in', ['valid'])
        ], limit=1)
        _logger.warning(to_process)
        invoices = set()
        invoices.add(to_process)

        sri_edi_format = self.env.ref('l10n_ec_edi.edi_sri_ec')
        edi_format = self.env['account.edi.format'].search([
            ('id', '=', int(sri_edi_format))
        ])

        edi_format.sudo()._post_invoice_edi(invoices)

    def _post_invoice_edi(self, invoices, test_mode=False):
        # OVERRIDE
        _logger.warning("1070 ")
        _logger.warning(self)
        _logger.warning(len(invoices))

        edi_result = super()._post_invoice_edi(invoices, test_mode=test_mode)

        if self.code != 'sri_ec':
            return edi_result

        for invoice in invoices:
            if not invoice.id:
                return edi_result

            _logger.warning(invoice.id)
            _logger.warning("1076 " + invoice.move_type + " " + invoice.edi_state)


            if invoice.move_type in ('out_invoice', 'out_refund') and invoice.edi_state == 'to_send' and invoice.printer_point and invoice.l10n_latam_document_type_id.code:

                env_name = invoice.company_id.l10n_ec_edi_pac
                _logger.warning(1062)
                _logger.warning(env_name)
                _logger.warning(invoice.state)
                _logger.warning(invoice.name)

                # == Check the configuration ==
                if env_name != 'demo':
                    errors = self._l10n_ec_edi_check_configuration(invoice)
                    _logger.warning(errors)
                    if errors:
                        edi_result[invoice] = {
                            'error': self._l10n_ec_edi_format_error_message(_("Invalid configuration:"), errors),
                        }
                        continue

                # == Generate the SRI ==
                res = self._l10n_ec_edi_export_invoice_sri(invoice)

                if res.get('errors'):
                    edi_result[invoice] = {
                        'error': self._l10n_ec_edi_format_error_message(_("Failure during the generation of the SRI:"),
                                                                        res['errors']),
                    }
                    continue
                sri_str = res['sri_str']


                if not invoice.l10n_ec_edi_sri_uuid:
                    _logger.warning("not invoice.l10n_ec_edi_sri_uuid")
                    invoice.l10n_ec_edi_sri_uuid = res['sri_uuid']

                # == Call the web-service ==
                if test_mode or invoice.company_id.l10n_ec_edi_pac == 'demo':
                    res['sri_signed'] = res['sri_str']
                    res['sri_encoding'] = 'str'
                else:
                    credentials = self._l10n_ec_edi_get_edi_credentials(invoice)
                    if credentials.get('errors'):
                        edi_result[invoice] = {
                            'error': self._l10n_ec_edi_format_error_message(_("PAC authentification error:"),
                                                                            credentials['errors']),
                            'attachment': self._create_invoice_sri_attachment(invoice, base64.encodebytes(sri_str)),
                        }
                        continue

                    # res = getattr(self, '_l10n_ec_edi_%s_sign_invoice' % env_name)(invoice, credentials, res['sri_str'])
                    if env_name != 'demo':
                        res = self._l10n_ec_edi_sri_reception(invoice, credentials, res['sri_str'])
                        if res.get('errors'):
                            invoice.edi_state = 'to_cancel'
                            edi_result[invoice] = {
                                'error': self._l10n_ec_edi_format_error_message(
                                    _("SRI no pudo validar el documento electrónico:"), res['errors']),
                                'attachment': self._create_invoice_sri_attachment(invoice, sri_str),
                            }
                            continue

                    else:
                        res['sri_signed'] = res['sri_str']
                        res['sri_encoding'] = 'str'

                if res['sri_encoding'] == 'str':
                    res.update({
                        'sri_signed': base64.encodebytes(res['sri_signed']),
                        'sri_encoding': 'base64',
                    })

                # == Create the attachment ==
                sri_attachment = self._create_invoice_sri_attachment(invoice, res['sri_signed'])

                edi_result[invoice] = {'attachment': sri_attachment}

                invoice.l10n_ec_edi_sri_uuid = res['sri_uuid']

                # == Chatter ==
                invoice.with_context(no_new_invoice=True).message_post(
                    body=_("El documento electrónico fue creado y enviado con éxito al SRI."),
                    attachment_ids=sri_attachment.ids
                )
                invoice.edi_state = 'sent'
            else:
                _logger.warning("NO EDI " + invoice.move_type + " - " + invoice.name + " " + invoice.edi_state)
        return edi_result

    def _create_invoice_sri_attachment(self, invoice, data):
        sri_filename = ('%s-%s-SRIv220.xml' % (invoice.journal_id.code, invoice.name)).replace('/', '')
        description = _('Ecuador invoice SRI generated for the %s document.') % invoice.name
        return self._create_sri_attachment(sri_filename, description, invoice, data)

    def _create_sri_attachment(self, sri_filename, description, move, data):
        IrAttachment = self.env['ir.attachment']
        values = {
            'name': sri_filename,
            'res_id': move.id,
            'res_model': move._name,
            'type': 'binary',
            'datas': data,
            'mimetype': 'application/xml',
            'description': description,
        }
        attachment = IrAttachment.search(
            [('name', '=', sri_filename), ('res_model', '=', move._name), ('res_id', '=', move.id),
             ('type', '=', 'binary')])
        if attachment:
            attachment.write(values)
            return attachment[0]
        else:
            return IrAttachment.create(values)

    def _cancel_invoice_edi(self, invoices, test_mode=False):
        # OVERRIDE
        _logger.warning('_cancel_invoice_edi')
        edi_result = super()._cancel_invoice_edi(invoices, test_mode=test_mode)
        if self.code != 'sri_ec':
            return edi_result

        for invoice in invoices:
            _logger.warning(1153)
            _logger.warning(invoice.edi_state)
            _logger.warning(invoice.l10n_ec_edi_sat_status)
            if invoice.edi_state == 'sent' and invoice.l10n_ec_edi_sat_status == 'valid':
                _logger.warning('error')
                edi_result[invoice] = {
                    'error': 'Comprobante no puede ser cancelado, ya se encuentra autorizado o aún no ha sido enviado'}
                continue
            else:
                _logger.warning('to_send')
                invoice.edi_state = 'to_send'


            # == Chatter ==
            invoice.with_context(no_new_invoice=True).message_post(
                body=_("The SRI document has been successfully cancelled."),
                subtype_xmlid='account.mt_invoice_validated',
            )

        return edi_result

    '''def _post_payment_edi(self, payments, test_mode=False):
        # OVERRIDE
        edi_result = super()._post_payment_edi(payments, test_mode=test_mode)
        if self.code != 'sri_ec':
            return edi_result

        for move in payments:

            # == Check the configuration ==
            errors = self._l10n_ec_edi_check_configuration(move)
            if errors:
                edi_result[move] = {
                    'error': self._l10n_ec_edi_format_error_message(_("Invalid configuration:"), errors),
                }
                continue

            # == Generate the SRI ==
            res = self._l10n_ec_edi_export_payment_sri(move)
            if res.get('errors'):
                edi_result[move] = {
                    'error': self._l10n_ec_edi_format_error_message(_("Failure during the generation of the SRI:"), res['errors']),
                }
                continue
            sri_str = res['sri_str']

            # == Call the web-service ==
            if test_mode:
                res['sri_signed'] = res['sri_str']
                res['sri_encoding'] = 'str'
            else:
                env_name = move.company_id.l10n_ec_edi_pac

                credentials = getattr(self, '_l10n_ec_edi_get_%s_credentials' % env_name)(move)
                if credentials.get('errors'):
                    edi_result[move] = {
                        'error': self._l10n_ec_edi_format_error_message(_("PAC authentification error:"), credentials['errors']),
                        'attachment': self._create_payment_sri_attachment(move, base64.encodebytes(sri_str)),
                    }
                    continue

                res = getattr(self, '_l10n_ec_edi_%s_sign_payment' % env_name)(move, credentials, res['sri_str'])
                if res.get('errors'):
                    edi_result[move] = {
                        'error': self._l10n_ec_edi_format_error_message(_("SRI failed to validate the electronic document:"), res['errors']),
                        'attachment': self._create_payment_sri_attachment(move, base64.encodebytes(sri_str)),
                    }
                    continue

            # == Create the attachment ==
            sri_signed = res['sri_signed'] if res['sri_encoding'] == 'base64' else base64.encodebytes(res['sri_signed'])
            sri_attachment = self._create_payment_sri_attachment(move, sri_signed)
            edi_result[move] = {'attachment': sri_attachment}

            # == Chatter ==
            message = _("The SRI document has been successfully signed.")
            move.message_post(body=message, attachment_ids=sri_attachment.ids)
            if move.payment_id:
                move.payment_id.message_post(body=message, attachment_ids=sri_attachment.ids)

        return edi_result

    def _create_payment_sri_attachment(self, move, data):
        sri_filename = ('%s-%s-MX-Payment-10.xml' % (move.journal_id.code, move.name)).replace('/', '')
        descritpion = _('Mexican payment SRI generated for the %s document.') % move.name
        return self._create_sri_attachment(sri_filename, descritpion, move, data)

    def _cancel_payment_edi(self, moves, test_mode=False):
        # OVERRIDE
        edi_result = super()._cancel_payment_edi(moves, test_mode=test_mode)
        if self.code != 'sri_ec':
            return edi_result

        for move in moves:

            # == Check the configuration ==
            errors = self._l10n_ec_edi_check_configuration(move)
            if errors:
                edi_result[move] = {'error': self._l10n_ec_edi_format_error_message(_("Invalid configuration:"), errors)}
                continue

            # == Call the web-service ==
            if test_mode:
                res = {'success': True}
            else:
                env_name = move.company_id.l10n_ec_edi_pac

                credentials = getattr(self, '_l10n_ec_edi_get_%s_credentials' % env_name)(move)
                if credentials.get('errors'):
                    edi_result[move] = {'error': self._l10n_ec_edi_format_error_message(_("PAC authentification error:"), credentials['errors'])}
                    continue

                signed_edi = move._get_l10n_ec_edi_signed_edi_document()
                if signed_edi:
                    sri_data = base64.decodebytes(signed_edi.attachment_id.with_context(bin_size=False).datas)
                res = getattr(self, '_l10n_ec_edi_%s_cancel_payment' % env_name)(move, credentials, sri_data)
                if res.get('errors'):
                    edi_result[move] = {'error': self._l10n_ec_edi_format_error_message(_("PAC failed to cancel the SRI:"), res['errors'])}
                    continue

            edi_result[move] = res

            # == Chatter ==
            message = _("The SRI document has been successfully cancelled.")
            move.message_post(body=message)
            if move.payment_id:
                move.payment_id.message_post(body=message)

        return edi_result

    def button_cancel_posted_moves(self):
        # OVERRIDE
        #edi_result = super().button_cancel_posted_moves(self)
        to_cancel_documents = self.env['account.edi.document']
        if self.code != 'sri_ec':
            return edi_result

        for move in self:
            is_move_marked = False
            for doc in move.edi_document_ids:
                if doc.edi_format_id._needs_web_services() \
                        and doc.attachment_id \
                        and doc.state == 'sent' \
                        and move.is_invoice(include_receipts=True) \
                        and doc.edi_format_id._is_required_for_invoice(move):
                    to_cancel_documents |= doc
                    is_move_marked = True
            if is_move_marked:
                move.message_post(body=_("A cancellation of the EDI has been requested."))

        to_cancel_documents.write({'state': 'to_send', 'error': False})'''
