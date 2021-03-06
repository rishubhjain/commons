from tendrl.commons.flows.exceptions import FlowExecutionFailedError
from tendrl.commons.flows.expand_cluster import gluster_help
import maps
import mock
from mock import patch
import __builtin__
import importlib
import pytest

'''Unit Test Cases'''

def test_get_node_ips():
    param = maps.NamedDict()
    param["Cluster.node_configuration"] = {"test_node": maps.NamedDict(role="mon",provisioning_ip="test_ip")}
    ret = gluster_help.get_node_ips(param)
    assert ret[0] == "test_ip"


@mock.patch('tendrl.commons.event.Event.__init__',
            mock.Mock(return_value=None))
@mock.patch('tendrl.commons.message.Message.__init__',
            mock.Mock(return_value=None))
def test_expand_gluster():
    setattr(__builtin__, "NS", maps.NamedDict())
    NS.publisher_id = "node_context"
    NS.config = maps.NamedDict()
    NS.config.data = maps.NamedDict()
    NS.config.data['glusterfs_repo'] = "test_gluster"
    param = maps.NamedDict()
    param["job_id"] = "test_id"
    param["flow_id"] = "test_flow_id"
    param['TendrlContext.integration_id'] = "test_integration_id"
    param["Cluster.node_configuration"] = {"test_node": maps.NamedDict(role="mon",provisioning_ip="test_ip")}
    NS.gluster_provisioner = importlib.import_module("tendrl.commons.tests.fixtures.plugin").Plugin()
    with pytest.raises(FlowExecutionFailedError):
        gluster_help.expand_gluster(param)
    NS.config.data['glusterfs_repo'] = "gluster"
    gluster_help.expand_gluster(param)
    param["Cluster.node_configuration"] = {"test_node": maps.NamedDict(role="mon",provisioning_ip="test")}
    gluster_help.expand_gluster(param)
