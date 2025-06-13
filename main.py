from aiohttp import web
import os

async def health_check(request):
    return web.json_response({"status": "Core is running"})

app = web.Application()
app.add_routes([web.get('/', health_check)])

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    web.run_app(app, host='0.0.0.0', port=port)