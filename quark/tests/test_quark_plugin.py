# Copyright 2013 Openstack Foundation
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
#  under the License.

from oslo.config import cfg
from quantum import context
from quantum.db import api as db_api

import quark.plugin

import test_base


class TestQuarkPlugin(test_base.TestBase):
    def setUp(self):
        cfg.CONF.set_override('sql_connection', 'sqlite://', 'DATABASE')
        db_api.configure_db()
        self.context = context.get_admin_context()
        self.plugin = quark.plugin.Plugin()

    def tearDown(self):
        db_api.clear_db()


class TestSubnets(TestQuarkPlugin):
    def test_allocated_ips_only(self):
        # 1. Create network
        network = {'network': {'name': 'test'}}
        response = self.plugin.create_network(self.context, network)
        network_id = response['id']

        # 2. Create subnet
        subnet = {'subnet': {'cidr': '192.168.10.1/24',
                             'network_id': network_id}}
        self.plugin.create_subnet(self.context, subnet)

        # 3. Create M.A.R.
        mac_range = {'mac_address_range': {'cidr': '01:23:45/24'}}
        self.plugin.create_mac_address_range(self.context, mac_range)

        # 4. Create port
        port = {'port': {'network_id': network_id,
                         'device_id': ''}}
        response = self.plugin.create_port(self.context, port)
        port = self.plugin.get_port(self.context, response['id'])

        self.assertTrue(len(port['fixed_ips']) >= 1)

        # 5. Delete port.
        self.plugin.delete_port(self.context, response['id'])

        # TODO(jkoelker) once the ip_addresses controller is in the api
        #                grab the fixed_ip from that and make sure it has
        #                no ports


class TestIpAddresses(TestQuarkPlugin):
    def test_create_ip_address_success(self):
        pass

    def test_create_ip_success_failure(self):
        pass

    def test_get_ip_address_success(self):
        pass

    def test_get_ip_address_failure(self):
        pass

    def test_get_ip_addresses_success(self):
        pass

    def test_update_ip_address_success(self):
        pass