# -*- coding: utf-8 -*-
#
# Copyright 2014, 2017 Red Hat, Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301 USA
#
# Refer to the README and COPYING files for full details of the license
#
from __future__ import absolute_import

import functools
import os
from os import EX_OK
import re

import pytest

from lago import utils, ssh
from ost_utils.pytest import order_by
from ost_utils.pytest.fixtures import api_v4
from ost_utils.pytest.fixtures import prefix
from ovirtlago import testlib

import ovirtsdk4.types as types

import test_utils
from test_utils import versioning
from test_utils import host_status_utils
from test_utils import constants

import time
import uuid


MB = 2 ** 20
GB = 2 ** 30

DC_NAME = 'test-dc'
TEST_CLUSTER = 'test-cluster'
TEMPLATE_CENTOS7 = 'centos7_template'
TEMPLATE_GUEST = versioning.guest_os_template_name()

SD_NFS_NAME = 'nfs'
SD_SECOND_NFS_NAME = 'second-nfs'
SD_ISCSI_NAME = 'iscsi'

VM_USER_NAME = 'root'
VM_PASSWORD = 'secret'

VM0_NAME = 'vm0'
VM1_NAME = 'vm1'
VM2_NAME = 'vm2'
BACKUP_VM_NAME = 'backup_vm'
IMPORTED_VM_NAME = 'imported_vm'
OVF_VM_NAME = 'ovf_vm'
VMPOOL_NAME = 'test-pool'
DISK0_NAME = '%s_disk0' % VM0_NAME
DISK1_NAME = '%s_disk1' % VM1_NAME
DISK2_NAME = '%s_disk2' % VM2_NAME
BACKUP_DISK_NAME = '%s_disk' % BACKUP_VM_NAME
GLANCE_DISK_NAME = versioning.guest_os_glance_disk_name()

SD_TEMPLATES_NAME = 'templates'

VM_NETWORK = u'VM Network with a very long name and עברית'

SNAPSHOT_DESC_1 = 'dead_snap1'
SNAPSHOT_DESC_2 = 'dead_snap2'
SNAPSHOT_FOR_BACKUP_VM = 'backup_snapshot'
SNAPSHOT_DESC_MEM = 'memory_snap'

VDSM_LOG = '/var/log/vdsm/vdsm.log'


_TEST_LIST = [
    "test_verify_add_all_hosts",
    "test_verify_glance_import",
    "test_reconstruct_master_domain",
    "test_add_vm1_from_template",
    "test_verify_add_vm1_from_template",
    "test_add_disks",
    "test_add_snapshot_for_backup",
    "test_run_vms",
    "test_attach_snapshot_to_backup_vm",
    "test_verify_transient_folder",
    "test_remove_backup_vm_and_backup_snapshot",
    "test_vm0_is_alive",
    "test_suspend_resume_vm0",
    "test_extend_disk1",
    "test_sparsify_disk1",
    "test_export_vm1",
    "test_verify_backup_snapshot_removed",
    "test_verify_vm2_run",
    "test_ha_recovery",
    "test_verify_vm1_exported",
    "test_import_vm_as_clone",
    "test_template_export",
    "test_template_update",
    "test_verify_vm_import",
    "test_verify_suspend_resume_vm0",
    "test_hotplug_memory",
    "test_hotplug_disk",
    "test_hotplug_nic",
    "test_hotplug_cpu",
    "test_next_run_unplug_cpu",
    "test_disk_operations",
    "test_live_storage_migration",
    "test_remove_vm2_lease",
    "test_hotunplug_disk",
    "test_make_snapshot_with_memory",
    "test_add_vm_pool",
    "test_preview_snapshot_with_memory",
    "test_update_template_version",
    "test_update_vm_pool",
    "test_remove_vm_pool",
    "test_check_snapshot_with_memory",
    "test_ovf_import",
    "test_vdsm_recovery",
]


@order_by(_TEST_LIST)
def test_verify_add_all_hosts(prefix):
    api = prefix.virt_env.engine_vm().get_api_v4()
    hosts_service = api.system_service().hosts_service()
    total_hosts = len(hosts_service.list(search='datacenter={}'.format(DC_NAME)))

    testlib.assert_true_within(
        lambda: host_status_utils._all_hosts_up(hosts_service, total_hosts),
        timeout=constants.ADD_HOST_TIMEOUT
    )


def _ping(ovirt_prefix, destination):
    """
    Ping a given destination.
    """
    host = ovirt_prefix.virt_env.host_vms()[0]
    cmd = ['ping', '-4', '-c', '1']
    ret = host.ssh(cmd + [destination])
    return ret.code


def _vm_host(prefix, vm_name):
    engine = prefix.virt_env.engine_vm().get_api_v4().system_service()
    vm_service = test_utils.get_vm_service(engine, vm_name)
    host_id = vm_service.get().host.id
    host_name = engine.hosts_service().host_service(host_id).get().name
    return prefix.virt_env.get_vm(host_name)


def _verify_vm_state(engine, vm_name, state):
    vm_service = test_utils.get_vm_service(engine, vm_name)
    testlib.assert_true_within_long(
        lambda:
        vm_service.get().status == state
    )
    return vm_service


def _vm_ssh(ip_address, command, tries=None):
    return ssh.ssh(
        ip_addr=ip_address,
        command=command,
        username=VM_USER_NAME,
        password=VM_PASSWORD,
        tries=tries,
    )


def assert_vm0_is_alive(prefix):
    assert_vm_is_alive(prefix, test_utils.get_vm0_ip_address(prefix))


def assert_vm_is_alive(prefix, ip_address):
    testlib.assert_true_within_short(
        lambda:
        _ping(prefix, ip_address) == EX_OK
    )
    assert _vm_ssh(ip_address, ['true']).code == EX_OK


@order_by(_TEST_LIST)
def test_add_disks(api_v4):
    engine = api_v4.system_service()
    vm_service = test_utils.get_vm_service(engine, VM0_NAME)
    glance_disk = test_utils.get_disk_service(engine, GLANCE_DISK_NAME)
    assert vm_service and glance_disk

    vm0_disk_attachments_service = test_utils.get_disk_attachments_service(engine, VM0_NAME)

    vm0_disk_attachments_service.add(
        types.DiskAttachment(
            disk=types.Disk(
                id=glance_disk.get().id,
                storage_domains=[
                    types.StorageDomain(
                        name=SD_ISCSI_NAME,
                    ),
                ],
            ),
            interface=types.DiskInterface.VIRTIO,
            active=True,
            bootable=True,
        ),
    )

    disk_params = types.Disk(
        provisioned_size=1 * GB,
        format=types.DiskFormat.COW,
        status=None,
        sparse=True,
        active=True,
        bootable=True,
    )

    for vm_name, disk_name, sd_name in (
            (VM1_NAME, DISK1_NAME, SD_NFS_NAME),
            (VM2_NAME, DISK2_NAME, SD_SECOND_NFS_NAME),
            (BACKUP_VM_NAME, BACKUP_DISK_NAME, SD_NFS_NAME)):
        disk_params.name = disk_name
        disk_params.storage_domains = [
            types.StorageDomain(
                name=sd_name,
            )
        ]

        disk_attachments_service = test_utils.get_disk_attachments_service(engine, vm_name)
        assert disk_attachments_service.add(types.DiskAttachment(
            disk=disk_params,
            interface=types.DiskInterface.VIRTIO))

    for disk_name in (GLANCE_DISK_NAME, DISK1_NAME, DISK2_NAME, BACKUP_DISK_NAME):
        disk_service = test_utils.get_disk_service(engine, disk_name)
        testlib.assert_true_within_short(
            lambda:
            disk_service.get().status == types.DiskStatus.OK
        )
    # USER_ADD_DISK_TO_VM_FINISHED_SUCCESS event
    # test_utils.test_for_event(engine, 97, last_event)


@order_by(_TEST_LIST)
def test_extend_disk1(api_v4):
    engine = api_v4.system_service()
    disk_attachments_service = test_utils.get_disk_attachments_service(engine, VM1_NAME)
    for disk_attachment in disk_attachments_service.list():
        disk = api_v4.follow_link(disk_attachment.disk)
        if disk.name == DISK1_NAME:
            attachment_service = disk_attachments_service.attachment_service(disk_attachment.id)
    with test_utils.TestEvent(engine, 371): # USER_EXTEND_DISK_SIZE_SUCCESS(371)
       attachment_service.update(
                types.DiskAttachment(
                    disk=types.Disk(provisioned_size=2 * GB,)))

       disk_service = test_utils.get_disk_service(engine, DISK1_NAME)
       testlib.assert_true_within_short(
           lambda:
           disk_service.get().status == types.DiskStatus.OK
       )
       testlib.assert_true_within_short(
           lambda:
           disk_service.get().provisioned_size == 2 * GB
       )


@order_by(_TEST_LIST)
def test_sparsify_disk1(api_v4):
    engine = api_v4.system_service()
    disk_service = test_utils.get_disk_service(engine, DISK1_NAME)
    with test_utils.TestEvent(engine, 1325): # USER_SPARSIFY_IMAGE_START event
        disk_service.sparsify()

    testlib.assert_true_within_short(
        lambda:
        disk_service.get().status == types.DiskStatus.OK
    )
    # USER_SPARSIFY_IMAGE_FINISH_SUCCESS event
    # TODO: enable - sparsify sometimes fails.
    # test_utils.test_for_event(engine, 1326, last_event)


@order_by(_TEST_LIST)
def test_add_snapshot_for_backup(api_v4):
    engine = api_v4.system_service()

    vm2_disk_attachments_service = test_utils.get_disk_attachments_service(engine, VM2_NAME)
    disk = vm2_disk_attachments_service.list()[0]

    backup_snapshot_params = types.Snapshot(
        description=SNAPSHOT_FOR_BACKUP_VM,
        persist_memorystate=False,
        disk_attachments=[
            types.DiskAttachment(
                disk=types.Disk(
                    id=disk.id
                )
            )
        ]
    )

    vm2_snapshots_service = test_utils.get_vm_snapshots_service(engine, VM2_NAME)

    correlation_id = uuid.uuid4()
    with test_utils.TestEvent(engine, [45, 68]):
        # USER_CREATE_SNAPSHOT(41) event
        # USER_CREATE_SNAPSHOT_FINISHED_SUCCESS(68) event
        vm2_snapshots_service.add(backup_snapshot_params,
                                  query={'correlation_id': correlation_id})

        testlib.assert_true_within_long(
            lambda:
            test_utils.all_jobs_finished(engine, correlation_id)
        )
        testlib.assert_true_within_long(
            lambda:
            vm2_snapshots_service.list()[-1].snapshot_status == types.SnapshotStatus.OK,
        )


@order_by(_TEST_LIST)
def test_attach_snapshot_to_backup_vm(api_v4):
    engine = api_v4.system_service()
    vm2_snapshots_service = test_utils.get_vm_snapshots_service(engine, VM2_NAME)
    vm2_disk_attachments_service = test_utils.get_disk_attachments_service(engine, VM2_NAME)
    vm2_disk = vm2_disk_attachments_service.list()[0]
    disk_attachments_service = test_utils.get_disk_attachments_service(engine, BACKUP_VM_NAME)

    with test_utils.TestEvent(engine, 2016): # USER_ATTACH_DISK_TO_VM event
        disk_attachments_service.add(
            types.DiskAttachment(
                disk=types.Disk(
                    id=vm2_disk.id,
                    snapshot=types.Snapshot(
                        id=vm2_snapshots_service.list()[-1].id
                    )
                ),
                interface=types.DiskInterface.VIRTIO_SCSI,
                bootable=False,
                active=True
            )
        )
        assert len(disk_attachments_service.list()) > 0

@order_by(_TEST_LIST)
def test_verify_transient_folder(prefix):
    engine = prefix.virt_env.engine_vm().get_api_v4().system_service()
    sd = engine.storage_domains_service().list(search='name={}'.format(SD_SECOND_NFS_NAME))[0]
    host = _vm_host(prefix, BACKUP_VM_NAME)

    ret = host.ssh(['ls', '/var/lib/vdsm/transient'])
    assert ret.code == 0

    all_volumes = ret.out.decode('utf-8').splitlines()
    assert len(all_volumes) == 1

    assert sd.id in all_volumes[0]
    assert_vm0_is_alive(prefix)


@order_by(_TEST_LIST)
def test_remove_backup_vm_and_backup_snapshot(api_v4):
    engine = api_v4.system_service()
    backup_vm_service = test_utils.get_vm_service(engine, BACKUP_VM_NAME)
    vm2_snapshots_service = test_utils.get_vm_snapshots_service(engine, VM2_NAME)
    vm2_snapshot = vm2_snapshots_service.list()[-1]
    # power-off backup-vm
    with test_utils.TestEvent(engine, [33, 61]):
        # VM_DOWN(61) event
        # USER_STOP_VM(33) event
        backup_vm_service.stop()
        testlib.assert_true_within_long(
            lambda:
            backup_vm_service.get().status == types.VmStatus.DOWN
        )
    # remove backup_vm
    num_of_vms = len(engine.vms_service().list())
    backup_vm_service.remove()
    assert len(engine.vms_service().list()) == (num_of_vms-1)
    with test_utils.TestEvent(engine, 342): # USER_REMOVE_SNAPSHOT event
        # remove vm2 snapshot
        vm2_snapshots_service.snapshot_service(vm2_snapshot.id).remove()


@order_by(_TEST_LIST)
def test_verify_backup_snapshot_removed(api_v4):
    engine = api_v4.system_service()
    vm2_snapshots_service = test_utils.get_vm_snapshots_service(engine, VM2_NAME)

    testlib.assert_true_within_long(
        lambda: len(vm2_snapshots_service.list()) == 1
    )


def snapshot_cold_merge(api_v4):
    engine = api_v4.system_service()
    vm1_snapshots_service = test_utils.get_vm_snapshots_service(engine, VM1_NAME)
    if vm1_snapshots_service is None:
        pytest.skip('Glance is not available')

    disk = engine.disks_service().list(search='name={}'.format(DISK1_NAME))[0]

    dead_snap1_params = types.Snapshot(
        description=SNAPSHOT_DESC_1,
        persist_memorystate=False,
        disk_attachments=[
            types.DiskAttachment(
                disk=types.Disk(
                    id=disk.id
                )
            )
        ]
    )
    correlation_id = uuid.uuid4()

    vm1_snapshots_service.add(dead_snap1_params,
                              query={'correlation_id': correlation_id})

    testlib.assert_true_within_long(
        lambda:
        test_utils.all_jobs_finished(engine, correlation_id)
    )
    testlib.assert_true_within_long(
        lambda:
        vm1_snapshots_service.list()[-1].snapshot_status == types.SnapshotStatus.OK
    )

    dead_snap2_params = types.Snapshot(
        description=SNAPSHOT_DESC_2,
        persist_memorystate=False,
        disk_attachments=[
            types.DiskAttachment(
                disk=types.Disk(
                    id=disk.id
                )
            )
        ]
    )
    correlation_id_snap2 = uuid.uuid4()

    vm1_snapshots_service.add(dead_snap2_params,
                              query={'correlation_id': correlation_id_snap2})

    testlib.assert_true_within_long(
        lambda:
        test_utils.all_jobs_finished(engine, correlation_id_snap2)
    )
    testlib.assert_true_within_long(
        lambda:
        vm1_snapshots_service.list()[-1].snapshot_status == types.SnapshotStatus.OK
    )

    snapshot = vm1_snapshots_service.list()[-2]
    vm1_snapshots_service.snapshot_service(snapshot.id).remove()

    testlib.assert_true_within_long(
        lambda:
        len(vm1_snapshots_service.list()) == 2
    )
    testlib.assert_true_within_long(
        lambda:
        vm1_snapshots_service.list()[-1].snapshot_status == types.SnapshotStatus.OK
    )


@order_by(_TEST_LIST)
def test_make_snapshot_with_memory(api_v4):
    engine = api_v4.system_service()
    vm_service = test_utils.get_vm_service(engine, VM0_NAME)
    disks_service = engine.disks_service()
    vm_disks_service = \
        test_utils.get_disk_attachments_service(engine, VM0_NAME)
    vm_disks = [disks_service.disk_service(attachment.disk.id).get()
                for attachment in vm_disks_service.list()]
    disk_attachments = [types.DiskAttachment(disk=types.Disk(id=disk.id))
                        for disk in vm_disks
                        if disk.storage_type != types.DiskStorageType.LUN]
    snapshots_service = vm_service.snapshots_service()
    snapshot_params = types.Snapshot(
        description=SNAPSHOT_DESC_MEM,
        persist_memorystate=True,
        disk_attachments=disk_attachments
    )
    with test_utils.TestEvent(engine, 45):  # USER_CREATE_SNAPSHOT event
        snapshots_service.add(snapshot_params)


@order_by(_TEST_LIST)
def test_preview_snapshot_with_memory(api_v4):
    engine = api_v4.system_service()
    events = engine.events_service()
    testlib.assert_true_within_long(
        # wait for event 68 == USER_CREATE_SNAPSHOT_FINISHED_SUCCESS
        lambda: any(e.code == 68 for e in events.list(max=6))
    )
    vm_service = test_utils.get_vm_service(engine, VM0_NAME)
    vm_service.stop()
    _verify_vm_state(engine, VM0_NAME, types.VmStatus.DOWN)
    snapshot = test_utils.get_snapshot(engine, VM0_NAME, SNAPSHOT_DESC_MEM)
    vm_service.preview_snapshot(snapshot=snapshot, async=False,
                                restore_memory=True)


@order_by(_TEST_LIST)
def test_check_snapshot_with_memory(api_v4):
    engine = api_v4.system_service()
    vm_service = test_utils.get_vm_service(engine, VM0_NAME)
    testlib.assert_true_within_long(
        lambda: test_utils.get_snapshot(engine, VM0_NAME,
                                        SNAPSHOT_DESC_MEM).snapshot_status ==
        types.SnapshotStatus.IN_PREVIEW
    )
    vm_service.start()
    _verify_vm_state(engine, VM0_NAME, types.VmStatus.UP)


def cold_storage_migration(api_v4):
    engine = api_v4.system_service()
    disk_service = test_utils.get_disk_service(engine, DISK2_NAME)

    # Cold migrate the disk to ISCSI storage domain and then migrate it back
    # to the NFS domain because it is used by other cases that assume the
    # disk found on that specific domain
    for domain in [SD_ISCSI_NAME, SD_SECOND_NFS_NAME]:
        with test_utils.TestEvent(engine, 2008): # USER_MOVED_DISK(2,008)
            disk_service.move(
                async=False,
                storage_domain=types.StorageDomain(
                    name=domain
                )
            )

            testlib.assert_true_within_long(
                lambda: api_v4.follow_link(
                    disk_service.get().storage_domains[0]).name == domain
            )
            testlib.assert_true_within_long(
                lambda:
                disk_service.get().status == types.DiskStatus.OK
            )


@order_by(_TEST_LIST)
def test_live_storage_migration(api_v4):
    pytest.skip("TODO: el8 fails all the time")

    engine = api_v4.system_service()
    disk_service = test_utils.get_disk_service(engine, DISK0_NAME)
    correlation_id = 'live_storage_migration'
    disk_service.move(
        async=False,
        filter=False,
        storage_domain=types.StorageDomain(
            name=SD_ISCSI_NAME
        ),
        query={'correlation_id': correlation_id}
    )

    testlib.assert_true_within_long(lambda: test_utils.all_jobs_finished(engine, correlation_id))

    # Assert that the disk is on the correct storage domain,
    # its status is OK and the snapshot created for the migration
    # has been merged
    testlib.assert_true_within_long(
        lambda: api_v4.follow_link(disk_service.get().storage_domains[0]).name == SD_ISCSI_NAME
    )

    vm0_snapshots_service = test_utils.get_vm_snapshots_service(engine, VM0_NAME)
    testlib.assert_true_within_long(
        lambda: len(vm0_snapshots_service.list()) == 1
    )
    testlib.assert_true_within_long(
        lambda: disk_service.get().status == types.DiskStatus.OK
    )

@order_by(_TEST_LIST)
def test_export_vm1(api_v4):
    engine = api_v4.system_service()
    vm_service = test_utils.get_vm_service(engine, VM1_NAME)
    sd = engine.storage_domains_service().list(search='name={}'.format(SD_TEMPLATES_NAME))[0]

    with test_utils.TestEvent(engine, 1162): # IMPORTEXPORT_STARTING_EXPORT_VM event
        vm_service.export(
            storage_domain=types.StorageDomain(
                id=sd.id,
            ), discard_snapshots=True, async=True
        )


@order_by(_TEST_LIST)
def test_verify_vm1_exported(api_v4):
    engine = api_v4.system_service()
    _verify_vm_state(engine, VM1_NAME, types.VmStatus.DOWN)

    storage_domain_service = test_utils.get_storage_domain_service(engine, SD_TEMPLATES_NAME)
    vm_sd_service = test_utils.get_storage_domain_vm_service_by_name(
        storage_domain_service, VM1_NAME)
    testlib.assert_true_within_short(
        lambda:
        vm_sd_service.get().status == types.VmStatus.DOWN
    )


@order_by(_TEST_LIST)
def test_import_vm_as_clone(api_v4):
    engine = api_v4.system_service()
    storage_domain_service = test_utils.get_storage_domain_service(engine, SD_TEMPLATES_NAME)
    vm_to_import = test_utils.get_storage_domain_vm_service_by_name(storage_domain_service, VM1_NAME)

    if vm_to_import is None:
        pytest.skip("VM: '%s' not found on export domain: '%s'" % (VM1_NAME, SD_TEMPLATES_NAME))

    with test_utils.TestEvent(engine, 1165): # IMPORTEXPORT_STARTING_IMPORT_VM event
        vm_to_import.import_(
            storage_domain=types.StorageDomain(
                name=SD_ISCSI_NAME,
            ),
            cluster=types.Cluster(
                name=TEST_CLUSTER,
            ),
            vm=types.Vm(
                name=IMPORTED_VM_NAME,
            ),
            clone=True, collapse_snapshots=True, async=True
        )


@order_by(_TEST_LIST)
def test_verify_vm_import(api_v4):
    engine = api_v4.system_service()
    vm_service = _verify_vm_state(engine, IMPORTED_VM_NAME, types.VmStatus.DOWN)

    # Remove the imported VM
    num_of_vms = len(engine.vms_service().list())
    vm_service.remove()
    assert len(engine.vms_service().list()) == (num_of_vms-1)


@order_by(_TEST_LIST)
def test_add_vm1_from_template(api_v4):
    engine = api_v4.system_service()
    templates_service = engine.templates_service()
    glance_template = templates_service.list(search='name=%s' % TEMPLATE_GUEST)[0]
    if glance_template is None:
        pytest.skip('%s: template %s not available.' % (add_vm1_from_template.__name__, TEMPLATE_GUEST))

    vm_memory = 512 * MB
    vms_service = engine.vms_service()
    vms_service.add(
        types.Vm(
            name=VM1_NAME,
            description='CirrOS imported from Glance as Template',
            memory= 512 * MB,
            cluster=types.Cluster(
                name=TEST_CLUSTER,
            ),
            template=types.Template(
                name=TEMPLATE_GUEST,
            ),
            use_latest_template_version=True,
            stateless=True,
            display=types.Display(
                type=types.DisplayType.VNC,
            ),
            memory_policy=types.MemoryPolicy(
                guaranteed=vm_memory // 2,
                ballooning=False,
            ),
            os=types.OperatingSystem(
                type='rhel_7x64',
            ),
            time_zone=types.TimeZone(
                name='Etc/GMT',
            ),
            type=types.VmType.SERVER,
            serial_number=types.SerialNumber(
                policy=types.SerialNumberPolicy.CUSTOM,
                value='12345678',
            ),
            cpu=types.Cpu(
                architecture=types.Architecture.X86_64,
                topology=types.CpuTopology(
                    sockets=1,
                    cores=1,
                    threads=2,
                ),
            ),
        )
    )


@order_by(_TEST_LIST)
def test_verify_add_vm1_from_template(api_v4):
    engine = api_v4.system_service()
    _verify_vm_state(engine, VM1_NAME, types.VmStatus.DOWN)

    disks_service = engine.disks_service()
    vm1_disk_attachments_service = test_utils.get_disk_attachments_service(engine, VM1_NAME)
    for disk_attachment in vm1_disk_attachments_service.list():
        disk_service = disks_service.disk_service(disk_attachment.disk.id)
        testlib.assert_true_within_short(
            lambda:
            disk_service.get().status == types.DiskStatus.OK
        )


@order_by(_TEST_LIST)
def test_run_vms(prefix):
    engine = prefix.virt_env.engine_vm().get_api_v4().system_service()

    vm_params = types.Vm(
        initialization=types.Initialization(
            user_name=VM_USER_NAME,
            root_password=VM_PASSWORD
        )
    )

    vm_params.initialization.host_name = BACKUP_VM_NAME
    backup_vm_service = test_utils.get_vm_service(engine, BACKUP_VM_NAME)
    backup_vm_service.start(use_cloud_init=True, vm=vm_params)

    vm_params.initialization.host_name = VM2_NAME
    vm2_service = test_utils.get_vm_service(engine, VM2_NAME)
    vm2_service.start(use_cloud_init=True, vm=vm_params)

    gw_ip = test_utils.get_management_net(prefix).gw()

    vm_params.initialization.host_name = VM0_NAME
    vm_params.initialization.dns_search = 'lago.local'
    vm_params.initialization.domain = 'lago.local'
    vm_params.initialization.dns_servers = gw_ip
    vm_params.initialization.nic_configurations = [
        types.NicConfiguration(
            name='eth0',
            boot_protocol=types.BootProtocol.STATIC,
            on_boot=True,
            ip=types.Ip(
                address=test_utils.get_vm0_ip_address(prefix),
                netmask='255.255.255.0',
                gateway=gw_ip
            )
        )
    ]
    vm0_service = test_utils.get_vm_service(engine, VM0_NAME)
    vm0_service.start(use_cloud_init=True, vm=vm_params)

    for vm_name in [VM0_NAME, BACKUP_VM_NAME]:
        _verify_vm_state(engine, vm_name, types.VmStatus.UP)

    assert_vm0_is_alive(prefix)


@order_by(_TEST_LIST)
def test_verify_vm2_run(api_v4):
    _verify_vm_state(api_v4.system_service(), VM2_NAME, types.VmStatus.UP)


@order_by(_TEST_LIST)
def test_vm0_is_alive(prefix):
    assert_vm0_is_alive(prefix)


@order_by(_TEST_LIST)
def test_ha_recovery(prefix):
    engine = prefix.virt_env.engine_vm().get_api_v4().system_service()
    with test_utils.TestEvent(engine, [119, 9602, 506]):
        # VM_DOWN_ERROR event(119)
        # HA_VM_FAILED event event(9602)
        # VDS_INITIATED_RUN_VM event(506)
        vm_host = _vm_host(prefix, VM2_NAME)
        pid = vm_host.ssh(['pgrep', '-f', 'qemu.*guest=vm2'])
        vm_host.ssh(['kill', '-KILL', pid.out.decode('utf-8')])

    vm_service = test_utils.get_vm_service(engine, VM2_NAME)
    testlib.assert_true_within_long(
        lambda:
        vm_service.get().status == types.VmStatus.UP
    )
    with test_utils.TestEvent(engine, 33): # USER_STOP_VM event
        vm_service.stop()


@order_by(_TEST_LIST)
def test_vdsm_recovery(prefix):
    engine = prefix.virt_env.engine_vm().get_api_v4().system_service()
    vm_service = test_utils.get_vm_service(engine, VM0_NAME)
    host_id = vm_service.get().host.id
    host_service = engine.hosts_service().host_service(host_id)
    host_name = host_service.get().name
    vm_host = prefix.virt_env.get_vm(host_name)

    vm_host.service('vdsmd').stop()
    testlib.assert_true_within_short(
        lambda:
        vm_service.get().status == types.VmStatus.UNKNOWN
    )

    vm_host.service('vdsmd').start()
    testlib.assert_true_within_short(
        lambda:
        host_service.get().status == types.HostStatus.UP
    )
    testlib.assert_true_within_short(
        lambda:
        vm_service.get().status == types.VmStatus.UP
    )


@order_by(_TEST_LIST)
def test_template_export(api_v4):
    engine = api_v4.system_service()

    template_guest = test_utils.get_template_service(engine, TEMPLATE_GUEST)
    if template_guest is None:
        pytest.skip('{0}: template {1} is missing'.format(
            template_export.__name__,
            TEMPLATE_GUEST
            )
        )

    storage_domain = engine.storage_domains_service().list(search='name={}'.format(SD_TEMPLATES_NAME))[0]
    with test_utils.TestEvent(engine, 1164):
        # IMPORTEXPORT_STARTING_EXPORT_TEMPLATE event
        template_guest.export(
            storage_domain=types.StorageDomain(
                id=storage_domain.id,
            ),
        )

    with test_utils.TestEvent(engine, 1156):
        # IMPORTEXPORT_EXPORT_TEMPLATE event
        testlib.assert_true_within_long(
            lambda:
            template_guest.get().status == types.TemplateStatus.OK,
        )


@order_by(_TEST_LIST)
def test_add_vm_pool(api_v4):
    engine = api_v4.system_service()
    pools_service = engine.vm_pools_service()
    pool_cluster = engine.clusters_service().list(search='name={}'.format(TEST_CLUSTER))[0]
    pool_template = engine.templates_service().list(search='name={}'.format(TEMPLATE_GUEST))[0]
    with test_utils.TestEvent(engine, 302):
        pools_service.add(
            pool=types.VmPool(
                name=VMPOOL_NAME,
                cluster=pool_cluster,
                template=pool_template,
                use_latest_template_version=True,
            )
        )
    vm_service = test_utils.get_vm_service(engine, VMPOOL_NAME+'-1')
    testlib.assert_true_within_short(
        lambda:
        vm_service.get().status == types.VmStatus.DOWN,
        allowed_exceptions=[IndexError]
    )


@order_by(_TEST_LIST)
def test_update_template_version(api_v4):
    engine = api_v4.system_service()
    stateless_vm = engine.vms_service().list(search='name={}'.format(VM1_NAME))[0]
    templates_service = engine.templates_service()
    template = templates_service.list(search='name={}'.format(TEMPLATE_GUEST))[0]

    assert stateless_vm.memory != template.memory

    templates_service.add(
        template=types.Template(
            name=TEMPLATE_GUEST,
            vm=stateless_vm,
            version=types.TemplateVersion(
                base_template=template,
                version_number=2
            )
        )
    )
    pool_service = test_utils.get_pool_service(engine, VMPOOL_NAME)
    testlib.assert_true_within_long(
        lambda:
        pool_service.get().vm.memory == stateless_vm.memory
    )


@order_by(_TEST_LIST)
def test_update_vm_pool(api_v4):
    engine = api_v4.system_service()
    pool_service = test_utils.get_pool_service(engine, VMPOOL_NAME)
    correlation_id = uuid.uuid4()
    pool_service.update(
        pool=types.VmPool(
            max_user_vms=2
        ),
        query={'correlation_id': correlation_id}
    )
    assert pool_service.get().max_user_vms == 2
    testlib.assert_true_within_long(
        lambda:
        test_utils.all_jobs_finished(engine, correlation_id)
    )


@versioning.require_version(4, 1)
@order_by(_TEST_LIST)
def test_remove_vm2_lease(api_v4):
    engine = api_v4.system_service()
    vm2_service = test_utils.get_vm_service(engine, VM2_NAME)

    vm2_service.update(
        vm=types.Vm(
            high_availability=types.HighAvailability(
                enabled=False,
            ),
            lease=types.StorageDomainLease(
                storage_domain=None
            )
        )
    )
    testlib.assert_true_within_short(
        lambda:
        vm2_service.get().lease is None
    )


@order_by(_TEST_LIST)
def test_remove_vm_pool(api_v4):
    engine = api_v4.system_service()
    pool_service = test_utils.get_pool_service(engine, VMPOOL_NAME)
    correlation_id = uuid.uuid4()
    with test_utils.TestEvent(engine, [321, 304]):
        # USER_REMOVE_VM_POOL_INITIATED(321) event
        # USER_REMOVE_VM_POOL(304) event
        pool_service.remove(query={'correlation_id': correlation_id})
        vm_pools_service = api_v4.system_service().vm_pools_service()
        assert len(vm_pools_service.list()) == 0
    testlib.assert_true_within_long(
        lambda:
        test_utils.all_jobs_finished(engine, correlation_id)
    )


@order_by(_TEST_LIST)
def test_template_update(api_v4):
    template_guest = test_utils.get_template_service(api_v4.system_service(), TEMPLATE_GUEST)

    if template_guest is None:
        pytest.skip('{0}: template {1} is missing'.format(
            template_update.__name__,
            TEMPLATE_GUEST
        )
    )
    new_comment = "comment by ovirt-system-tests"
    template_guest.update(
        template = types.Template(
            comment=new_comment
        )
    )
    testlib.assert_true_within_short(
        lambda:
        template_guest.get().status == types.TemplateStatus.OK
    )
    assert template_guest.get().comment == new_comment


@order_by(_TEST_LIST)
def test_disk_operations(api_v4):
    vt = utils.VectorThread(
        [
            functools.partial(cold_storage_migration, api_v4),
            functools.partial(snapshot_cold_merge, api_v4),
        ],
    )
    vt.start_all()
    vt.join_all()


@order_by(_TEST_LIST)
def test_hotplug_memory(prefix):
    api_v4 = prefix.virt_env.engine_vm().get_api_v4()
    engine = api_v4.system_service()
    vm_service = test_utils.get_vm_service(engine, VM0_NAME)
    new_memory = vm_service.get().memory + 256 * MB
    with test_utils.TestEvent(engine, 2039): # HOT_SET_MEMORY(2,039)
        vm_service.update(
            vm=types.Vm(
                memory=new_memory
            )
        )
        assert vm_service.get().memory == new_memory
    assert_vm0_is_alive(prefix)


@order_by(_TEST_LIST)
def test_hotplug_cpu(prefix):
    api_v4 = prefix.virt_env.engine_vm().get_api_v4()
    engine = api_v4.system_service()
    vm_service = test_utils.get_vm_service(engine, VM0_NAME)
    new_cpu = vm_service.get().cpu
    new_cpu.topology.sockets = 2
    with test_utils.TestEvent(engine, 2033): # HOT_SET_NUMBER_OF_CPUS(2,033)
        vm_service.update(
            vm=types.Vm(
                cpu=new_cpu
            )
        )
        assert vm_service.get().cpu.topology.sockets == 2
    ret = _vm_ssh(test_utils.get_vm0_ip_address(prefix), ['lscpu'])
    assert ret.code == 0
    match = re.search(r'CPU\(s\):\s+(?P<cpus>[0-9]+)', ret.out.decode('utf-8'))
    assert match.group('cpus') == '2'


@order_by(_TEST_LIST)
def test_next_run_unplug_cpu(api_v4):
    engine = api_v4.system_service()
    vm_service = test_utils.get_vm_service(engine, VM0_NAME)
    new_cpu = vm_service.get().cpu
    new_cpu.topology.sockets = 1
    vm_service.update(
        vm=types.Vm(
            cpu=new_cpu,
        ),
        next_run=True
    )
    assert vm_service.get().cpu.topology.sockets == 2
    assert vm_service.get(next_run=True).cpu.topology.sockets == 1

    with test_utils.TestEvent(engine, 157): # USER_REBOOT_VM(157)
        vm_service.reboot()
        testlib.assert_true_within_long(
            lambda:
             vm_service.get().status == types.VmStatus.UP
        )
    assert vm_service.get().cpu.topology.sockets == 1


@order_by(_TEST_LIST)
def test_hotplug_nic(prefix):
    pytest.skip('https://bugzilla.redhat.com/1776317')
    api_v4 = prefix.virt_env.engine_vm().get_api_v4()
    vms_service = api_v4.system_service().vms_service()
    vm = vms_service.list(search='name=%s' % VM0_NAME)[0]
    nics_service = vms_service.vm_service(vm.id).nics_service()
    nics_service.add(
        types.Nic(
            name='eth1',
            interface=types.NicInterface.VIRTIO
        ),
    )
    assert_vm0_is_alive(prefix)


@order_by(_TEST_LIST)
def test_hotplug_disk(prefix):
    api_v4 = prefix.virt_env.engine_vm().get_api_v4()
    engine = api_v4.system_service()
    disk_attachments_service = test_utils.get_disk_attachments_service(engine, VM0_NAME)
    disk_attachment = disk_attachments_service.add(
        types.DiskAttachment(
            disk=types.Disk(
                name=DISK0_NAME,
                provisioned_size=2 * GB,
                format=types.DiskFormat.COW,
                storage_domains=[
                    types.StorageDomain(
                        name=SD_NFS_NAME,
                    ),
                ],
                status=None,
                sparse=True,
            ),
            interface=types.DiskInterface.VIRTIO,
            bootable=False,
            active=True
        )
    )

    disks_service = engine.disks_service()
    disk_service = disks_service.disk_service(disk_attachment.disk.id)
    attachment_service = disk_attachments_service.attachment_service(disk_attachment.id)

    testlib.assert_true_within_short(
        lambda:
        attachment_service.get().active == True
    )
    testlib.assert_true_within_short(
        lambda:
        disk_service.get().status == types.DiskStatus.OK
    )
    assert_vm0_is_alive(prefix)


@order_by(_TEST_LIST)
def test_hotunplug_disk(api_v4):
    engine = api_v4.system_service()
    disk_service = test_utils.get_disk_service(engine, DISK0_NAME)
    disk_attachments_service = test_utils.get_disk_attachments_service(engine, VM0_NAME)
    disk_attachment = disk_attachments_service.attachment_service(disk_service.get().id)

    with test_utils.TestEvent(engine, 2002):
        # USER_HOTUNPLUG_DISK(2,002)
        correlation_id = 'test_hotunplug_disk'
        assert disk_attachment.update(types.DiskAttachment(active=False),
                                      query={'correlation_id': correlation_id})
        testlib.assert_true_within_long(
            lambda:
            test_utils.all_jobs_finished(engine, correlation_id)
        )

        testlib.assert_true_within_short(
            lambda:
            disk_service.get().status == types.DiskStatus.OK
        )

        testlib.assert_true_within_short(
            lambda:
            disk_attachment.get().active == False
        )


_log_time_before_suspend = None


@order_by(_TEST_LIST)
def test_suspend_resume_vm0(prefix):
    vm_host = _vm_host(prefix, VM0_NAME)
    ret = vm_host.ssh(['tail', '-1', VDSM_LOG])
    assert ret.code == EX_OK
    log_items = ret.out.decode('utf-8').split()
    global _log_time_before_suspend
    _log_time_before_suspend = log_items[0] + ' ' + log_items[1]  # date + time

    assert_vm0_is_alive(prefix)

    api_v4 = prefix.virt_env.engine_vm().get_api_v4()
    vm_service = test_utils.get_vm_service(api_v4.system_service(), VM0_NAME)
    vm_service.suspend()
    testlib.assert_true_within_long(
        lambda: vm_service.get().status == types.VmStatus.SUSPENDED
    )

    vm_service.start()


@order_by(_TEST_LIST)
def test_verify_suspend_resume_vm0(prefix):
    api_v4 = prefix.virt_env.engine_vm().get_api_v4()
    _verify_vm_state(api_v4.system_service(), VM0_NAME, types.VmStatus.UP)
    vm_host = _vm_host(prefix, VM0_NAME)

    def log_line_count(regexp):
        awk = ('BEGIN {{ n = 0; }} '
               '$1 " " $2 > "{}" && $0 ~ /{}/ {{ n = n + 1; }} '
               'END {{ print n; }}').format(
                   _log_time_before_suspend, regexp
               )
        ret = vm_host.ssh(['awk', "'" + awk + "'", VDSM_LOG])
        assert ret.code == EX_OK
        return int(ret.out)

    if versioning.cluster_version_ok(4, 2):
        identifier = 'memoryDumpVolume'
    else:
        identifier = 'hiberVolHandle'
    assert log_line_count('START create\(.*' + identifier) == 1
    assert log_line_count('CPU running: onResume') >= 1
    assert_vm0_is_alive(prefix)


@order_by(_TEST_LIST)
def test_verify_glance_import(api_v4):
    for disk_name in (GLANCE_DISK_NAME, TEMPLATE_GUEST):
        disks_service = api_v4.system_service().disks_service()
        testlib.assert_true_within_long(
            lambda: disks_service.list(search='name={}'.format(disk_name))[0].status == types.DiskStatus.OK
        )

@order_by(_TEST_LIST)
def test_reconstruct_master_domain(api_v4):
    pytest.skip('TODO:Handle case where tasks are running')
    system_service = api_v4.system_service()
    dc_service = test_utils.data_center_service(system_service, DC_NAME)
    attached_sds_service = dc_service.storage_domains_service()
    master_sd = next(sd for sd in attached_sds_service.list() if sd.master)
    attached_sd_service = attached_sds_service.storage_domain_service(master_sd.id)
    attached_sd_service.deactivate()
    testlib.assert_true_within_long(
        lambda: attached_sd_service.get().status ==
                types.StorageDomainStatus.MAINTENANCE
        )
    new_master_sd = next(sd for sd in attached_sds_service.list() if sd.master)
    assert new_master_sd.id != master_sd.id
    attached_sd_service.activate()
    testlib.assert_true_within_long(
        lambda: attached_sd_service.get().status ==
                types.StorageDomainStatus.ACTIVE
        )


@order_by(_TEST_LIST)
def test_ovf_import(api_v4):
    # Read the OVF file and replace the disk id
    engine = api_v4.system_service()
    disk_service = test_utils.get_disk_service(engine, DISK0_NAME)
    disk_id = disk_service.get().id
    ovf_file = os.path.join(os.environ['SUITE'], 'files', 'test-vm.ovf')
    ovf_text = open(ovf_file).read()
    ovf_text = ovf_text.replace(
        "ovf:diskId='52df5324-2230-40d9-9d3d-8cbb2aa33ba6'",
        "ovf:diskId='%s'" % (disk_id,)
    )
    # Upload OVF
    vms_service = engine.vms_service()
    vms_service.add(
        types.Vm(
            name=OVF_VM_NAME,
            cluster=types.Cluster(
                name=TEST_CLUSTER,
            ),
            initialization=types.Initialization(
                configuration=types.Configuration(
                    type=types.ConfigurationType.OVA,
                    data=ovf_text
                )
            )
        )
    )
    # Check the VM exists
    assert test_utils.get_vm_service(engine, OVF_VM_NAME) is not None
