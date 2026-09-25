from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

router = APIRouter()


@router.get("/media/{key:path}")
def media(key: str, request: Request) -> Response:
    try:
        found = request.app.state.storage.get(key)
    except ValueError as exc:
        raise HTTPException(status_code=404) from exc
    if found is None:
        raise HTTPException(status_code=404)
    data, content_type = found
    # Keys contain a random id per upload, so the bytes behind a URL never change.
    return Response(
        data,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
