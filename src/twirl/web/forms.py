from pydantic import BaseModel, ValidationError
from starlette.datastructures import FormData
from starlette.requests import Request


async def form_data(request: Request) -> FormData:
    return await request.form()


def validate_form[M: BaseModel](
    model_cls: type[M], form: FormData, list_fields: tuple[str, ...] = ()
) -> tuple[M | None, dict[str, str]]:
    data: dict = {key: form.get(key) for key in form.keys() if key not in list_fields}
    for key in list_fields:
        data[key] = form.getlist(key)
    data.pop("csrf_token", None)
    try:
        return model_cls.model_validate(data), {}
    except ValidationError as exc:
        return None, {
            str(err["loc"][0]) if err["loc"] else "__all__": err["msg"] for err in exc.errors()
        }
