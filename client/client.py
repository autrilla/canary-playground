import aiohttp
import asyncio
import sys

import itertools
import collections

batch_size = 1000
sleep_time = 1

async def fetch(session, url):
    async with session.get(url) as response:
        return response

async def run_batch():
    async with aiohttp.ClientSession() as session:
        http_codes = collections.defaultdict(int) 
        rsps = [session.get(url) for _ in range(batch_size)]
        for rsp in asyncio.as_completed(rsps):
            rsp = await rsp
            http_codes[rsp.status] += 1
        print(f'HTTP status codes: {dict(http_codes)}')

async def main():
    while True:
        await run_batch()
        await asyncio.sleep(sleep_time)

url = sys.argv[1]
loop = asyncio.get_event_loop()
loop.run_until_complete(main())
