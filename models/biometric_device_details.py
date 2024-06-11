# -*- coding: utf-8 -*-
################################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2023-TODAY Cybrosys Technologies(<https://www.cybrosys.com>).
#    Author: Ammu Raj (odoo@cybrosys.com)
#
#    You can modify it under the terms of the GNU AFFERO
#    GENERAL PUBLIC LICENSE (AGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU AFFERO GENERAL PUBLIC LICENSE (AGPL v3) for more details.
#
#    You should have received a copy of the GNU AFFERO GENERAL PUBLIC LICENSE
#    (AGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
################################################################################

import datetime
import logging
import pytz
from odoo import fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

try:
    from zk import ZK, const
except ImportError:
    _logger.error("Please Install pyzk library.")


class BiometricDeviceDetails(models.Model):
    """Model for configuring and connecting the biometric device with Odoo"""
    _name = 'biometric.device.details'
    _description = 'Biometric Device Details'

    name = fields.Char(string='Name', required=True, help='Record Name')
    device_ip = fields.Char(string='Device IP', required=True, help='The IP address of the Device')
    port_number = fields.Integer(string='Port Number', required=True, help="The Port Number of the Device")
    comm_key = fields.Integer(string='Communication Key', required=True, help="The Communication Key for the Device")
    address_id = fields.Many2one('res.partner', string='Working Address', help='Working address of the partner')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.user.company_id.id, help='Current Company')

    def device_connect(self, zk):
        """Function for connecting the device with Odoo"""
        try:
            conn = zk.connect()
            return conn
        except Exception:
            return False

    def action_test_connection(self):
        """Checking the connection status"""
        zk = ZK(self.device_ip, port=self.port_number, timeout=30, password=self.comm_key, ommit_ping=False)
        try:
            if zk.connect():
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'message': 'Successfully Connected',
                        'type': 'success',
                        'sticky': False
                    }
                }
        except Exception as error:
            raise ValidationError(f'{error}')

    def action_clear_attendance(self):
        """Method to clear records from the zk.machine.attendance model and from the device"""
        for info in self:
            try:
                machine_ip = info.device_ip
                zk_port = info.port_number
                comm_key = info.comm_key
                try:
                    # Connecting with the device
                    zk = ZK(machine_ip, port=zk_port, timeout=30, password=comm_key, force_udp=False, ommit_ping=False)
                except NameError:
                    raise UserError(_("Please install it with 'pip3 install pyzk'."))
                conn = self.device_connect(zk)
                if conn:
                    conn.enable_device()
                    clear_data = zk.get_attendance()
                    if clear_data:
                        # Clearing data in the device
                        conn.clear_attendance()
                        # Clearing data from attendance log
                        self._cr.execute("""DELETE FROM zk_machine_attendance""")
                        conn.disconnect()
                    else:
                        raise UserError(_('Unable to clear Attendance log. Are you sure attendance log is not empty?'))
                else:
                    raise UserError(_('Unable to connect to Attendance Device. Please use the Test Connection button to verify.'))
            except Exception as error:
                raise ValidationError(f'{error}')

    def action_download_attendance(self):
        """Function to download attendance records from the device"""
        _logger.info("++++++++++++Cron Executed++++++++++++++++++++++")
        zk_attendance = self.env['zk.machine.attendance']
        hr_attendance = self.env['hr.attendance']
        for info in self:
            machine_ip = info.device_ip
            zk_port = info.port_number
            comm_key = info.comm_key
            try:
                zk = ZK(machine_ip, port=zk_port, timeout=15, password=comm_key, force_udp=False, ommit_ping=False)
            except NameError:
                raise UserError(_("Pyzk module not found. Please install it with 'pip3 install pyzk'."))
            conn = self.device_connect(zk)
            if conn:
                conn.disable_device()
                user = conn.get_users()
                attendance = conn.get_attendance()
                if attendance:
                    attendance_by_user = {}
                    for each in attendance:
                        atten_time = each.timestamp
                        local_tz = pytz.timezone(self.env.user.partner_id.tz or 'GMT')
                        local_dt = local_tz.localize(atten_time, is_dst=None)
                        utc_dt = local_dt.astimezone(pytz.utc)
                        utc_dt = utc_dt.strftime("%Y-%m-%d %H:%M:%S")
                        atten_time = datetime.datetime.strptime(utc_dt, "%Y-%m-%d %H:%M:%S")
                        atten_time_str = fields.Datetime.to_string(atten_time)
                        atten_date = atten_time.date()
    
                        if each.user_id not in attendance_by_user:
                            attendance_by_user[each.user_id] = {}
    
                        if atten_date not in attendance_by_user[each.user_id]:
                            attendance_by_user[each.user_id][atten_date] = {
                                'check_in': None,
                                'check_out': None
                            }
    
                        if each.punch == 0:  # check-in
                            if (not attendance_by_user[each.user_id][atten_date]['check_in'] or
                                    atten_time < attendance_by_user[each.user_id][atten_date]['check_in']):
                                attendance_by_user[each.user_id][atten_date]['check_in'] = atten_time
    
                        if each.punch == 1:  # check-out
                            if (not attendance_by_user[each.user_id][atten_date]['check_out'] or
                                    atten_time > attendance_by_user[each.user_id][atten_date]['check_out']):
                                attendance_by_user[each.user_id][atten_date]['check_out'] = atten_time
    
                    for user_id, dates in attendance_by_user.items():
                        for atten_date, times in dates.items():
                            check_in_time = times['check_in']
                            check_out_time = times['check_out']
    
                            if check_in_time:
                                get_user_id = self.env['hr.employee'].search([('device_id_num', '=', user_id)])
                                if not get_user_id:
                                    uid = next((u for u in user if u.user_id == user_id), None)
                                    if uid:
                                        get_user_id = self.env['hr.employee'].create({
                                            'device_id_num': user_id,
                                            'name': uid.name
                                        })
    
                                existing_hr_attendance = hr_attendance.search([
                                    ('employee_id', '=', get_user_id.id),
                                    ('check_in', '>=', fields.Datetime.to_string(datetime.datetime.combine(atten_date, datetime.time.min))),
                                    ('check_in', '<=', fields.Datetime.to_string(datetime.datetime.combine(atten_date, datetime.time.max))),
                                ])
    
                                if existing_hr_attendance:
                                    existing_hr_attendance.write({'check_in': check_in_time, 'check_out': check_out_time})
                                else:
                                    hr_attendance.create({
                                        'employee_id': get_user_id.id,
                                        'check_in': check_in_time,
                                        'check_out': check_out_time
                                    })
    
                                existing_zk_attendance = zk_attendance.search([
                                    ('device_id_num', '=', user_id),
                                    ('punching_time', '>=', fields.Datetime.to_string(datetime.datetime.combine(atten_date, datetime.time.min))),
                                    ('punching_time', '<=', fields.Datetime.to_string(datetime.datetime.combine(atten_date, datetime.time.max))),
                                ])
    
                                if existing_zk_attendance:
                                    existing_zk_attendance.write({
                                        'employee_id': get_user_id.id,
                                        'punching_time': check_in_time if check_in_time else check_out_time,
                                        'punch_type': '0' if check_in_time else '1',
                                        'address_id': info.address_id.id
                                    })
                                else:
                                    zk_attendance.create({
                                        'employee_id': get_user_id.id,
                                        'device_id_num': user_id,
                                        'punching_time': check_in_time if check_in_time else check_out_time,
                                        'punch_type': '0' if check_in_time else '1',
                                        'address_id': info.address_id.id
                                    })
    
                    conn.disconnect()
                    return True
                else:
                    raise UserError(_('Unable to get the attendance log, please try again later.'))
            else:
                raise UserError(_('Unable to connect, please check the parameters and network connections.'))

    def action_restart_device(self):
        """For restarting the device"""
        zk = ZK(self.device_ip, port=self.port_number, timeout=15, password=self.comm_key, force_udp=False, ommit_ping=False)
        self.device_connect(zk).restart()
