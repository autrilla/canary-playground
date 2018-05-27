from invoke import task
import requests
from collections import defaultdict

app_name = "app-deployment"
canary_name = "app-canary-deployment"

@task
def build_good(c):
    c.run("docker build -t app:good app_good")

@task
def build_bad(c):
    c.run("docker build -t app:bad app_bad")

@task
def build(c):
    build_good(c)
    build_bad(c)

@task
def deploy(c):
    c.run("kubectl apply -f deployment.yaml")

def get_http_200_percent(pod_prefix):
    json = requests.get("http://192.168.99.100:30900/api/v1/query?query=sanic_request_count").json()
    results = json['data']['result']

    oks = 0
    non_oks = 0
    
    for metric in filter(lambda result: result['metric']['pod'].startswith(pod_prefix), results):
        if metric['metric']['http_status'] == '200':
            oks += int(metric['value'][1])
        else:
            non_oks += int(metric['value'][1])
    return (100 * oks)/(oks + non_oks)

@task
def check_canary_metrics(c):
    print(get_http_200_percent(app_name))
    print(get_http_200_percent(canary_name))

@task
def canary(c, tag="bad"):
    print(f'Canarying tag "{tag}"')
    c.run("kubectl apply -f canary.yaml")
