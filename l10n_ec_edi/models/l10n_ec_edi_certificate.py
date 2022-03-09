# -*- coding: utf-8 -*-

import base64
import logging
import ssl
import subprocess
import tempfile

import os
import subprocess

import random

import OpenSSL
from OpenSSL.crypto import load_pkcs12, FILETYPE_PEM
from datetime import datetime

_logger = logging.getLogger(__name__)

try:
    from OpenSSL import crypto
except ImportError:
    _logger.warning('OpenSSL library not found. If you plan to use l10n_ec_edi, please install the library from https://pypi.python.org/pypi/pyOpenSSL')

from pytz import timezone

from odoo import _, api, fields, models, tools
from odoo.exceptions import ValidationError, UserError
from odoo.tools.misc import DEFAULT_SERVER_DATETIME_FORMAT


#KEY_TO_PEM_CMD = 'openssl pkcs12 -in %s -nocerts -out %s -passin file:%s'
KEY_TO_PEM_CMD = 'openssl pkcs8 -in %s -inform der -outform pem -out %s -passin file:%s'

#from lxml import etree
#from signxml import XMLSigner, XMLVerifier

#data_to_sign = "<Test/>"
#cert = open("filename.crt").read()
#key = open("private.key").read()
#tree = ET.parse('doc.xml')
#root = tree.fromstring(data_to_sign)
#signed_root = XMLSigner().sign(root, key=key, cert=cert)
#verified_data = XMLVerifier().verify(signed_root).signed_xml




def convert_key_cer_to_pem(key, password):
    # TODO compute it from a python way
    with tempfile.NamedTemporaryFile('wb', suffix='.key', prefix='edi.mx.tmp.') as key_file, \
            tempfile.NamedTemporaryFile('wb', suffix='.txt', prefix='edi.mx.tmp.') as pwd_file, \
            tempfile.NamedTemporaryFile('rb', suffix='.key', prefix='edi.mx.tmp.') as keypem_file:
        key_file.write(key)
        key_file.flush()
        pwd_file.write(password)
        pwd_file.flush()
        subprocess.call((KEY_TO_PEM_CMD % (key_file.name, keypem_file.name, pwd_file.name)).split())
        key_pem = keypem_file.read()
    return key_pem


def str_to_datetime(dt_str, tz=timezone('America/Guayaquil')):
    return tz.localize(fields.Datetime.from_string(dt_str))


class Certificate(models.Model):
    _name = 'l10n_ec_edi.certificate'
    _description = 'SAT Digital Sail'
    _order = "date_start desc, id desc"

    content = fields.Binary(
        string='Certificate',
        help='Certificate in der format',
        required=False,
        attachment=False,)
    key = fields.Binary(
        string='Certificate Key',
        help='Certificate Key in der format',
        required=True,
        attachment=False,)
    password = fields.Char(
        string='Certificate Password',
        help='Password for the Certificate Key',
        required=True,)
    serial_number = fields.Char(
        string='Serial number',
        help='The serial number to add to electronic documents',
        readonly=True,
        index=True)
    date_start = fields.Datetime(
        string='Available date',
        help='The date on which the certificate starts to be valid',
        readonly=True)
    date_end = fields.Datetime(
        string='Expiration date',
        help='The date on which the certificate expires',
        readonly=True)

    def sign(self, xml_document, file_pk12, password, uuid):
        """
        Metodo que aplica la firma digital al XML
        TODO: Revisar return
        """
        _logger.warning('103 sign')
        xml_str = xml_document#.encode('utf-8')
        _logger.warning(xml_str)

        os.chdir(".")

        nameDocToSign = "sign/doc/ce" + uuid + ".xml"
        pathDocToSign = os.path.join(os.path.dirname(__file__), nameDocToSign)
        file = open(pathDocToSign, "w")
        file.seek(0)
        file.truncate()
        file.write(xml_str.encode('ascii', 'ignore').decode())
        file.close()

        nameSignatureFile = "sign/keys/k" + self.serial_number + self.create_date.strftime('%Y%m%dT%H%M%S') + ".p12"
        pathSignature = os.path.join(os.path.dirname(__file__), nameSignatureFile)
        file = open(pathSignature, "wb")
        file.seek(0)
        file.truncate()
        file.write(base64.b64decode(file_pk12))
        file.close()

        JAR_PATH = 'sign/firmaxades.jar'
        JAR_PATH = 'sign/firmadigital-jar-jar-with-dependencies.jar'
        JAR_PATH = 'sign/firmajasoft.jar'
        JAVA_CMD = 'java'
        firma_path = os.path.join(os.path.dirname(__file__), JAR_PATH)
        command = [
            JAVA_CMD,
            '-Xms128M',
            '-Xmx256M',
            '-jar',
            firma_path,
            pathDocToSign,
            pathSignature,#file_pk12,
            base64.b64encode(password.encode('utf-8')),
            uuid
        ]
        '''
        command = [
            JAVA_CMD,
            '-jar',
            firma_path
        ]'''
        _logger.warning(command)

        try:
            subprocess.check_output(command)
        except subprocess.CalledProcessError as e:
            returncode = e.returncode
            output = e.output
            logging.error('Llamada a proceso JAVA codigo: %s' % returncode)
            logging.error('Error: %s' % output)

        p = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT
        )
        res = p.communicate()
        return res[0]

    #@tools.ormcache('content')
    def get_pem_cer(self, content):
        '''Get the current content in PEM format
        '''
        self.ensure_one()
        return ssl.DER_cert_to_PEM_cert(base64.decodebytes(content)).encode('UTF-8')

    @tools.ormcache('key', 'password')
    def get_pem_key(self, key, password):
        '''Get the current key in PEM format
        '''
        self.ensure_one()
        return convert_key_cer_to_pem(base64.decodebytes(key), password.encode('UTF-8'))

    def get_data(self):
        '''Return the content (b64 encoded) and the certificate decrypted
        '''
        self.ensure_one()
        cer_pem = self.get_pem_cer(self.content)
        certificate = crypto.load_certificate(crypto.FILETYPE_PEM, cer_pem)
        for to_del in ['\n', ssl.PEM_HEADER, ssl.PEM_FOOTER]:
            cer_pem = cer_pem.replace(to_del.encode('UTF-8'), b'')
        return cer_pem, certificate

    def get_mx_current_datetime(self):
        '''Get the current datetime with the Mexican timezone.
        '''
        return fields.Datetime.context_timestamp(
            self.with_context(tz='America/Guayaquil'), fields.Datetime.now())

    def get_valid_certificate(self):
        '''Search for a valid certificate that is available and not expired.
        '''
        _logger.warning('get_valid_certificate')
        mexican_dt = self.get_mx_current_datetime()
        _logger.warning(mexican_dt)
        _logger.warning(self)
        for record in self:
            _logger.warning(record)
            date_start = str_to_datetime(record.date_start)
            date_end = str_to_datetime(record.date_end)
            _logger.warning(date_start)
            _logger.warning(date_end)
            if date_start <= mexican_dt <= date_end:
                return record
        return None

    def get_encrypted_cadena(self, cadena, uuid):
        '''Encrypt the cadena using the private key.
        '''
        cadena = cadena.decode("utf-8").strip()
        cadena_crypted = self.sign(cadena, self.key, self.password, uuid)
        cadena_crypted = cadena_crypted.replace(b'i18n/dictionaries/ - MITyCLibXAdES - es_419', b'')
        cadena_crypted = cadena_crypted.replace(b'i18n/dictionaries/ - MITyCLibXAdES - en', b'')

        cadena_crypted = cadena_crypted[1:]
        #_logger.warning(cadena_crypted)

        return cadena_crypted

    @api.constrains('content', 'key', 'password')
    def _check_credentials(self):
        '''Check the validity of content/key/password and fill the fields
        with the certificate values.
        '''
        mexican_tz = timezone('America/Guayaquil')
        mexican_dt = self.get_mx_current_datetime()
        _logger.warning('date');
        date_format = '%Y%m%d%H%M%SZ'
        for record in self:
            # Try to decrypt the certificate
            try:
                p12 = crypto.load_pkcs12(base64.decodebytes(record.key), record.password.encode('UTF-8'))
            except Exception:
                raise ValidationError(_('The certificate key and/or password is/are invalid.'))

            try:
                certificate = p12.get_certificate()

                sn = p12.get_certificate().get_subject().get_components()[4][1]
                record.serial_number = sn

                before = mexican_tz.localize(
                    datetime.strptime(certificate.get_notBefore().decode("utf-8"), date_format))
                after = mexican_tz.localize(
                    datetime.strptime(certificate.get_notAfter().decode("utf-8"), date_format))
                serial_number = certificate.get_serial_number()
            except UserError as exc_orm:  # ;-)
                raise exc_orm
            except Exception:
                raise ValidationError(_('The certificate content is invalid.'))
            # Assign extracted values from the certificate
            record.serial_number = ('%x' % serial_number)[1::2]
            record.date_start = before.strftime(DEFAULT_SERVER_DATETIME_FORMAT)
            record.date_end = after.strftime(DEFAULT_SERVER_DATETIME_FORMAT)
            if mexican_dt > after:
                raise ValidationError(_('The certificate is expired since %s', record.date_end))

    @api.model
    def create(self, data):
        res = super(Certificate, self).create(data)
        self.clear_caches()
        return res

    def write(self, data):
        res = super(Certificate, self).write(data)
        self.clear_caches()
        return res

    def unlink(self):
        mx_edi = self.env.ref('l10n_ec_edi.edi_sir_2_20')
        if self.env['account.edi.document'].sudo().search([
            ('edi_format_id', '=', mx_edi.id),
            ('attachment_id', '!=', False),
        ], limit=1):
            raise UserError(_(
                'You cannot remove a certificate if at least an invoice has been signed. '
                'Expired Certificates will not be used as Odoo uses the latest valid certificate. '
                'To not use it, you can unlink it from the current company certificates.'))
        res = super(Certificate, self).unlink()
        self.clear_caches()
        return res
