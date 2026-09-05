"""Replaceable TikTok HTTP publishing adapter. See signer/tiktok/NOTICE.md."""

import json
import re
import secrets
import string
import time
from collections.abc import Callable
from html import escape
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlencode

import requests
from pydantic import ValidationError

from socauto.config import Settings
from socauto.destinations.base import PublishError, PublishResult
from socauto.destinations.tiktok.http import TikTokHTTP, check_status
from socauto.destinations.tiktok.session import TikTokSession
from socauto.destinations.tiktok.signer import PUBLISH_URL, BunSigner, Signer, validate_signed_url
from socauto.destinations.tiktok.transfer import BASE_URL, VideoTransfer


def publish_payload(
    creation_id: str, video_id: str, caption: str, visibility: Literal[0, 1]
) -> dict[str, Any]:
    # TikTok offsets count UTF-16 code units, not Python Unicode codepoints.
    tags = [
        {
            "start": len(caption[: match.start()].encode("utf-16-le")) // 2,
            "end": len(caption[: match.end()].encode("utf-16-le")) // 2,
            "hashtag_name": match.group(1),
            "type": 1,
            "user_id": "",
            "tag_id": str(index),
        }
        for index, match in enumerate(re.finditer(r"(?<!\w)#(\w+)", caption))
    ]
    markup: list[str] = []
    previous = 0
    for index, match in enumerate(re.finditer(r"(?<!\w)#(\w+)", caption)):
        markup.extend(
            [
                escape(caption[previous : match.start()]),
                f'<h id="{index}">{escape(match.group())}</h>',
            ]
        )
        previous = match.end()
    markup.append(escape(caption[previous:]))
    return {
        "post_common_info": {"creation_id": creation_id, "enter_post_page_from": 1, "post_type": 3},
        "feature_common_info_list": [
            {
                "geofencing_regions": [],
                "playlist_name": "",
                "playlist_id": "",
                "tcm_params": '{"commerce_toggle_info":{}}',
                "sound_exemption": 0,
                "anchors": [],
                "vedit_common_info": {"draft": "", "video_id": video_id},
                "privacy_setting_info": {
                    "visibility_type": visibility,
                    "allow_duet": 0,
                    "allow_stitch": 0,
                    "allow_comment": 1,
                },
            }
        ],
        "single_post_req_list": [
            {
                "batch_index": 0,
                "video_id": video_id,
                "is_long_video": 0,
                "single_post_feature_info": {
                    "text": caption,
                    "text_extra": tags,
                    "markup_text": "".join(markup),
                    "music_info": {},
                    "poster_delay": 0,
                },
            }
        ],
    }


class TikTokDestination:
    def __init__(
        self,
        settings: Settings,
        session: TikTokSession,
        *,
        signer: Signer | None = None,
        session_factory: Callable[[], requests.Session] = requests.Session,
    ) -> None:
        self.settings = settings
        self.session = session
        self.signer = signer or BunSigner(settings)
        self.session_factory = session_factory

    def publish(
        self,
        media: Path,
        caption: str,
        *,
        visibility: Literal[0, 1] = 1,
        before_publish: Callable[[], None] | None = None,
    ) -> PublishResult:
        try:
            caption_length = len(caption.encode("utf-16-le")) // 2
        except UnicodeError:
            raise PublishError("tiktok_invalid_publish_options") from None
        if caption_length > 2200 or visibility not in (0, 1):
            raise PublishError("tiktok_invalid_publish_options")
        if not media.is_file() or media.suffix.lower() != ".mp4":
            raise PublishError("tiktok_invalid_media")
        # Revalidate at call time: a stored session can expire after it was loaded.
        try:
            credentials = TikTokSession.model_validate(self.session.model_dump())
        except ValidationError:
            raise PublishError("tiktok_session_expired") from None
        with self.session_factory() as api_session, self.session_factory() as storage_session:
            for client in (api_session, storage_session):
                client.trust_env = False  # No implicit proxies or netrc credentials.
                client.headers.update({"User-Agent": credentials.user_agent})
            self._cookies(api_session, credentials)
            api_session.headers.update({"Referer": BASE_URL + "/", "Origin": BASE_URL})
            api = self._http(api_session)
            storage = self._http(storage_session)
            creation = "".join(
                secrets.choice(string.ascii_letters + string.digits) for _ in range(21)
            )
            project = api.request(
                "POST",
                BASE_URL
                + "/api/v1/web/project/create/?"
                + urlencode(
                    {
                        "creation_id": creation,
                        "type": 1,
                        "aid": 1988,
                    }
                ),
            )
            check_status(project)
            if (
                not isinstance(project.get("project"), dict)
                or not isinstance(project["project"].get("project_id"), str)
                or not project["project"]["project_id"]
            ):
                raise PublishError("tiktok_invalid_project_response")
            video_id = VideoTransfer(api, storage).upload(media)
            api.request("HEAD", BASE_URL + "/", retry_safe=True, json_response=False)
            tokens = [
                cookie.value
                for cookie in api_session.cookies
                if cookie.name == "msToken"
                and not cookie.is_expired()
                and cookie.domain.lstrip(".") in ("tiktok.com", "www.tiktok.com")
            ]
            if not tokens or not tokens[-1]:
                raise PublishError("tiktok_ms_token_missing")
            url = (
                PUBLISH_URL
                + "?"
                + urlencode(
                    {
                        "app_name": "tiktok_web",
                        "channel": "tiktok_web",
                        "device_platform": "web",
                        "aid": 1988,
                        "msToken": tokens[-1],
                    }
                )
            )
            signed = self.signer.sign(url, credentials.user_agent)
            validate_signed_url(url, signed)
            if requests.Request("POST", signed).prepare().url != signed:
                raise PublishError("tiktok_signer_invalid_output")
            if before_publish is not None:
                before_publish()
            response = api.request(
                "POST",
                signed,
                publishing=True,
                data=json.dumps(publish_payload(creation, video_id, caption, visibility)).encode(),
                headers={"Content-Type": "application/json"},
            )
            check_status(response, publishing=True)
            # No invented post URL: upstream acknowledgement may not include a public item ID.
            post_id = response.get("item_id")
            return PublishResult(
                creation_id=creation,
                video_id=video_id,
                post_id=post_id if isinstance(post_id, str) and post_id.isdecimal() else None,
            )

    def _http(self, session: requests.Session) -> TikTokHTTP:
        return TikTokHTTP(
            session,
            attempts=self.settings.tiktok_http_attempts,
            timeout=self.settings.tiktok_http_timeout_seconds,
        )

    @staticmethod
    def _cookies(client: requests.Session, session: TikTokSession) -> None:
        now = time.time()
        required: set[str] = set()
        for cookie in session.cookies:
            domain = (cookie.domain or ".tiktok.com").lower()
            if domain.lstrip(".") not in ("tiktok.com", "www.tiktok.com"):
                continue
            if cookie.expires_at is not None and cookie.expires_at <= now:
                continue
            if cookie.path != "/":
                continue
            client.cookies.set(
                cookie.name,
                cookie.value,
                domain=domain,
                path="/",
                secure=True,
                expires=cookie.expires_at,
            )
            required.add(cookie.name)
        if not {"sessionid", "tt-target-idc"} <= required:
            raise PublishError("tiktok_session_invalid")
