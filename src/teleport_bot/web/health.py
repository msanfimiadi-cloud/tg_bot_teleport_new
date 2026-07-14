from aiohttp import web


async def health(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


def create_health_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health", health)
    return app
