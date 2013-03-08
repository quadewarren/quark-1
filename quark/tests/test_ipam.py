# Copyright (c) 2013 OpenStack Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from datetime import datetime
import mock
import netaddr

from oslo.config import cfg
from quantum import context
from quantum.common import exceptions
from quantum.db import api as db_api

from quark.db import models
import quark.ipam

import test_base


class TestQuarkIpamBase(test_base.TestBase):
    def setUp(self):
        cfg.CONF.set_override('sql_connection', 'sqlite://', 'DATABASE')
        db_api.configure_db()
        models.BASEV2.metadata.create_all(db_api._ENGINE)
        self.ipam = quark.ipam.QuarkIpam()
        self.context = context.get_admin_context()

    def tearDown(self):
        db_api.clear_db()

    def _create_and_insert_mar(self, base='01:02:03:00:00:00', mask=24):
        first_address = int(base.replace(':', ''), base=16)
        last_address = first_address + (1 << (48 - mask))
        mar = models.MacAddressRange(cidr=base + '/' + str(mask),
                                     first_address=first_address,
                                     last_address=last_address)
        self.context.session.add(mar)
        self.context.session.flush()

    def test_allocate_mac_address_no_ranges(self):
        net_id = None
        port_id = None
        tenant_id = None
        reuse_after = 0

        with self.assertRaises(exceptions.MacAddressGenerationFailure):
            self.ipam.allocate_mac_address(self.context.session,
                                           net_id,
                                           port_id,
                                           tenant_id,
                                           reuse_after)

    def test_allocate_mac_address_success(self):
        net_id = None
        port_id = None
        tenant_id = 'foobar'
        reuse_after = 0

        self._create_and_insert_mar()
        mar = self.context.session.query(models.MacAddressRange).first()

        mac = self.ipam.allocate_mac_address(self.context.session,
                                             net_id,
                                             port_id,
                                             tenant_id,
                                             reuse_after)

        self.assertEqual(mac['tenant_id'], tenant_id)
        self.assertIsNone(mac['created_at'])  # null pre-insert
        self.assertEqual(mac['address'], mar['first_address'])
        self.assertEqual(mac['mac_address_range_id'], mar['id'])
        self.assertFalse(mac['deallocated'])
        self.assertIsNone(mac['deallocated_at'])

    def test_allocate_mac_address_deallocated_success(self):
        net_id = None
        port_id = None
        tenant_id = 'foobar'
        reuse_after = 0

        self._create_and_insert_mar()
        mar = self.context.session.query(models.MacAddressRange).first()

        mac_deallocated = models.MacAddress(tenant_id=tenant_id,
                                            address=mar['first_address'],
                                            mac_address_range_id=mar['id'],
                                            deallocated=True,
                                            deallocated_at=datetime(1970,
                                                                    1,
                                                                    1))
        self.context.session.add(mac_deallocated)
        self.context.session.flush()

        mac = self.ipam.allocate_mac_address(self.context.session,
                                             net_id,
                                             port_id,
                                             tenant_id,
                                             reuse_after)

        self.assertEqual(mac['tenant_id'], tenant_id)
        self.assertIsNotNone(mac['created_at'])  # non-null post-insert
        self.assertEqual(mac['address'], mar['first_address'])
        self.assertEqual(mac['mac_address_range_id'], mar['id'])
        self.assertFalse(mac['deallocated'])
        self.assertIsNone(mac['deallocated_at'])

    def test_allocate_mac_address_deallocated_failure(self):
        '''Fails based on the choice of reuse_after argument. Allocates new mac
        address instead of previously deallocated mac address.'''
        net_id = None
        port_id = None
        tenant_id = 'foobar'
        reuse_after = 3600
        test_datetime = datetime(1970, 1, 1)
        deallocated_at = test_datetime

        self._create_and_insert_mar()
        mar = self.context.session.query(models.MacAddressRange).first()

        mac_deallocated = models.MacAddress(tenant_id=tenant_id,
                                            address=mar['first_address'],
                                            mac_address_range_id=mar['id'],
                                            deallocated=True,
                                            deallocated_at=deallocated_at)
        self.context.session.add(mac_deallocated)
        self.context.session.flush()

        with mock.patch('quark.ipam.timeutils') as timeutils:
            timeutils.utcnow.return_value = test_datetime
            mac = self.ipam.allocate_mac_address(self.context.session,
                                                 net_id,
                                                 port_id,
                                                 tenant_id,
                                                 reuse_after)

            self.assertEqual(mac['tenant_id'], tenant_id)
            self.assertIsNone(mac['created_at'])  # null pre-insert
            self.assertEqual(mac['address'], mar['first_address'] + 1)
            self.assertEqual(mac['mac_address_range_id'], mar['id'])
            self.assertFalse(mac['deallocated'])
            self.assertIsNone(mac['deallocated_at'])

    def test_allocate_mac_address_second_mac(self):
        net_id = None
        port_id = None
        tenant_id = 'foobar'
        reuse_after = 0

        self._create_and_insert_mar()
        mar = self.context.session.query(models.MacAddressRange).first()

        mac = models.MacAddress(tenant_id=tenant_id,
                                address=mar['first_address'],
                                mac_address_range_id=mar['id'],
                                deallocated=False,
                                deallocated_at=None)
        self.context.session.add(mac)
        self.context.session.flush()

        mac2 = self.ipam.allocate_mac_address(self.context.session,
                                              net_id,
                                              port_id,
                                              tenant_id,
                                              reuse_after)

        self.assertEqual(mac2['tenant_id'], tenant_id)
        self.assertIsNone(mac2['created_at'])  # null pre-insert
        self.assertEqual(mac2['address'], mar['first_address'] + 1)
        self.assertEqual(mac2['mac_address_range_id'], mar['id'])
        self.assertFalse(mac2['deallocated'])
        self.assertIsNone(mac2['deallocated_at'])

    def test_allocate_mac_address_fully_allocated_range(self):
        net_id = None
        port_id = None
        tenant_id = 'foobar'
        reuse_after = 0

        self._create_and_insert_mar(mask=48)
        mar = self.context.session.query(models.MacAddressRange).first()

        mac = models.MacAddress(tenant_id=tenant_id,
                                address=mar['first_address'],
                                mac_address_range_id=mar['id'],
                                deallocated=False,
                                deallocated_at=None)
        self.context.session.add(mac)
        self.context.session.flush()

        with self.assertRaises(exceptions.MacAddressGenerationFailure):
            self.ipam.allocate_mac_address(self.context.session,
                                           net_id,
                                           port_id,
                                           tenant_id,
                                           reuse_after)

    def test_allocate_mac_address_multiple_ranges(self):
        '''Tests that new address is allocated in m.a.r. that has the most macs
        allocated to it.'''
        net_id = None
        port_id = None
        tenant_id = 'foobar'
        reuse_after = 0

        self._create_and_insert_mar()
        mar = self.context.session.query(models.MacAddressRange).first()

        mac = models.MacAddress(tenant_id=tenant_id,
                                address=mar['first_address'],
                                mac_address_range_id=mar['id'],
                                deallocated=False,
                                deallocated_at=None)
        self.context.session.add(mac)
        self.context.session.flush()

        self._create_and_insert_mar(base='01:02:04:00:00:00')

        mac = self.ipam.allocate_mac_address(self.context.session,
                                             net_id,
                                             port_id,
                                             tenant_id,
                                             reuse_after)

        self.assertEqual(mac['tenant_id'], tenant_id)
        self.assertIsNone(mac['created_at'])  # null pre-insert
        self.assertEqual(mac['address'], mar['first_address'] + 1)
        self.assertEqual(mac['mac_address_range_id'], mar['id'])
        self.assertFalse(mac['deallocated'])
        self.assertIsNone(mac['deallocated_at'])

    def test_deallocate_mac_address_failure(self):
        with self.assertRaises(exceptions.NotFound):
            self.ipam.deallocate_mac_address(self.context.session,
                                             '01:02:04:00:00:00')

    def test_deallocate_mac_address_success(self):
        tenant_id = 'foobar'

        self._create_and_insert_mar()
        mar = self.context.session.query(models.MacAddressRange).first()

        mac = models.MacAddress(tenant_id=tenant_id,
                                address=mar['first_address'],
                                mac_address_range_id=mar['id'],
                                deallocated=False,
                                deallocated_at=None)
        self.context.session.add(mac)
        self.context.session.flush()

        test_datetime = datetime(1970, 1, 1)
        with mock.patch('quark.ipam.timeutils') as timeutils:
            timeutils.utcnow.return_value = test_datetime
            self.ipam.deallocate_mac_address(self.context.session,
                                             mar['first_address'])

        mac = self.context.session.query(models.MacAddress).first()
        self.assertTrue(mac['deallocated'])
        self.assertEqual(mac['deallocated_at'], test_datetime)

    def _create_and_insert_net(self, name='mynet', tenant_id='foobar'):
        net = models.Network()
        net['name'] = name
        net['tenant_id'] = tenant_id
        self.context.session.add(net)
        self.context.session.flush()

    def _create_and_insert_subnet(self, net_id, tenant_id='foobar',
                                  cidr='192.168.10.1/24'):
        subnet = models.Subnet()
        subnet['tenant_id'] = tenant_id
        subnet['network_id'] = net_id
        subnet['cidr'] = cidr
        self.context.session.add(subnet)
        self.context.session.flush()

    def _create_and_insert_port(self, net_id, id='123', backend_key='123',
                                device_id='123', tenant_id='foobar'):
        port = models.Port()
        port['tenant_id'] = tenant_id
        port['id'] = id
        port['network_id'] = net_id
        port['backend_key'] = backend_key
        port['mac_address'] = None
        port['device_id'] = device_id
        self.context.session.add(port)
        self.context.session.flush()

    def _create_and_insert_ip(self, ports, subnet_id, net_id,
                              tenant_id='foobar',
                              address='::ffff:192.168.10.0',
                              deallocated=False, deallocated_at=None):
        ipaddress = models.IPAddress()
        ipaddress['tenant_id'] = tenant_id
        ipaddress['address_readable'] = address
        ipaddress['address'] = int(netaddr.IPAddress(address))
        ipaddress['subnet_id'] = subnet_id
        ipaddress['network_id'] = net_id
        ipaddress['version'] = 4
        ipaddress['deallocated'] = deallocated
        ipaddress['deallocated_at'] = deallocated_at
        if not deallocated:
            for port in ports:
                port['ip_addresses'].extend([ipaddress])
        self.context.session.add(ipaddress)
        self.context.session.flush()

    def test_allocate_ip_address_deallocated_success(self):
        tenant_id = 'foobar'
        test_datetime = datetime(1970, 1, 1)
        reuse_after = 0

        self._create_and_insert_net()
        net = self.context.session.query(models.Network).first()

        self._create_and_insert_subnet(net['id'])
        subnet = self.context.session.query(models.Subnet).first()

        self._create_and_insert_port(net['id'])
        port = self.context.session.query(models.Port).first()

        self._create_and_insert_ip([port],
                                   subnet['id'],
                                   net['id'],
                                   deallocated=True,
                                   deallocated_at=test_datetime)

        ipaddress = self.ipam.allocate_ip_address(self.context.session,
                                                  net['id'],
                                                  port['id'],
                                                  tenant_id,
                                                  reuse_after)

        self.assertIsNotNone(ipaddress['id'])
        self.assertEqual(ipaddress['tenant_id'], tenant_id)
        self.assertEqual(ipaddress['address_readable'], '::ffff:192.168.10.0')
        self.assertEqual(int(ipaddress['address']),
                         int(netaddr.IPAddress('::ffff:192.168.10.0')))
        self.assertEqual(ipaddress['subnet_id'], subnet['id'])
        self.assertEqual(ipaddress['network_id'], net['id'])
        self.assertEqual(ipaddress['version'], 4)
        self.assertFalse(ipaddress['deallocated'])
        self.assertIsNone(ipaddress['deallocated_at'])
        self.assertEqual(len(ipaddress['ports']), 0)

    def test_allocate_ip_address_deallocated_failure(self):
        '''Fails based on the choice of reuse_after argument. Allocates new ip
        address instead of previously deallocated mac address.'''
        tenant_id = 'foobar'
        test_datetime = datetime(1970, 1, 1)
        reuse_after = 3600

        self._create_and_insert_net()
        net = self.context.session.query(models.Network).first()

        self._create_and_insert_subnet(net['id'])
        subnet = self.context.session.query(models.Subnet).first()

        self._create_and_insert_port(net['id'])
        port = self.context.session.query(models.Port).first()

        self._create_and_insert_ip([port],
                                   subnet['id'],
                                   net['id'],
                                   deallocated=True,
                                   deallocated_at=test_datetime)

        with mock.patch('quark.ipam.timeutils') as timeutils:
            timeutils.utcnow.return_value = test_datetime
            ipaddress = self.ipam.allocate_ip_address(self.context.session,
                                                      net['id'],
                                                      port['id'],
                                                      tenant_id,
                                                      reuse_after)
            self.assertIsNone(ipaddress['id'])
            self.assertEqual(ipaddress['tenant_id'], tenant_id)
            self.assertEqual(ipaddress['address_readable'],
                             '::ffff:192.168.10.1')
            self.assertEqual(ipaddress['address'],
                             int(netaddr.IPAddress('::ffff:192.168.10.1')))
            self.assertEqual(ipaddress['subnet_id'], subnet['id'])
            self.assertEqual(ipaddress['network_id'], net['id'])
            self.assertEqual(ipaddress['version'], 4)
            self.assertFalse(ipaddress['deallocated'])
            self.assertIsNone(ipaddress['deallocated_at'])
            self.assertEqual(len(ipaddress['ports']), 0)

    def test_allocate_ip_address_no_subnets_failure(self):
        net_id = None
        port_id = None
        tenant_id = None
        reuse_after = 0
        with self.assertRaises(exceptions.IpAddressGenerationFailure):
            self.ipam.allocate_ip_address(self.context.session,
                                          net_id,
                                          port_id,
                                          tenant_id,
                                          reuse_after)

    def test_allocate_ip_address_fully_allocated_subnet(self):
        tenant_id = 'foobar'
        reuse_after = 0

        self._create_and_insert_net()
        net = self.context.session.query(models.Network).first()

        self._create_and_insert_subnet(net['id'], cidr='192.168.10.1/32')
        subnet = self.context.session.query(models.Subnet).first()

        self._create_and_insert_port(net['id'])
        port = self.context.session.query(models.Port).first()

        self._create_and_insert_ip([port],
                                   subnet['id'],
                                   net['id'])

        with self.assertRaises(exceptions.IpAddressGenerationFailure):
            ipaddress = self.ipam.allocate_ip_address(self.context.session,
                                                      net['id'],
                                                      port['id'],
                                                      tenant_id,
                                                      reuse_after)

    def test_allocate_ip_address_multiple_subnets(self):
        tenant_id = 'foobar'
        reuse_after = 0

        self._create_and_insert_net()
        net = self.context.session.query(models.Network).first()

        self._create_and_insert_subnet(net['id'])
        primary_subnet = self.context.session.query(models.Subnet).first()
        self._create_and_insert_subnet(net['id'], cidr='192.168.20.1/24')

        self._create_and_insert_port(net['id'])
        port = self.context.session.query(models.Port).first()

        self._create_and_insert_ip([port], primary_subnet['id'], net['id'])

        ipaddress = self.ipam.allocate_ip_address(self.context.session,
                                                  net['id'],
                                                  port['id'],
                                                  tenant_id,
                                                  reuse_after)
        self.assertIsNone(ipaddress['id'])
        self.assertEqual(ipaddress['tenant_id'], tenant_id)
        self.assertEqual(ipaddress['address_readable'], '::ffff:192.168.10.1')
        self.assertEqual(ipaddress['address'],
                         int(netaddr.IPAddress('::ffff:192.168.10.1')))
        self.assertEqual(ipaddress['subnet_id'], primary_subnet['id'])
        self.assertEqual(ipaddress['network_id'], net['id'])
        self.assertEqual(ipaddress['version'], 4)
        self.assertFalse(ipaddress['deallocated'])
        self.assertIsNone(ipaddress['deallocated_at'])
        self.assertEqual(len(ipaddress['ports']), 0)

    def test_allocate_ip_address_multiple_networks_subnet(self):
        tenant_id = 'foobar'
        reuse_after = 0

        self._create_and_insert_net(name='mynet')
        self._create_and_insert_net(name='mynet2')
        primary_net = self.context.session.query(models.Network).first()

        self._create_and_insert_subnet(primary_net['id'])
        subnet = self.context.session.query(models.Subnet).first()

        self._create_and_insert_port(primary_net['id'])
        port = self.context.session.query(models.Port).first()

        ipaddress = self.ipam.allocate_ip_address(self.context.session,
                                                  primary_net['id'],
                                                  port['id'],
                                                  tenant_id,
                                                  reuse_after)
        self.assertIsNone(ipaddress['id'])
        self.assertEqual(ipaddress['tenant_id'], tenant_id)
        self.assertEqual(ipaddress['address_readable'], '::ffff:192.168.10.0')
        self.assertEqual(ipaddress['address'],
                         int(netaddr.IPAddress('::ffff:192.168.10.0')))
        self.assertEqual(ipaddress['subnet_id'], subnet['id'])
        self.assertEqual(ipaddress['network_id'], primary_net['id'])
        self.assertEqual(ipaddress['version'], 4)
        self.assertFalse(ipaddress['deallocated'])
        self.assertIsNone(ipaddress['deallocated_at'])
        self.assertEqual(len(ipaddress['ports']), 0)

    def test_allocate_ip_address_multiple_networks_deallocated(self):
        tenant_id = 'foobar'
        test_datetime = datetime(1970, 1, 1)
        reuse_after = 0

        self._create_and_insert_net(name='mynet')
        self._create_and_insert_net(name='mynet2')
        primary_net = self.context.session.query(models.Network).first()

        self._create_and_insert_subnet(primary_net['id'])
        subnet = self.context.session.query(models.Subnet).first()

        self._create_and_insert_port(primary_net['id'])
        port = self.context.session.query(models.Port).first()

        self._create_and_insert_ip([port],
                                   subnet['id'],
                                   primary_net['id'],
                                   deallocated=True,
                                   deallocated_at=test_datetime)

        ipaddress = self.ipam.allocate_ip_address(self.context.session,
                                                  primary_net['id'],
                                                  port['id'],
                                                  tenant_id,
                                                  reuse_after)
        self.assertIsNotNone(ipaddress['id'])
        self.assertEqual(ipaddress['tenant_id'], tenant_id)
        self.assertEqual(ipaddress['address_readable'], '::ffff:192.168.10.0')
        self.assertEqual(int(ipaddress['address']),
                         int(netaddr.IPAddress('::ffff:192.168.10.0')))
        self.assertEqual(ipaddress['subnet_id'], subnet['id'])
        self.assertEqual(ipaddress['network_id'], primary_net['id'])
        self.assertEqual(ipaddress['version'], 4)
        self.assertFalse(ipaddress['deallocated'])
        self.assertIsNone(ipaddress['deallocated_at'])
        self.assertEqual(len(ipaddress['ports']), 0)

    def test_allocate_ip_address_success(self):
        tenant_id = 'foobar'
        reuse_after = 0

        self._create_and_insert_net()
        net = self.context.session.query(models.Network).first()

        self._create_and_insert_subnet(net['id'])
        subnet = self.context.session.query(models.Subnet).first()

        self._create_and_insert_port(net['id'])
        port = self.context.session.query(models.Port).first()

        ipaddress = self.ipam.allocate_ip_address(self.context.session,
                                                  net['id'],
                                                  port['id'],
                                                  tenant_id,
                                                  reuse_after)
        self.assertIsNone(ipaddress['id'])
        self.assertEqual(ipaddress['tenant_id'], tenant_id)
        self.assertEqual(ipaddress['address_readable'], '::ffff:192.168.10.0')
        self.assertEqual(ipaddress['address'],
                         int(netaddr.IPAddress('::ffff:192.168.10.0')))
        self.assertEqual(ipaddress['subnet_id'], subnet['id'])
        self.assertEqual(ipaddress['network_id'], net['id'])
        self.assertEqual(ipaddress['version'], 4)
        self.assertFalse(ipaddress['deallocated'])
        self.assertIsNone(ipaddress['deallocated_at'])
        self.assertEqual(len(ipaddress['ports']), 0)

    def test_allocate_ip_address_multiple_ips(self):
        tenant_id = 'foobar'
        reuse_after = 0

        self._create_and_insert_net()
        net = self.context.session.query(models.Network).first()

        self._create_and_insert_subnet(net['id'])
        subnet = self.context.session.query(models.Subnet).first()

        self._create_and_insert_port(net['id'])
        port = self.context.session.query(models.Port).first()

        ipaddress = self.ipam.allocate_ip_address(self.context.session,
                                                  net['id'],
                                                  port['id'],
                                                  tenant_id,
                                                  reuse_after)
        self.assertIsNone(ipaddress['id'])
        self.assertEqual(ipaddress['tenant_id'], tenant_id)
        self.assertEqual(ipaddress['address_readable'], '::ffff:192.168.10.0')
        self.assertEqual(ipaddress['address'],
                         int(netaddr.IPAddress('::ffff:192.168.10.0')))
        self.assertEqual(ipaddress['subnet_id'], subnet['id'])
        self.assertEqual(ipaddress['network_id'], net['id'])
        self.assertEqual(ipaddress['version'], 4)
        self.assertFalse(ipaddress['deallocated'])
        self.assertIsNone(ipaddress['deallocated_at'])
        self.assertEqual(len(ipaddress['ports']), 0)
        self.context.session.add(ipaddress)
        self.context.session.flush()

        ipaddress2 = self.ipam.allocate_ip_address(self.context.session,
                                                   net['id'],
                                                   port['id'],
                                                   tenant_id,
                                                   reuse_after)
        self.assertIsNone(ipaddress2['id'])
        self.assertEqual(ipaddress2['tenant_id'], tenant_id)
        self.assertEqual(ipaddress2['address_readable'], '::ffff:192.168.10.1')
        self.assertEqual(ipaddress2['address'],
                         int(netaddr.IPAddress('::ffff:192.168.10.1')))
        self.assertEqual(ipaddress2['subnet_id'], subnet['id'])
        self.assertEqual(ipaddress2['network_id'], net['id'])
        self.assertEqual(ipaddress2['version'], 4)
        self.assertFalse(ipaddress2['deallocated'])
        self.assertIsNone(ipaddress2['deallocated_at'])
        self.assertEqual(len(ipaddress['ports']), 0)

    def test_deallocate_ip_address_success_one_port(self):
        tenant_id = 'foobar'
        reuse_after = 0

        self._create_and_insert_net()
        net = self.context.session.query(models.Network).first()

        self._create_and_insert_subnet(net['id'])
        subnet = self.context.session.query(models.Subnet).first()

        self._create_and_insert_port(net['id'])
        port = self.context.session.query(models.Port).first()

        self._create_and_insert_ip([port], subnet['id'], net['id'])

        self.ipam.deallocate_ip_address(self.context.session,
                                        port['id'])
        self.context.session.flush()

        ipaddress = self.context.session.query(models.IPAddress).first()
        self.assertTrue(ipaddress['deallocated'])
        self.assertEqual(len(ipaddress['ports']), 0)

    def test_deallocate_ip_address_success_two_ports(self):
        tenant_id = 'foobar'
        reuse_after = 0

        self._create_and_insert_net()
        net = self.context.session.query(models.Network).first()

        self._create_and_insert_subnet(net['id'])
        subnet = self.context.session.query(models.Subnet).first()

        self._create_and_insert_port(net['id'], id='123')
        self._create_and_insert_port(net['id'], id='456')
        ports = self.context.session.query(models.Port).all()

        self._create_and_insert_ip(ports, subnet['id'], net['id'])

        self.ipam.deallocate_ip_address(self.context.session,
                                        ports[0]['id'])
        self.context.session.flush()

        ipaddress = self.context.session.query(models.IPAddress).first()
        self.assertFalse(ipaddress['deallocated'])
        self.assertIsNotNone(ipaddress['ports'])

    def test_deallocate_ip_address_failure(self):
        port_id = 'abc'
        with self.assertRaises(exceptions.NotFound):
            self.ipam.deallocate_ip_address(self.context.session,
                                            port_id)