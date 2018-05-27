from kubernetes.client.configuration import Configuration
from kubernetes.client.api_client import ApiClient
from kubernetes import client, config, watch

from pprint import pprint
from copy import deepcopy
import requests
from time import sleep

import traceback
from retry import retry

_metrics = {}


def metric(cls):
    name = cls.__name__
    name = name[0].lower() + name[1:]
    _metrics[name] = cls
    return cls


@metric
class HttpErrorRate:
    def __init__(self, pods, **kwargs):
        self.pods = pods
        self.threshold = kwargs.get('threshold', 1)
        self.min_request_count = kwargs.get('minRequestCount', 100)

    def check(self):
        # Here be dragons
        json = requests.get("http://192.168.99.100:30900/api/v1/query?query=sanic_request_count").json()
        results = json['data']['result']
        
        oks = 0
        non_oks = 0
        print(self.pods)

        for metric in filter(lambda result: result['metric']['pod'] in self.pods, results):
            if metric['metric']['http_status'] == '200':
                oks += int(metric['value'][1])
            else:
                non_oks += int(metric['value'][1])

        total_request_count = oks + non_oks
        print(f"Total request count: {total_request_count}")
        # If we don't have enough data, make the check fail
        if total_request_count < self.min_request_count:
            return False
        error_rate = (100 * non_oks)/(oks + non_oks)
        print(f"Error rate: {error_rate}")
        return error_rate < self.threshold

DEFAULT_METRICS = []

class CanaryDeployment:
    def __init__(self, api_object, api_client):
        self._api_object = api_object
        if 'status' not in self._api_object:
            self._api_object['status'] = {}
        self._api_client = api_client

    def get_deployment_name(self):
        return self.get_deployment_template()['metadata']['name']

    def get_deployment_template(self):
        return self._api_object['spec']['deploymentTemplate']

    def get_canary_deployment_pods(self):
        api = client.CoreV1Api(self._api_client)
        ret = api.list_pod_for_all_namespaces(watch=False)
        pods = []
        for pod in ret.items:
            if pod.metadata.name.startswith(self.get_deployment_name() + '-canary'):
                pods.append(pod.metadata.name)
        return pods
        
    def create_deployment(self):
        api = client.AppsV1Api(self._api_client)
        deployment_template = deepcopy(self.get_deployment_template())
        deployment_template['metadata']['labels']['tier'] = 'canary'
        deployment_template['metadata']['name'] += '-canary'

        try:
            response = api.create_namespaced_deployment(
                namespace=deployment_template['metadata'].get('namespace', 'default'),
                body=deployment_template,
            )
        except client.rest.ApiException as e:
            if e.status == 409:
                # HTTP 409 Conflict, deployment already exists
                pass
            else:
                raise
        self._api_object['status']['deploymentCreated'] = True
        self.update_api()

    def check_metrics(self):
        metrics = []
        for metric in self._api_object['spec'].get('metrics', DEFAULT_METRICS):
            kind = metric['kind']
            MetricClass = _metrics[kind]
            m = MetricClass(self.get_canary_deployment_pods(), **metric)
            metrics.append(m)
        result = all(m.check() for m in metrics)
        self._api_object['status']['metricsChecked'] = True
        self.update_api()
        return result

    # The Kubernetes API fails intermittently, at least locally
    def update_api(self):
        # Can't PATCH with resourceVersion specified
        if 'resourceVersion' in self._api_object['metadata']:
            del self._api_object['metadata']['resourceVersion']
        crds = client.CustomObjectsApi(self._api_client)
        crds.patch_namespaced_custom_object(
            DOMAIN,
            VERSION,
            self._api_object['metadata']['namespace'],
            RESOURCE_NAME,
            self._api_object['metadata']['name'],
            self._api_object
        )

    def replace_deployment(self):
        api = client.AppsV1Api(self._api_client)
        deployment_template = self.get_deployment_template()
        api.patch_namespaced_deployment(
            deployment_template['metadata']['name'],
            deployment_template['metadata'].get('namespace', 'default'),
            deployment_template,
        )
        self._api_object['status']['deploymentReplaced'] = True
        self.update_api()

    def delete_canary_deployment(self):
        api = client.AppsV1Api(self._api_client)
        
        try:
            api.delete_namespaced_deployment(
                self.get_deployment_name() + '-canary',
                self.get_deployment_template()['metadata'].get('namespace', 'default'),
                client.V1DeleteOptions(),
            )
        except client.rest.ApiException as e:
            if e.status == 404:
                # Already deleted
                pass
            else:
                raise
        self._api_object['status']['deletedCanaryDeployment'] = True
        self.update_api()


    def run(self):
        if not self._api_object['status'].get('deploymentCreated', False):
            print("Creating deployment")
            self.create_deployment()
        if not self._api_object['status'].get('metricsChecked', False):
            print("Sleeping before checking metrics")
            sleep(60)
            print("Checking metrics")
            metrics_ok = self.check_metrics()
            self._api_object['status']['metricsOk'] = metrics_ok
            self.update_api()
        if (self._api_object['status'].get('metricsOk', False)
            and not self._api_object['status'].get('deploymentReplaced', False)):
            print("Metrics OK, replacing main deployment")
            self.replace_deployment()
        if not self._api_object['status'].get('deletedCanaryDeployment', False):
            print("Deleting canary deployment")
            self.delete_canary_deployment()

DOMAIN = "canarying.mozilla.com"
VERSION = "v1alpha1"
RESOURCE_NAME = "canarydeployments"
        

def main():
    config.load_kube_config()
    api_client = client.api_client.ApiClient()
    crds = client.CustomObjectsApi(api_client)
    stream = watch.Watch().stream(crds.list_cluster_custom_object, DOMAIN, VERSION, RESOURCE_NAME)
    for event in stream:
        obj, event_type = event['object'], event['type']
        if event_type != 'ADDED':
            continue
        cd = CanaryDeployment(obj, api_client)
        try:
            cd.run()
        except Exception as e:
            traceback.print_exc()


if __name__ == '__main__':
    main()
