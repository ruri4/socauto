"""Streaming VOD multipart upload adapted from TiktokAutoUploader (see signer NOTICE)."""

import json
import re
import zlib
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import quote, urlencode
from uuid import uuid4

from pydantic import BaseModel, Field, SecretStr, ValidationError

from socauto.destinations.base import PublishError
from socauto.destinations.tiktok.aws import UploadCredentials, VODAuth
from socauto.destinations.tiktok.http import TikTokHTTP, check_status

BASE_URL = "https://www.tiktok.com"
CHUNK_SIZE = 5 * 1024 * 1024
UPLOAD_DOMAINS = (
    "tiktok.com",
    "byteoversea.com",
    "ibytedtos.com",
    "bytedanceapi.com",
    "tiktokcdn.com",
)


class StoreInfo(BaseModel):
    StoreUri: str = Field(min_length=1)
    Auth: SecretStr = Field(min_length=1)


class UploadNode(BaseModel):
    Vid: str = Field(min_length=1)
    SessionKey: SecretStr = Field(min_length=1)
    UploadHost: str = Field(min_length=1)
    StoreInfos: list[StoreInfo] = Field(min_length=1)


def vod_url(action: str, **extra: str) -> str:
    return (
        BASE_URL
        + "/top/v1?"
        + urlencode(
            {
                "Action": action,
                "Version": "2020-11-19",
                "SpaceName": "tiktok",
                **extra,
            }
        )
    )


def vod_result(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = payload.get("ResponseMetadata")
    if not isinstance(metadata, dict) or metadata.get("Error"):
        raise PublishError("tiktok_vod_rejected")
    result = payload.get("Result")
    if not isinstance(result, dict) or not result:
        raise PublishError("tiktok_invalid_response")
    return result


def storage_url(node: UploadNode) -> str:
    host = node.UploadHost.lower()
    if not re.fullmatch(r"[a-z0-9.-]+", host) or not any(
        host == domain or host.endswith("." + domain) for domain in UPLOAD_DOMAINS
    ):
        raise PublishError("tiktok_upload_host_rejected")
    uri = node.StoreInfos[0].StoreUri
    if uri.startswith("/") or any(part in ("", ".", "..") for part in uri.split("/")):
        raise PublishError("tiktok_invalid_response")
    return f"https://{host}/{quote(uri, safe='/')}"


def check_storage(payload: dict[str, Any], crc: str | None = None) -> None:
    code = payload.get("code")
    nested_error = payload.get("error")
    nested_success = (
        type(payload.get("success")) is int
        and payload.get("success") == 0
        and isinstance(nested_error, dict)
        and type(nested_error.get("code")) is int
        and nested_error.get("code") == 200
        and type(nested_error.get("error_code")) is int
        and nested_error.get("error_code") == 0
        and type(nested_error.get("error")) is str
        and nested_error.get("error") == ""
        and type(nested_error.get("message")) is str
        and nested_error.get("message") == ""
    )
    if (type(code) is not int or code not in (0, 2000)) and not nested_success:
        raise PublishError("tiktok_chunk_rejected")
    data = payload.get("data")
    if crc is not None and isinstance(data, dict) and "crc32" in data and data["crc32"] != crc:
        raise PublishError("tiktok_chunk_crc_mismatch")


class VideoTransfer:
    def __init__(self, api: TikTokHTTP, storage: TikTokHTTP) -> None:
        self.api = api
        self.storage = storage

    def upload(self, media: Path) -> str:
        try:
            with media.open("rb") as source:
                source.seek(0, 2)
                size = source.tell()
                source.seek(0)
                if size <= 0:
                    raise PublishError("tiktok_invalid_media")
                return self._upload(source, size)
        except OSError:
            raise PublishError("tiktok_media_unreadable") from None

    def _upload(self, source: BinaryIO, size: int) -> str:
        payload = self.api.request(
            "GET", BASE_URL + "/api/v1/video/upload/auth/?aid=1988", retry_safe=True
        )
        check_status(payload)
        try:
            credentials = UploadCredentials.model_validate(payload.get("video_token_v5"))
        except ValidationError:
            raise PublishError("tiktok_invalid_upload_credentials") from None
        auth = VODAuth(credentials)
        apply_url = vod_url(
            "ApplyUploadInner",
            FileType="video",
            IsInner="1",
            FileSize=str(size),
            s="g158iqx8434",
        )
        applied = vod_result(
            self.api.request(
                "GET",
                apply_url,
                headers=auth.headers("GET", apply_url),
                retry_safe=True,
            )
        )
        try:
            nodes = applied["InnerUploadAddress"]["UploadNodes"]
            if not isinstance(nodes, list) or not nodes:
                raise ValueError
            node = UploadNode.model_validate(nodes[0])
        except KeyError, TypeError, ValueError:
            raise PublishError("tiktok_invalid_upload_address") from None
        url = storage_url(node)
        upload_id = str(uuid4())
        authorization = node.StoreInfos[0].Auth.get_secret_value()
        crcs: list[str] = []
        transferred = 0
        while chunk := source.read(CHUNK_SIZE):
            transferred += len(chunk)
            if transferred > size:
                raise PublishError("tiktok_media_changed")
            crc = f"{zlib.crc32(chunk) & 0xFFFFFFFF:08x}"
            part = len(crcs) + 1
            payload = self.storage.request(
                "POST",
                url
                + "?"
                + urlencode(
                    {
                        "partNumber": part,
                        "uploadID": upload_id,
                        "phase": "transfer",
                    }
                ),
                data=chunk,
                headers={
                    "Authorization": authorization,
                    "Content-Type": "application/octet-stream",
                    "Content-Disposition": 'attachment; filename="video.mp4"',
                    "Content-Crc32": crc,
                },
                retry_safe=True,
            )
            check_storage(payload, crc)
            crcs.append(f"{part}:{crc}")
        if transferred != size:
            raise PublishError("tiktok_media_changed")
        finished = self.storage.request(
            "POST",
            url
            + "?"
            + urlencode(
                {
                    "uploadID": upload_id,
                    "phase": "finish",
                    "uploadmode": "part",
                }
            ),
            headers={"Authorization": authorization, "Content-Type": "text/plain;charset=UTF-8"},
            data=",".join(crcs).encode(),
        )
        check_storage(finished)
        commit_url = vod_url("CommitUploadInner")
        commit_body = json.dumps(
            {
                "SessionKey": node.SessionKey.get_secret_value(),
                "Functions": [{"name": "GetMeta"}],
            },
            separators=(",", ":"),
        ).encode()
        committed = vod_result(
            self.api.request(
                "POST",
                commit_url,
                headers=auth.headers("POST", commit_url, commit_body),
                data=commit_body,
            )
        )
        results = committed.get("Results")
        if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], dict):
            raise PublishError("tiktok_invalid_commit_response")
        result = results[0]
        vid = result.get("Vid")
        if not isinstance(vid, str) or not vid or vid != node.Vid:
            raise PublishError("tiktok_commit_rejected")
        if "Code" in result and (type(result["Code"]) is not int or result["Code"] != 2000):
            raise PublishError("tiktok_commit_rejected")
        return node.Vid
