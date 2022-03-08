# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError

import logging

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'
    printer_point = fields.Many2one('account.printer.point', string='Printer Point', ondelete='set null',
                                    domain="[('l10n_latam_document_type', '=', l10n_latam_document_type_id)]")
    printer_point_next_number = fields.Char(string='Next Sequence', inverse='_inverse_printer_point_next_number')
    partner_shipping_id = fields.Many2one(
        'res.partner', string='Delivery Address', readonly=True, required=False,
        states={'draft': [('readonly', False)], 'sent': [('readonly', False)], 'sale': [('readonly', False)]},
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]", )

    @api.depends('posted_before', 'state', 'journal_id', 'date')
    def _compute_name(self):
        for move in self:
            _logger.warning(232323)
            _logger.warning(move.move_type)
            _logger.warning(move.name)
            _logger.warning(move.printer_point.sequence_id.name)
            if move.move_type == 'out_refund' and move.name == False:
                move.printer_point = move.company_id.l10n_ec_edi_nc_printer_point

            #_logger.warning(move.printer_point.sequence_id.name)
            if not move.printer_point.sequence_id:
                return super(AccountMove, self)._compute_name()
            sequence_id = move._get_sequence()
            if not sequence_id:
                raise UserError('Please define a sequence on your journal.')
            if move.state == 'draft':
                move.name = '/'
            elif move.state != 'draft':
                printer_sequence_next = sequence_id.with_context(
                    {'ir_sequence_date': self.invoice_date, 'bypass_constrains': True}).next_by_id(
                    sequence_date=self.invoice_date)
                move.name = "%s %s-%s" % (
                    move.l10n_latam_document_type_id.doc_code_prefix, move.printer_point.printer_point,
                    printer_sequence_next.zfill(9))

    @api.onchange('l10n_latam_document_type_id')
    def onchange_l10n_latam_document_type_id(self):
        self.printer_point = ''

    def _get_sequence(self):
        ''' Return the sequence to be used during the post of the current move.
        :return: An ir.sequence record or False.
        '''
        self.ensure_one()

        _logger.warning(42)
        _logger.warning(self.move_type)
        printer_point = self.printer_point
        if self.move_type in ('entry', 'out_invoice', 'in_invoice', 'out_receipt', 'in_receipt', 'out_refund'):
            return printer_point.sequence_id

    @api.onchange('printer_point')
    def _inverse_printer_point_next_number(self):
        for rec in self:
            rec.printer_point_next_number = str(rec.printer_point.sequence_number_next).zfill(9)


class PrinterPoint(models.Model):
    _name = "account.printer.point"
    # _rec_name = 'printer_point'
    _description = "Printer Point"

    printer_point = fields.Char(string='Name', required=True)
    printer_point_address = fields.Char(string='Address', required=True)
    sequence_id = fields.Many2one('ir.sequence', string='Entry Sequence',
                                  help="This field contains the information related to the numbering of the journal entries of this journal.",
                                  copy=False)
    sequence_number_next = fields.Integer(string='Next Number',
                                          help='The next sequence number will be used for the next invoice.',
                                          compute='_compute_seq_number_next',
                                          inverse='_inverse_seq_number_next')
    electronic_documents = fields.Boolean(string='Electronic Documents')
    enabled = fields.Boolean(string='Enabled')
    account_ids = fields.One2many('account.move', 'printer_point', string='Account')
    company_id = fields.Many2one('res.company', require=True, default=lambda self: self.env.user.company_id)
    l10n_latam_document_type = fields.Many2one('l10n_latam.document.type', string='Document Type')

    def name_get(self):
        result = []
        for printer_point in self:
            # name = str(printer_point.sequence_id.prefix) + str(printer_point.sequence_number_next)
            result.append(
                (printer_point.id, "{}".format(printer_point.printer_point)))
        return result

    # do not depend on 'sequence_id.date_range_ids', because
    # sequence_id._get_current_sequence() may invalidate it!
    @api.depends('sequence_id.use_date_range', 'sequence_id.number_next_actual')
    def _compute_seq_number_next(self):
        '''Compute 'sequence_number_next' according to the current sequence in use,
        an ir.sequence or an ir.sequence.date_range.
        '''
        for printer_point in self:
            if printer_point.sequence_id:
                sequence = printer_point.sequence_id._get_current_sequence()
                printer_point.sequence_number_next = sequence.number_next_actual
            else:
                printer_point.sequence_number_next = 1

    def _inverse_seq_number_next(self):
        '''Inverse 'sequence_number_next' to edit the current sequence next number.
        '''
        for printer_point in self:
            if printer_point.sequence_id and printer_point.sequence_number_next:
                sequence = printer_point.sequence_id._get_current_sequence()
                sequence.sudo().number_next = printer_point.sequence_number_next
