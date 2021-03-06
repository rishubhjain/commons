import uuid

import etcd
import gevent

from tendrl.commons.event import Event
from tendrl.commons import flows
from tendrl.commons.flows.create_cluster.ceph_help import create_ceph
from tendrl.commons.flows.create_cluster.gluster_help import create_gluster
from tendrl.commons.flows.create_cluster import utils as create_cluster_utils
from tendrl.commons.flows.exceptions import FlowExecutionFailedError
from tendrl.commons.message import ExceptionMessage
from tendrl.commons.message import Message
from tendrl.commons.objects.job import Job


class CreateCluster(flows.BaseFlow):
    def run(self):
        try:
            # Locking nodes
            create_cluster_utils.acquire_node_lock(self.parameters)
            integration_id = self.parameters['TendrlContext.integration_id']
            if integration_id is None:
                raise FlowExecutionFailedError("TendrlContext.integration_id "
                                               "cannot be empty")
            supported_sds = NS.compiled_definitions.get_parsed_defs()[
                'namespace.tendrl']['supported_sds']
            sds_name = self.parameters["TendrlContext.sds_name"]
            if sds_name not in supported_sds:
                raise FlowExecutionFailedError("SDS (%s) not supported" %
                                               sds_name)

            # Check if cluster name contains space char and fail if so
            if ' ' in self.parameters['TendrlContext.cluster_name']:
                Event(
                    Message(
                        priority="error",
                        publisher=NS.publisher_id,
                        payload={
                            "message": "Space char not allowed in cluster name"
                        },
                        job_id=self.job_id,
                        flow_id=self.parameters['flow_id'],
                        cluster_id=NS.tendrl_context.integration_id,
                    )
                )
                raise FlowExecutionFailedError(
                    "Space char not allowed in cluster name"
                )

            # Execute super run() to execute pre-runs
            # Note: this super call would make execution of atom's pre_run,
            # run and post_run
            # Currently there is no atoms defined for create cluster flow.
            # TODO(team): break down run() into run_pre(), run_atom(),
            # run_post() where we run the pre_runs, atoms, post_runs
            # respectively so run() simply calls run_pre(), run_atom(),
            # run_post()
            super(CreateCluster, self).run()

            ssh_job_ids = []
            if "ceph" in sds_name:
                ssh_job_ids = create_cluster_utils.ceph_create_ssh_setup_jobs(
                    self.parameters
                )
            else:
                create_cluster_utils.install_gdeploy()
                create_cluster_utils.install_python_gdeploy()
                ssh_job_ids = \
                    create_cluster_utils.gluster_create_ssh_setup_jobs(
                        self.parameters
                    )

            while True:
                gevent.sleep(3)
                all_status = {}
                for job_id in ssh_job_ids:
                    # noinspection PyUnresolvedReferences
                    all_status[job_id] = NS._int.client.read(
                        "/queue/%s/status" % job_id).value

                _failed = {_jid: status for _jid, status in
                           all_status.iteritems() if status == "failed"}
                if _failed:
                    raise FlowExecutionFailedError(
                        "SSH setup failed for jobs %s cluster %s" % (str(
                            _failed), integration_id))
                if all([status == "finished" for status in
                        all_status.values()]):
                    Event(
                        Message(
                            job_id=self.parameters['job_id'],
                            flow_id=self.parameters['flow_id'],
                            priority="info",
                            publisher=NS.publisher_id,
                            payload={"message": "SSH setup completed for all "
                                                "nodes in cluster %s" %
                                                integration_id
                                     }
                        )
                    )
                    # set this node as gluster provisioner
                    if "gluster" in self.parameters["TendrlContext.sds_name"]:
                        tags = ["provisioner/%s" % integration_id]
                        NS.node_context = NS.node_context.load()
                        tags += NS.node_context.tags
                        NS.node_context.tags = list(set(tags))
                        NS.node_context.save()
                    break

            Event(
                Message(
                    job_id=self.parameters['job_id'],
                    flow_id=self.parameters['flow_id'],
                    priority="info",
                    publisher=NS.publisher_id,
                    payload={"message": "Starting SDS install and config %s"
                                        % integration_id
                             }
                )
            )

            # SSH setup jobs finished above, now install sds bits and create
            #  cluster
            if "ceph" in sds_name:
                Event(
                    Message(
                        job_id=self.parameters['job_id'],
                        flow_id=self.parameters['flow_id'],
                        priority="info",
                        publisher=NS.publisher_id,
                        payload={"message": "Creating Ceph Storage Cluster "
                                            "%s" % integration_id
                                 }
                    )
                )

                self.parameters.update({'create_mon_secret': True})
                create_ceph(self.parameters)
            else:
                Event(
                    Message(
                        job_id=self.parameters['job_id'],
                        flow_id=self.parameters['flow_id'],
                        priority="info",
                        publisher=NS.publisher_id,
                        payload={"message": "Creating Gluster Storage "
                                            "Cluster %s" % integration_id
                                 }
                    )
                )

                create_gluster(self.parameters)

            # Wait till detected cluster in populated for nodes
            Event(
                Message(
                    job_id=self.parameters['job_id'],
                    flow_id=self.parameters['flow_id'],
                    priority="info",
                    publisher=NS.publisher_id,
                    payload={"message": "SDS install and config completed, "
                                        "Waiting for tendrl-node-agent to "
                                        "detect newly installed sds details "
                                        "%s %s" % (integration_id,
                                                   self.parameters['Node[]'])
                             }
                )
            )

            while True:
                gevent.sleep(3)
                all_status = []
                for node in self.parameters['Node[]']:
                    try:
                        NS._int.client.read(
                            "/nodes/%s/DetectedCluster/detected_cluster_id"
                            % node)
                        all_status.append(True)
                    except etcd.EtcdKeyNotFound:
                        all_status.append(False)
                if all_status:
                    if all(all_status):
                        break

            # Create the params list for import cluster flow
            new_params = dict()
            new_params['Node[]'] = self.parameters['Node[]']
            new_params['TendrlContext.integration_id'] = integration_id

            # Get node context for one of the nodes from list
            detected_cluster_id = NS._int.client.read(
                "nodes/%s/DetectedCluster/detected_cluster_id" %
                self.parameters['Node[]'][0]
            ).value
            sds_pkg_name = NS._int.client.read(
                "nodes/%s/DetectedCluster/sds_pkg_name" % self.parameters[
                    'Node[]'][0]
            ).value
            if "gluster" in sds_pkg_name:
                new_params['gdeploy_provisioned'] = True
            sds_pkg_version = NS._int.client.read(
                "nodes/%s/DetectedCluster/sds_pkg_version" %
                self.parameters['Node[]'][0]
            ).value
            new_params['DetectedCluster.sds_pkg_name'] = \
                sds_pkg_name
            new_params['DetectedCluster.sds_pkg_version'] = \
                sds_pkg_version
            new_params['import_after_create'] = True
            payload = {"tags": ["detected_cluster/%s" % detected_cluster_id],
                       "run": "tendrl.flows.ImportCluster",
                       "status": "new",
                       "parameters": new_params,
                       "parent": self.parameters['job_id'],
                       "type": "node"
                       }
            _job_id = str(uuid.uuid4())

            # release lock before import cluster
            create_cluster_utils.release_node_lock(
                self.parameters
            )

            # Persist the cluster's extra details
            _cluster = NS.tendrl.objects.Cluster(
                integration_id=self.parameters['TendrlContext.integration_id'],
                public_network=self.parameters.get('Cluster.public_network'),
                cluster_network=self.parameters.get('Cluster.cluster_network')
            )
            _cluster.save()

            import_job = Job(job_id=_job_id,
                             status="new",
                             payload=payload)
            import_job.save()

            Event(
                Message(
                    job_id=self.parameters['job_id'],
                    flow_id=self.parameters['flow_id'],
                    priority="info",
                    publisher=NS.publisher_id,
                    payload={"message": "Please wait while Tendrl imports "
                                        "newly created %s SDS Cluster %s"
                             " Import job id :%s" % (sds_pkg_name,
                                                     integration_id, _job_id)
                             }
                )
            )
            while True:
                gevent.sleep(3)
                import_job = import_job.load()
                _cluster = _cluster.load()
                if import_job.status == "failed":
                    _msg = "Importing newly created cluster failed! \n" \
                           "Failed job id :%s" % _job_id
                    Event(
                        Message(
                            job_id=self.parameters['job_id'],
                            flow_id=self.parameters['flow_id'],
                            priority="error",
                            publisher=NS.publisher_id,
                            payload={
                                "message": _msg
                                }
                        )
                    )

                    raise FlowExecutionFailedError(_msg)

                if _cluster.sync_status == "done":
                    Event(
                        Message(
                            job_id=self.parameters['job_id'],
                            flow_id=self.parameters['flow_id'],
                            priority="info",
                            publisher=NS.publisher_id,
                            payload={
                                "message": "Success! Cluster (%s) is "
                                           "ready for "
                                           "use" % integration_id
                                }
                        )
                    )

                    break

        except Exception as ex:
            # For traceback
            Event(
                ExceptionMessage(
                    priority="error",
                    publisher=NS.publisher_id,
                    payload={"message": ex.message,
                             "exception": ex
                             }
                )
            )
            # raising exception to mark job as failed
            raise ex
        finally:
            # releasing nodes if any exception came
            create_cluster_utils.release_node_lock(self.parameters)
