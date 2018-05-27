from sanic import Sanic
from sanic.response import json
from sanic_prometheus import monitor

app = Sanic()

@app.route('/')
async def test(request):
    return json({'hello': 'world'})

if __name__ == '__main__':
    monitor(app).expose_endpoint()
    app.run(host='0.0.0.0', port=80)
