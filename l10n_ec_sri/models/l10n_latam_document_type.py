# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
from odoo import models, fields
from odoo.exceptions import ValidationError

import logging

_logger = logging.getLogger(__name__)


class L10nLatamDocumentType(models.Model):

    _inherit = 'l10n_latam.document.type'

    def _format_document_number(self, document_number):
        """ Make validation of Import Dispatch Number
          * making validations on the document_number. If it is wrong it should raise an exception
          * format the document_number against a pattern and return it
        """
        self.ensure_one()
        if self.country_id.code != "EC":
            return super()._format_document_number(document_number)

        if not document_number:
            return False

        if self.l10n_ec_validate_number:
            parts = document_number.split('-')
            if len(parts) == 3:
                establecimiento = parts[0].zfill(3)
                punto_emision = parts[1].zfill(3)
                numero = parts[2].zfill(10)
                number = establecimiento + '-' + punto_emision + '-' + numero
                _logger.warning(number)
                return number
            else:
                raise ValidationError('Verificar que el número de documento sea de la forma ###-###-########## (ejemplo: 001-001-0001234567)')


        return document_number
