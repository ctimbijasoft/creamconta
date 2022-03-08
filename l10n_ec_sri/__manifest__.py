# -*- coding: utf-8 -*-

{
    'name': 'Utilidades para SRI',
    'version': '14.0.1.0',
    'summary': 'Utilidades para SRI',
    'sequence': 10,
    'description': """Manejo de varias utilidades para SRI (Ecuador)""",
    'category': 'Tools',
    'website': 'https://www.jasoft.com',
    'depends': ['base', 'account', 'l10n_latam_invoice_document', 'l10n_latam_base'],
    'data': ['views/account_move_view.xml',
             'views/printer_point_view.xml',
             'views/sri_payment_method.xml',
             'views/sri_tax_support.xml',
             'security/ir.model.access.csv',
             'security/security.xml',
             'data/account_tax_support_data.xml',
             'data/account_payment_method_data.xml'
             ],
    'demo': [],
    'qweb': [],
    'installable': True,
    'application': True,
    'auto_install': False,
}
