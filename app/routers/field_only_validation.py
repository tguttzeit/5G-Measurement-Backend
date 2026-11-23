"""Route class shared by the superuser-only routers whose 422 must not echo the request."""

from collections.abc import Callable

from fastapi import Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute


class FieldOnlyValidationErrorRoute(APIRoute):
    """Validation errors name the field and the violated constraint but never echo the
    submitted input back, unlike FastAPI's default 422 body."""

    def get_route_handler(self) -> Callable:
        default_handler = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await default_handler(request)
            except RequestValidationError as exc:
                return JSONResponse(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    content={
                        "detail": [
                            {"loc": error["loc"], "msg": error["msg"], "type": error["type"]}
                            for error in exc.errors()
                        ]
                    },
                )

        return handler
