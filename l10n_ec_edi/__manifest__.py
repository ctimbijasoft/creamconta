# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
{
    'name': 'EDI for Ecuador',
    'version': '0.1',
    'author': 'Jasoft Cía. Ltda.',
    'category': 'Accounting/Localizations/EDI',
    'summary': 'Ecuatorian Localization for EDI documents',
    'description': """
EDI Ecuatorian Localization
========================
Allow the user to generate the EDI document for Ecuatorian invoicing and other electronic receipts

This module allows the creation of the EDI documents and the communication with the SRI  to autorization them.
    """,
    'depends': [
        'account_edi',
        'l10n_ec',
        'base_vat',
        'base_address_extended',
        'attachment_indexation',
        'base_address_city',
        #'product_unspsc'
    ],
    'external_dependencies': {
        'python': ['pyOpenSSL'],
    },
    'data': [
        'security/ir.model.access.csv',
        'security/l10n_ec_edi_certificate.xml',

        #'data/2_20srii.xml',
        'data/sri_fac_v110v2.xml',
        'data/sri_nc_v110v2.xml',
        #'data/2_20/payment10.xml',
        'data/account_edi_data.xml',
        #'data/l10n_ec_edi_payment_method_data.xml',
        'data/ir_cron.xml',
        #'data/res_partner_data.xml',
        #'data/res_country_data.xml',
        'data/res_currency_data.xml',

        #'views/account_bank_statement_view.xml',
        #'views/account_journal_view.xml',
        'views/account_move_view.xml',
        #'views/account_payment_view.xml',
        #'views/account_payment_register_views.xml',
        #'views/account_tax_view.xml',
        'views/ir_ui_view.xml',
        'views/l10n_ec_edi_certificate_view.xml',
        #'views/l10n_ec_edi_payment_method_view.xml',
        "views/l10n_ec_edi_report_invoice.xml",
        #'views/res_partner_view.xml',
        #'views/res_bank_view.xml',
        'views/res_company_view.xml',
        'views/res_config_settings_view.xml',
        #'views/res_country_view.xml',
    ],
    'demo': [
        #'demo/demo_sri.xml',
        #'demo/demo_addenda.xml',
    ],
    #'post_init_hook': 'post_init_hook',
    'installable': True,
    'auto_install': True,
    'license': 'LGPL-3',
}
