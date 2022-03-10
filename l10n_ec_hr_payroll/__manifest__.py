# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': 'Ecuadorian Payroll',
    'category': 'Human Resources/Payroll',
    'author': 'Jasoft',
    'depends': ['om_hr_payroll', 'l10n_ec'],
    'description': """
Ecuadorian Payroll Rules.
=====================
    - Configuration of om_hr_payroll for Ecuadorian localization
    """,
    'data': [
        'data/l10n_ec_hr_payroll_data.xml',
        'data/l10n_ec_hr_payroll_employe_frame_data.xml',
        'views/hr_employee_views.xml',
    ],
}
