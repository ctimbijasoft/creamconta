from odoo import api, models, fields, tools, _

import logging
_logger = logging.getLogger(__name__)

class HrSalaryRuleCategory(models.Model):
    _inherit = 'hr.salary.rule.category'

    is_deductible = fields.Boolean(string='Is deductible', default=False)
